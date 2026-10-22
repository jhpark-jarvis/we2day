import httpx
from fastapi.testclient import TestClient

from we2day_api.config import Settings
from we2day_api.main import create_app


def test_retired_place_search_never_calls_provider_or_reads_credentials(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected provider request")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    config = Settings(
        _env_file=None,
        naver_search_enabled=True,
        naver_search_client_id="retired-fixture-id",
        naver_search_client_secret="retired-fixture-secret",
    )
    assert not any(name.startswith("naver_search_") for name in Settings.model_fields)
    with TestClient(create_app(config)) as client:
        for body in [{"query": "가상 장소"}, {"query": "x" * 5000}, None]:
            result = client.post("/places/search", json=body)
            assert result.status_code == 410
            assert result.json() == {"detail": "place_search_moved_to_naver_maps"}
            assert "no-store" in result.headers["cache-control"]
            assert "retired-fixture" not in result.text
