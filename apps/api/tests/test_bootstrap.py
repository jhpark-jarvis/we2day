from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from we2day_api import auth
from we2day_api.config import Settings
from we2day_api.main import create_app

FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-10-25T00:00:00Z"


@pytest.fixture
def bundle(monkeypatch):
    calls, state = [], {"fail": "", "linked": True}
    original = httpx.Client

    def handler(request):
        token = request.headers["authorization"].removeprefix("Bearer ")
        assert request.headers["apikey"] == "synthetic-key"
        calls.append((token, request.url.path))
        if token == "revoked":
            return httpx.Response(401, json={"msg": "revoked", "error_code": "bad_jwt"})
        user = FIRST if token == "first" else SECOND
        path = request.url.path
        if path == "/auth/v1/user":
            body = {
                "id": user,
                "aud": "authenticated",
                "created_at": STAMP,
                "app_metadata": {},
                "user_metadata": {},
            }
        elif path.endswith(state["fail"]) and state["fail"]:
            return httpx.Response(503, json={"message": "must not reflect private SQL"})
        elif path.endswith("get_my_couple"):
            body = {"id": user, "member_count": 1} if state["linked"] else None
        elif path.endswith("user_profiles"):
            body = [
                {"user_id": user, "display_name": "테스트 이름", "version": 1, "updated_at": STAMP}
            ]
        else:
            body = []
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kw: original(**{**kw, "transport": httpx.MockTransport(handler)}),
    )
    settings = Settings(
        _env_file=None,
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="synthetic-key",
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = "Bearer first"
        yield client, calls, state


def test_home_bundle_single_auth_and_independent_failure(bundle):
    client, calls, state = bundle
    state["fail"] = "timezone_preferences"
    result = client.get("/bootstrap/home?month=2026-10")
    assert result.status_code == 200
    body = result.json()
    assert body["couple"]["data"]["id"] == FIRST
    assert body["appointments"] == {"data": [], "status": 200, "detail": ""}
    assert body["zones"]["status"] == 503
    assert body["profiles"]["data"]["mine"]["user_id"] == FIRST
    assert "private SQL" not in result.text
    assert Counter(path for _, path in calls)["/auth/v1/user"] == 1
    assert len(calls) == 6  # One Auth, couple + four data reads.
    assert "auth;dur=" in result.headers["server-timing"]
    assert "data;dur=" in result.headers["server-timing"]
    assert "no-store" in result.headers["cache-control"]


def test_context_revalidates_each_caller_and_profile_failure_keeps_user(bundle):
    client, calls, state = bundle
    for token, expected in [("first", FIRST), ("second", SECOND)]:
        response = client.get("/bootstrap/context", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["user_id"] == expected
        assert response.json()["profiles"]["data"]["mine"]["user_id"] == expected
    state["fail"] = "user_profiles"
    account = client.get("/bootstrap/account").json()
    assert account["user_id"] == FIRST and account["profiles"]["status"] == 503
    assert sum(path == "/auth/v1/user" for _, path in calls) == 3
    before = len(calls)
    assert (
        client.get("/bootstrap/context", headers={"Authorization": "Bearer revoked"}).status_code
        == 401
    )
    assert len(calls) == before + 1  # No data request after failed authentication.


def test_unlinked_home_skips_data_and_invalid_month_is_rejected(bundle):
    client, calls, state = bundle
    state["linked"] = False
    result = client.get("/bootstrap/home?month=2026-10")
    assert result.status_code == 200 and result.json()["couple"]["data"] is None
    assert result.json()["appointments"]["data"] is None
    assert len(calls) == 2
    assert client.get("/bootstrap/home?month=2026-13").status_code == 422
