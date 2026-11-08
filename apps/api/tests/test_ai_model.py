import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from we2day_api.ai_model import MODEL_ID, model_parameters
from we2day_api.config import Settings
from we2day_api.data import require_data
from we2day_api.main import create_app


def test_server_profile_is_fixed_and_request_local():
    settings = Settings(_env_file=None)
    first = model_parameters(settings)
    first["model"] = "untrusted-model"
    assert model_parameters(settings) == {"model": MODEL_ID, "reasoning_effort": "low"}
    assert MODEL_ID == "@cf/openai/gpt-oss-120b"


def test_disabled_profile_cannot_issue_inference():
    with pytest.raises(HTTPException) as error:
        model_parameters(Settings(_env_file=None, ai_planner_enabled=False))
    assert error.value.status_code == 503


def test_disabled_planner_retains_history_and_denies_new_turns():
    settings = Settings(
        _env_file=None,
        ai_planner_enabled=False,
        cloudflare_account_id="a" * 32,
        cloudflare_api_token="synthetic-token",
    )
    app = create_app(settings)

    class Store:
        def rpc(self, name, values=None):
            assert name in {"get_my_couple", "read_ai_conversations"}
            return True if name == "get_my_couple" else []

    app.dependency_overrides[require_data] = Store
    with TestClient(app) as client:
        assert client.get("/ai/planner").json() == {"available": False}
        for headers in [{}, {"Accept": "text/event-stream"}]:
            response = client.post(
                "/ai/planner",
                json={"messages": [{"role": "user", "content": "코스 제안"}]},
                headers=headers,
            )
            assert response.status_code == 503
            assert response.json()["detail"] == "ai_unavailable"
        assert client.get("/ai/planner/history").status_code == 200


def test_caller_cannot_choose_another_model_or_reasoning():
    app = create_app(Settings(_env_file=None, ai_planner_enabled=False))
    app.dependency_overrides[require_data] = lambda: object()
    with TestClient(app) as client:
        response = client.post(
            "/ai/planner",
            json={
                "messages": [{"role": "user", "content": "코스 제안"}],
                "model": "untrusted-model",
                "reasoning_effort": "high",
            },
        )
    assert response.status_code == 422
