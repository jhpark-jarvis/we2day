from fastapi.testclient import TestClient

from we2day_api.config import Settings
from we2day_api.main import create_app


def test_health_does_not_require_external_credentials():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "we2day-api"}


def test_cors_accepts_only_configured_origins():
    settings = Settings(_env_file=None, cors_origins=["http://localhost:3000"])
    with TestClient(create_app(settings)) as client:
        allowed = client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/health/live",
            headers={"Origin": "https://unrelated.invalid", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_configuration_is_not_exposed_by_health_or_openapi():
    config = Settings(_env_file=None, supabase_publishable_key="synthetic-config-value")
    with TestClient(create_app(config)) as client:
        responses = [client.get("/health/live"), client.get("/openapi.json")]
    assert all("synthetic-config-value" not in response.text for response in responses)
