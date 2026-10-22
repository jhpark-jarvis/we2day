"""Caller-owned settings and explicit device tests; no worker DB credentials."""

import base64
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request
from py_vapid import Vapid02
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pywebpush import WebPushException, webpush

from we2day_api.calendar import Store

router = APIRouter(tags=["device-push"])
ENDPOINT = re.compile(
    r"https://(?:web\.push\.apple\.com/[A-Za-z0-9_/-]+"
    r"|fcm\.googleapis\.com/fcm/send/[A-Za-z0-9_-]+"
    r"|updates\.push\.services\.mozilla\.com/wpush/v2/[A-Za-z0-9_-]+)"
)


def decode_key(value: str, size: int) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid_key")
    data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(data) != size:
        raise ValueError("invalid_key")
    return data


def validate_endpoint(value: str) -> str:
    if len(value) > 2048 or not ENDPOINT.fullmatch(value):
        raise ValueError("invalid_endpoint")
    return value


class PushInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal[
        "register", "status", "remove", "test", "remove_all", "automatic_on", "automatic_off"
    ]
    endpoint: str = Field(default="", max_length=2048)
    p256dh: str = Field(default="", max_length=87)
    auth: str = Field(default="", max_length=22)

    @field_validator("endpoint")
    @classmethod
    def endpoint_url(cls, value: str) -> str:
        return validate_endpoint(value) if value else value


async def read_push(request: Request) -> PushInput:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "invalid_push_subscription")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 4096:
            raise HTTPException(413, "invalid_push_subscription")
        content.extend(chunk)
    try:
        body = PushInput.model_validate_json(content)
        if body.action != "remove_all" and not body.endpoint:
            raise ValueError("endpoint_required")
        if body.action == "register":
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), decode_key(body.p256dh, 65)
            )
            decode_key(body.auth, 16)
        return body
    except (ValidationError, ValueError):
        raise HTTPException(422, "invalid_push_subscription") from None


def push_configuration(settings):
    if not settings.push_enabled or not settings.push_private_key or not settings.push_subject:
        return None
    try:
        subject = settings.push_subject
        parts = urlsplit(subject)
        if not (
            (parts.scheme == "mailto" and "@" in parts.path and not parts.netloc)
            or (parts.scheme == "https" and parts.hostname and parts.hostname != "localhost")
        ) or any(ord(c) < 33 for c in subject):
            return None
        raw = decode_key(settings.push_private_key, 32)
        key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
        public = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return key, base64.urlsafe_b64encode(public).rstrip(b"=").decode(), subject
    except ValueError:
        return None


class RestrictedSession:
    """Never follow redirects, proxies, or retain/reflect a provider response body."""

    def post(self, url, **kwargs):
        validate_endpoint(url)
        kwargs.pop("timeout", None)
        with requests.Session() as session:
            session.trust_env = False
            with session.post(
                url, **kwargs, timeout=(2, 4), allow_redirects=False, stream=True
            ) as response:
                result = requests.Response()
                result.status_code = response.status_code
                result._content = b""
                return result


def deliver_test(subscription: dict, config) -> str:
    key, _, subject = config
    try:
        validate_endpoint(subscription["endpoint"])
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), decode_key(subscription["keys"]["p256dh"], 65)
        )
        decode_key(subscription["keys"]["auth"], 16)
        response = webpush(
            subscription_info=subscription,
            data=json.dumps({"type": "we2day-test-v1"}),
            vapid_private_key=Vapid02(private_key=key),
            vapid_claims={"sub": subject},
            ttl=60,
            timeout=4,
            requests_session=RestrictedSession(),
            verbose=False,
        )
        return "accepted" if 200 <= response.status_code < 300 else "failed"
    except WebPushException as error:
        if error.response is not None and error.response.status_code in {404, 410}:
            return "expired"
        return "failed"
    except (ValueError, KeyError, TypeError, requests.RequestException):
        return "failed"


@router.get("/push/config")
def push_config(request: Request, store: Store):
    config = push_configuration(request.app.state.settings)
    result = {"configured": config is not None, "public_key": config[1] if config else None}
    if request.app.state.settings.push_automatic_enabled:
        result["automatic_available"] = config is not None
    return result


@router.post("/push/device")
def device(body: Annotated[PushInput, Depends(read_push)], request: Request, store: Store):
    config = push_configuration(request.app.state.settings)
    if body.action in {"remove", "remove_all"}:
        try:
            store.rpc(
                "manage_push_subscription", {"p_action": body.action, "p_endpoint": body.endpoint}
            )
        except HTTPException as error:
            # A transactional migration absent in a fresh installation implies no subscriptions.
            if body.action != "remove_all" or error.detail != "Database setup required":
                raise
        return {"enabled": False}
    if not config:
        if body.action == "automatic_off":
            store.rpc(
                "manage_push_subscription", {"p_action": body.action, "p_endpoint": body.endpoint}
            )
            return {"automatic_enabled": False}
        raise HTTPException(503, "push_not_configured")
    if body.action == "automatic_on" and not request.app.state.settings.push_automatic_enabled:
        raise HTTPException(503, "push_not_configured")
    result = store.rpc(
        "manage_push_subscription",
        {
            "p_action": "claim" if body.action == "test" else body.action,
            "p_endpoint": body.endpoint,
            "p_p256dh": body.p256dh,
            "p_auth": body.auth,
            "p_vapid_key": config[1],
        },
    )
    if body.action != "test":
        if body.action in {"automatic_on", "automatic_off"}:
            return {"automatic_enabled": result.get("automatic_enabled") is True}
        projection = {"enabled": result.get("enabled") is True}
        if "automatic_enabled" in result:
            projection["automatic_enabled"] = result["automatic_enabled"] is True
        return projection
    outcome = deliver_test(result, config)
    if outcome == "expired":
        store.rpc("manage_push_subscription", {"p_action": "remove", "p_endpoint": body.endpoint})
        raise HTTPException(409, "push_registration_required")
    if outcome != "accepted":
        raise HTTPException(503, "push_delivery_failed")
    return {"accepted": True}


def main():
    """Create a new disabled server env fragment without printing any key."""
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Create new private Push env fragment; no network")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        private = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
        encoded = base64.urlsafe_b64encode(private.to_bytes(32, "big")).rstrip(b"=").decode()
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(
                "WE2DAY_PUSH_ENABLED=false\nWE2DAY_PUSH_PRIVATE_KEY="
                + encoded
                + "\nWE2DAY_PUSH_SUBJECT=\n"
            )
        print("PASS: new disabled server fragment; no key output or network")
        return 0
    except OSError:
        print("FAIL: new private file required; existing file preserved")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
