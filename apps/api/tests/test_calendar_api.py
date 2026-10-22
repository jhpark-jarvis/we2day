import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from we2day_api import anniversaries, auth
from we2day_api.config import Settings
from we2day_api.main import create_app

USER = "11111111-1111-4111-8111-111111111111"
SPACE = "22222222-2222-4222-8222-222222222222"
CONFIG = Settings(
    _env_file=None,
    supabase_url="https://synthetic.supabase.co",
    supabase_publishable_key="synthetic-key",
)
BODY = {"title": "산책", "date": "2026-10-24", "time": "14:30", "place": "", "note": ""}
ROW = {
    **BODY,
    "id": str(uuid4()),
    "version": 1,
    "created_by": USER,
    "updated_by": USER,
    "created_at": "2026-10-19T00:00:00Z",
    "app_metadata": {},
    "user_metadata": {},
    "updated_at": "2026-10-19T00:00:00Z",
    "creation_fingerprint": "private",
    "request_id": str(uuid4()),
    "couple_id": SPACE,
}


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    replies = []
    original = httpx.Client

    def handler(request):
        assert request.headers["apikey"] == "synthetic-key"
        assert request.headers["authorization"] == "Bearer caller-token"
        if request.url.path == "/auth/v1/user":
            return httpx.Response(
                200,
                json={
                    "id": USER,
                    "aud": "authenticated",
                    "created_at": "2026-10-19T00:00:00Z",
                    "app_metadata": {},
                    "user_metadata": {},
                },
            )
        calls.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}),
    )
    with TestClient(create_app(CONFIG)) as client:
        client.headers["Authorization"] = "Bearer caller-token"
        yield client, calls, replies


def test_couple_and_invite_rpc_headers_and_bodies(upstream):
    client, calls, replies = upstream
    replies.extend(
        [
            (200, None),
            (200, {"id": SPACE, "member_count": 1}),
            (200, {"token": "a" * 64, "expires_at": "2026-10-20T00:00:00Z"}),
            (200, {"id": SPACE, "member_count": 2}),
        ]
    )
    assert client.get("/couple").json() is None
    assert client.post("/couple").status_code == 201
    assert client.post("/couple/invites").status_code == 201
    result = client.post("/couple/accept", json={"token": "a" * 64})
    assert result.json()["member_count"] == 2
    assert "no-store" in result.headers["cache-control"]
    assert calls[-1].url.path == "/rest/v1/rpc/accept_couple_invite"
    assert json.loads(calls[-1].content) == {"p_token": "a" * 64}


def test_month_filter_and_minimal_response(upstream):
    client, calls, replies = upstream
    replies.append((200, [ROW]))
    result = client.get("/appointments?month=2028-02")
    assert result.status_code == 200
    assert "creation_fingerprint" not in result.text
    assert "couple_id" not in result.text
    assert calls[0].url.params["and"] == "(date.gte.2028-02-01,date.lte.2028-02-29)"
    assert "couple_id" not in calls[0].url.params


def test_create_and_edit_version_contract(upstream):
    client, calls, replies = upstream
    replies.extend([(200, [ROW]), (200, [{**ROW, "version": 2}])])
    request_id = str(uuid4())
    result = client.post("/appointments", json={**BODY, "request_id": request_id})
    assert result.status_code == 201
    assert json.loads(calls[-1].content)["p_request_id"] == request_id
    result = client.patch(f"/appointments/{ROW['id']}", json={**BODY, "expected_version": 1})
    assert result.json()["version"] == 2
    assert json.loads(calls[-1].content)["p_expected_version"] == 1


def test_anniversary_endpoints_and_minimal_fields(upstream, monkeypatch):
    from datetime import date

    monkeypatch.setattr(anniversaries, "seoul_today", lambda: date(2029, 2, 28))
    client, calls, replies = upstream
    body = {
        "kind": "birthday",
        "title": "생일",
        "month": 2,
        "day": 29,
        "date": None,
        "annual": True,
    }
    row = {**ROW, **body}
    replies.extend([(200, [row]), (200, [row]), (200, [{**row, "version": 2}])])
    listed = client.get("/anniversaries")
    assert listed.json()["items"][0]["next_date"] == "2029-02-28"
    assert "couple_id" not in listed.text and "creation_fingerprint" not in listed.text
    assert calls[-1].url.params["order"] == "id.asc"
    assert (
        client.post("/anniversaries", json={**body, "request_id": str(uuid4())}).status_code == 201
    )
    changed = client.patch(f"/anniversaries/{ROW['id']}", json={**body, "expected_version": 1})
    assert changed.json()["version"] == 2
    assert json.loads(calls[-1].content)["p_date"] is None


def test_anniversary_read_paginates(upstream):
    client, calls, replies = upstream
    row = {**ROW, "kind": "custom", "month": None, "day": None, "annual": False}
    replies.extend([(200, [row] * 100), (200, [row])])
    result = client.get("/anniversaries")
    assert len(result.json()["items"]) == 101
    assert calls[-1].url.params["offset"] == "100"


@pytest.mark.parametrize(
    "code,message,status",
    [
        ("PT409", "version_conflict", 409),
        ("PT400", "invalid_invite", 400),
        ("PT404", "appointment_not_found", 404),
        ("PGRST202", "sensitive SQL", 503),
        ("42501", "sensitive credentials", 503),
        ("PT409", "private surprise", 503),
    ],
)
def test_safe_upstream_error_mapping(upstream, caplog, code, message, status):
    client, _, replies = upstream
    replies.append((400, {"code": code, "message": message, "details": "secret"}))
    result = client.post("/couple")
    assert result.status_code == status
    assert "secret" not in result.text and "sensitive" not in result.text
    assert "no-store" in result.headers["cache-control"]
    assert "secret" not in caplog.text and message not in caplog.text


def test_database_diagnostics_exclude_upstream_details(upstream, caplog):
    client, _, replies = upstream
    replies.append((404, {"code": "PGRST205", "message": "private table", "details": "secret"}))
    assert client.get("/anniversaries").status_code == 503
    assert "category=schema_not_ready" in caplog.text
    assert "private table" not in caplog.text and "secret" not in caplog.text


@pytest.mark.parametrize(
    "change",
    [
        {"title": "  "},
        {"date": "2026-02-30"},
        {"date": "1999-12-31"},
        {"time": "14:30Z"},
        {"time": "14:30:01"},
        {"title": "a" * 101},
        {"couple_id": SPACE},
        {"place": "a" * 201},
    ],
)
def test_invalid_input_never_reaches_data_api(upstream, change):
    client, calls, _ = upstream
    result = client.post("/appointments", json={**BODY, "request_id": str(uuid4()), **change})
    assert result.status_code == 422 and calls == []
    assert '"input"' not in result.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/couple"),
        ("post", "/couple"),
        ("post", "/couple/invites"),
        ("post", "/couple/accept"),
        ("get", "/appointments?month=2026-10"),
        ("post", "/appointments"),
        ("patch", f"/appointments/{ROW['id']}"),
    ],
)
def test_all_business_endpoints_require_auth(method, path):
    with TestClient(create_app(CONFIG)) as client:
        result = getattr(client, method)(path)
    assert result.status_code == 401
