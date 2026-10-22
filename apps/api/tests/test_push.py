import base64
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401

from we2day_api import push
from we2day_api.config import Settings

ENDPOINT = "https://fcm.googleapis.com/fcm/send/synthetic-device"


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def keys():
    private = ec.generate_private_key(ec.SECP256R1())
    public = b64(
        private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    raw = b64(private.private_numbers().private_value.to_bytes(32, "big"))
    return raw, public


def manage(dsn, user, action, endpoint=ENDPOINT, public=None):
    public = public or keys()[1]
    return call(
        dsn, user, "manage_push_subscription", action, endpoint, public, b64(b"a" * 16), public
    )[0]


def test_push_rls_cooldown_revocation_expiry_and_limits(database_url):
    dsn = database_url
    connect_pair(dsn)
    public = keys()[1]
    assert manage(dsn, USERS[0], "register", public=public) == {"enabled": True}
    with actor(dsn, USERS[1]) as connection:
        assert connection.execute("select * from public.push_subscriptions").fetchall() == []
    with actor(dsn, USERS[0]) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("delete from public.push_subscriptions")
    assert manage(dsn, USERS[1], "status", public=public) == {
        "enabled": False,
        "automatic_enabled": False,
    }
    with pytest.raises(psycopg.Error, match="push_registration_required"):
        manage(dsn, USERS[1], "claim", public=public)
    assert manage(dsn, USERS[1], "remove", public=public) == {"enabled": False}

    def claim(_):
        try:
            return manage(dsn, USERS[0], "claim", public=public)["endpoint"]
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert results.count(ENDPOINT) == 1 and results.count("PT409") == 1
    # Re-registering must not reset test cooldown.
    manage(dsn, USERS[0], "register", public=public)
    with pytest.raises(psycopg.Error, match="push_test_limited"):
        manage(dsn, USERS[0], "claim", public=public)
    for i in range(4):
        manage(dsn, USERS[0], "register", ENDPOINT + str(i), public)
    with pytest.raises(psycopg.Error, match="push_device_limit"):
        manage(dsn, USERS[0], "register", ENDPOINT + "excess", public)
    with psycopg.connect(dsn) as c:
        c.execute("update public.push_subscriptions set expires_at=now()-interval '1 second'")
    assert manage(dsn, USERS[0], "status", public=public)["enabled"] is False
    with pytest.raises(psycopg.Error, match="push_registration_required"):
        manage(dsn, USERS[0], "claim", public=public)
    manage(dsn, USERS[0], "register", public=public)
    manage(dsn, USERS[0], "remove_all", public=public)
    assert manage(dsn, USERS[0], "status", public=public)["enabled"] is False
    for endpoint in ["https://127.0.0.1/private", ENDPOINT + "?secret=1", ENDPOINT + "#test"]:
        with pytest.raises(psycopg.Error, match="invalid_push_subscription"):
            manage(dsn, USERS[0], "register", endpoint, public)
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.manage_push_subscription('remove_all')")


def test_push_api_safe_projection_and_disabled_cleanup(upstream, monkeypatch):  # noqa: F811
    client, calls, replies = upstream
    assert client.get("/push/config").json() == {"configured": False, "public_key": None}
    assert (
        client.post("/push/device", json={"action": "test", "endpoint": ENDPOINT}).status_code
        == 503
    )
    raw, public = keys()
    config = client.app.state.settings
    monkeypatch.setattr(config, "push_enabled", True)
    monkeypatch.setattr(config, "push_private_key", raw)
    monkeypatch.setattr(config, "push_subject", "https://example.com")
    body = {"action": "register", "endpoint": ENDPOINT, "p256dh": public, "auth": b64(b"a" * 16)}
    replies.append((200, {"enabled": True, "auth": "must-not-leak"}))
    result = client.post("/push/device", json=body)
    assert result.json() == {"enabled": True} and "no-store" in result.headers["cache-control"]
    for update in [{"endpoint": "https://127.0.0.1"}, {"p256dh": "x" * 87}, {"action": "claim"}]:
        assert client.post("/push/device", json=body | update).status_code == 422
    assert (
        client.post(
            "/push/device", content="x" * 4097, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    subscription = {"endpoint": ENDPOINT, "keys": {"p256dh": public, "auth": b64(b"a" * 16)}}
    monkeypatch.setattr(push, "deliver_test", lambda *_: "accepted")
    replies.append((200, subscription))
    result = client.post("/push/device", json={"action": "test", "endpoint": ENDPOINT})
    assert result.json() == {"accepted": True} and ENDPOINT not in result.text
    monkeypatch.setattr(push, "deliver_test", lambda *_: "expired")
    replies.extend([(200, subscription), (200, {"enabled": False})])
    assert (
        client.post("/push/device", json={"action": "test", "endpoint": ENDPOINT}).status_code
        == 409
    )
    # Fresh installations without SQL023 must retain ordinary logout.
    replies.append((404, {"code": "PGRST202"}))
    assert client.post("/push/device", json={"action": "remove_all"}).json() == {"enabled": False}
    assert raw not in result.text


def test_push_encryption_transport_restrictions_and_fixed_payload(monkeypatch):
    raw, public = keys()
    config = push.push_configuration(
        Settings(
            _env_file=None,
            push_enabled=True,
            push_private_key=raw,
            push_subject="https://example.com",
        )
    )
    captured = []

    def post(self, endpoint, **kwargs):
        captured.append((endpoint, kwargs))
        response = requests.Response()
        response.status_code = 201
        response._content = b""
        return response

    monkeypatch.setattr(push.RestrictedSession, "post", post)
    sub = {"endpoint": ENDPOINT, "keys": {"p256dh": public, "auth": b64(b"a" * 16)}}
    assert push.deliver_test(sub, config) == "accepted"
    assert captured[0][0] == ENDPOINT
    encrypted = captured[0][1]
    assert encrypted["data"] != b'{"type": "we2day-test-v1"}'
    assert "authorization" in {key.lower() for key in encrypted["headers"]}
    assert push.deliver_test(sub | {"endpoint": "https://localhost/private"}, config) == "failed"
    for endpoint in [
        ENDPOINT + "?a=1",
        "https://fcm.googleapis.com.evil.test/fcm/send/a",
        "https://user@web.push.apple.com/a",
        "https://web.push.apple.com:443/a",
    ]:
        with pytest.raises(ValueError):
            push.validate_endpoint(endpoint)


def test_restricted_transport_disables_redirects_and_proxies(monkeypatch):
    calls = []

    class Response:
        status_code = 307

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, url, **kwargs):
            calls.append((self.trust_env, url, kwargs))
            return Response()

    monkeypatch.setattr(push.requests, "Session", Session)
    response = push.RestrictedSession().post(ENDPOINT, data=b"encrypted", timeout=999)
    assert response.status_code == 307 and response.content == b""
    trust, endpoint, kwargs = calls[0]
    assert trust is False and endpoint == ENDPOINT
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["timeout"] == (2, 4)


def test_push_key_fragment_preserves_existing_file_and_hides_key(tmp_path, monkeypatch, capsys):
    output = tmp_path / "private-fragment.env"
    monkeypatch.setattr("sys.argv", ["push", "--output", str(output)])
    assert push.main() == 0
    text = output.read_text(encoding="utf-8")
    private = text.split("WE2DAY_PUSH_PRIVATE_KEY=")[1].splitlines()[0]
    assert len(push.decode_key(private, 32)) == 32
    assert "WE2DAY_PUSH_ENABLED=false" in text
    assert private not in capsys.readouterr().out
    assert push.main() == 1 and output.read_text(encoding="utf-8") == text
    assert private not in capsys.readouterr().out


def test_automatic_consent_requires_server_readiness_and_safe_projection(upstream, monkeypatch):  # noqa: F811
    client, _, replies = upstream
    raw, public = keys()
    settings = client.app.state.settings
    monkeypatch.setattr(settings, "push_enabled", True)
    monkeypatch.setattr(settings, "push_private_key", raw)
    monkeypatch.setattr(settings, "push_subject", "https://example.com")
    assert (
        client.post(
            "/push/device", json={"action": "automatic_on", "endpoint": ENDPOINT}
        ).status_code
        == 503
    )
    monkeypatch.setattr(settings, "push_automatic_enabled", True)
    assert client.get("/push/config").json()["automatic_available"] is True
    for action, value in [("automatic_on", True), ("automatic_off", False), ("status", False)]:
        replies.append((200, {"enabled": True, "automatic_enabled": value, "endpoint": "private"}))
        result = client.post("/push/device", json={"action": action, "endpoint": ENDPOINT})
        assert result.status_code == 200 and result.json()["automatic_enabled"] is value
        assert "private" not in result.text and "no-store" in result.headers["cache-control"]
    monkeypatch.setattr(settings, "push_enabled", False)
    replies.append((200, {"automatic_enabled": False}))
    assert client.post(
        "/push/device", json={"action": "automatic_off", "endpoint": ENDPOINT}
    ).json() == {"automatic_enabled": False}
