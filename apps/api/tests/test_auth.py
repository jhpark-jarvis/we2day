import httpx
import pytest
from fastapi.testclient import TestClient

from we2day_api import auth
from we2day_api.config import Settings
from we2day_api.main import create_app

USER_ID = "11111111-1111-4111-8111-111111111111"
CONFIG = Settings(
    _env_file=None,
    supabase_url="https://synthetic.supabase.co",
    supabase_publishable_key="synthetic-publishable-key",
)


def install_auth_transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}),
    )


@pytest.mark.parametrize("authorization", [None, "Basic invalid", "Bearer"])
def test_missing_bearer_is_denied(authorization):
    with TestClient(create_app(CONFIG)) as client:
        response = client.get(
            "/auth/me", headers={"Authorization": authorization} if authorization else {}
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "no-store" in response.headers["cache-control"]


def test_unconfigured_auth_fails_closed():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/auth/me", headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 503


@pytest.mark.parametrize("token", ["forged-token", "expired-token", "wrong-project-token"])
def test_auth_rejection_does_not_expose_upstream_details(monkeypatch, token):
    def handler(request):
        assert request.url == "https://synthetic.supabase.co/auth/v1/user"
        assert request.headers["authorization"] == f"Bearer {token}"
        return httpx.Response(
            401, json={"msg": "sensitive upstream detail", "error_code": "bad_jwt"}
        )

    install_auth_transport(monkeypatch, handler)
    with TestClient(create_app(CONFIG)) as client:
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text
    assert "sensitive" not in response.text


@pytest.mark.parametrize("email", [None, "synthetic@example.invalid"])
def test_verified_identity_is_minimal_and_not_cached(monkeypatch, email):
    def handler(request):
        assert request.headers["authorization"] == "Bearer valid-synthetic-token"
        assert request.headers["apikey"] == "synthetic-publishable-key"
        return httpx.Response(
            200,
            json={
                "id": USER_ID,
                "aud": "authenticated",
                "email": email,
                "created_at": "2026-10-19T00:00:00Z",
                "app_metadata": {"provider": "kakao"},
                "user_metadata": {"private": "not-for-api-response"},
            },
        )

    install_auth_transport(monkeypatch, handler)
    with TestClient(create_app(CONFIG)) as client:
        response = client.get("/auth/me", headers={"Authorization": "Bearer valid-synthetic-token"})
    assert response.status_code == 200
    assert response.json() == {"id": USER_ID, "email": email}
    assert "no-store" in response.headers["cache-control"]


def test_upstream_unavailable_is_not_reported_as_bad_login(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("synthetic outage", request=request)

    install_auth_transport(monkeypatch, handler)
    with TestClient(create_app(CONFIG)) as client:
        response = client.get("/auth/me", headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 503
    assert "synthetic" not in response.text


def test_malformed_auth_response_fails_closed(monkeypatch):
    install_auth_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"id": USER_ID, "private": "upstream detail"}),
    )
    with TestClient(create_app(CONFIG)) as client:
        response = client.get("/auth/me", headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 503
    assert "upstream detail" not in response.text
