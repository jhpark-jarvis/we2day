"""Offline credential preparation. Existing files and all databases remain untouched."""

import argparse
import base64
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from types import SimpleNamespace

from we2day_api.push import push_configuration


def prepare(api_env: Path, destination: Path, host: str, project: str):
    if not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", host):
        raise ValueError("invalid_pooler_host")
    if not re.fullmatch(r"[a-z]{20}", project):
        raise ValueError("invalid_project")
    values = {}
    for line in api_env.read_text(encoding="utf-8").splitlines():
        key, mark, value = line.partition("=")
        if mark and key in {
            "WE2DAY_PUSH_ENABLED",
            "WE2DAY_PUSH_PRIVATE_KEY",
            "WE2DAY_PUSH_SUBJECT",
        }:
            if key in values:
                raise ValueError("duplicate_push_setting")
            values[key] = value
    config = push_configuration(
        SimpleNamespace(
            push_enabled=values.get("WE2DAY_PUSH_ENABLED") == "true",
            push_private_key=values.get("WE2DAY_PUSH_PRIVATE_KEY"),
            push_subject=values.get("WE2DAY_PUSH_SUBJECT"),
        )
    )
    if config is None:
        raise ValueError("push_not_configured")
    password = secrets.token_urlsafe(48)
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
    stored = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    encoded = [base64.b64encode(v).decode() for v in (salt, stored, server)]
    verifier = f"SCRAM-SHA-256$4096:{encoded[0]}${encoded[1]}:{encoded[2]}"
    dsn = (
        f"postgresql://we2day_reminder_worker.{project}:{password}@{host}:5432/postgres"
        "?sslmode=verify-full&sslrootcert=/run/we2day/supabase-ca.crt"
    )
    files = {
        "worker.env": "WE2DAY_REMINDER_WORKER_ENABLED=false\nWE2DAY_REMINDER_DATABASE_URL="
        + dsn
        + "\n"
        + "\n".join(f"{k}={v}" for k, v in values.items())
        + "\n",
        "worker-login.sql": "-- New dedicated worker login only; no existing account reset.\n"
        + "alter role we2day_reminder_worker login password '"
        + verifier
        + "';\n",
    }
    destination.mkdir(mode=0o700)  # Must be a new, operator-private directory.
    created = []
    try:
        for name, content in files.items():
            path = destination / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(content)
    except Exception:
        for path in created:
            path.unlink()
        destination.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Prepare private worker credentials without DB access"
    )
    parser.add_argument("--api-env", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--pooler-host", required=True)
    parser.add_argument("--project-ref", required=True)
    args = parser.parse_args()
    try:
        prepare(args.api_env, args.directory, args.pooler_host, args.project_ref)
        print("PASS: private disabled worker env and login SQL; no network or credential output")
        return 0
    except Exception:
        print("FAIL: new private directory, valid Push configuration and pooler details required")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
