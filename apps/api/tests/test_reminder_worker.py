import json
from uuid import uuid4

import requests
from pywebpush import WebPushException
from test_push import ENDPOINT, b64, keys

from we2day_api import reminder_worker as worker
from we2day_api.push import push_configuration


def test_creation_payload_is_allowlisted_and_never_contains_business_text(monkeypatch):
    raw, public = keys()
    config = push_configuration(
        worker.WorkerSettings(
            push_enabled=True, push_private_key=raw, push_subject="https://example.com"
        )
    )
    subscription = {"endpoint": ENDPOINT, "keys": {"p256dh": public, "auth": b64(b"a" * 16)}}
    event = {"type": "we2day-appointment-created-v1", "date": "2026-11-13", "event": str(uuid4())}
    sent = []

    def send(**kwargs):
        sent.append(kwargs)
        response = requests.Response()
        response.status_code = 201
        return response

    monkeypatch.setattr(worker, "webpush", send)
    assert worker.deliver(subscription | {"notification": event}, config) == "accepted"
    assert json.loads(sent[0]["data"]) == event
    assert set(sent[0]["subscription_info"]) == {"endpoint", "keys"}
    for invalid in [
        event | {"date": "2026-02-30"},
        event | {"type": "other"},
        event | {"title": "private"},
        event | {"event": "invalid"},
    ]:
        assert worker.deliver(subscription | {"notification": invalid}, config) == "rejected"
    assert len(sent) == 1


def test_worker_payload_fixed_and_definite_vs_ambiguous_outcomes(monkeypatch):
    raw, public = keys()
    settings = worker.WorkerSettings(
        push_enabled=True, push_private_key=raw, push_subject="https://example.com"
    )
    config = push_configuration(settings)
    subscription = {"endpoint": ENDPOINT, "keys": {"p256dh": public, "auth": b64(b"a" * 16)}}
    captured = []

    def response(status):
        result = requests.Response()
        result.status_code = status
        return result

    for status, expected in [
        (201, "accepted"),
        (410, "expired"),
        (429, "retry"),
        (503, "retry"),
        (307, "rejected"),
        (401, "rejected"),
    ]:

        def send(_status=status, **kwargs):
            captured.append(kwargs)
            return response(_status)

        monkeypatch.setattr(worker, "webpush", send)
        assert worker.deliver(subscription, config) == expected
    assert all(
        c["data"] == '{"type": "we2day-anniversary-v1"}' and c["ttl"] == 60 for c in captured
    )
    assert "private" not in repr(settings) and raw not in repr(settings)

    for error in [
        requests.ReadTimeout("private URL"),
        WebPushException("unknown private response"),
    ]:

        def fail(_error=error, **_):
            raise _error

        monkeypatch.setattr(worker, "webpush", fail)
        assert worker.deliver(subscription, config) == "unknown"
    assert (
        worker.deliver(subscription | {"endpoint": "https://127.0.0.1/private"}, config)
        == "rejected"
    )


def test_worker_connection_rejects_privileged_users_plaintext_or_arbitrary_hosts(monkeypatch):
    accepted = []
    monkeypatch.setattr(worker.psycopg, "connect", lambda **kw: accepted.append(kw))
    valid = "postgresql://we2day_reminder_worker.abcdefghijklmnopqrst:synthetic-password@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"
    worker.connect(worker.WorkerSettings(reminder_database_url=valid))
    assert accepted[0]["sslmode"] == "verify-full" and accepted[0]["prepare_threshold"] is None
    for invalid in [
        valid.replace("we2day_reminder_worker", "postgres"),
        valid.replace("pooler.supabase.com", "example.com"),
        valid + "?sslmode=disable",
    ]:
        try:
            worker.connect(worker.WorkerSettings(reminder_database_url=invalid))
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe connection accepted")
    assert len(accepted) == 1


def test_worker_cli_errors_never_print_driver_credentials(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["reminder-worker", "--check"])
    raw, _ = keys()
    monkeypatch.setenv("WE2DAY_PUSH_ENABLED", "true")
    monkeypatch.setenv("WE2DAY_PUSH_PRIVATE_KEY", raw)
    monkeypatch.setenv("WE2DAY_PUSH_SUBJECT", "https://example.com")

    def fail(_):
        raise worker.psycopg.OperationalError("secret-password@example.com")

    monkeypatch.setattr(worker, "connect", fail)
    assert worker.main() == 1
    output = capsys.readouterr().out
    assert "secret" not in output and raw not in output and "FAIL:" in output
    assert "reminder_worker_connection" in output
