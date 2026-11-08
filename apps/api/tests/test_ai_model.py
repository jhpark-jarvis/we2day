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


@pytest.mark.parametrize(
    "reference", ["첫 번째 활동", "첫번째활동", "두번째 장소", "3번째 활동", "마지막 활동"]
)
def test_activity_reference_is_not_a_public_area(reference):
    from we2day_api.ai_place_policy import explicit_area

    assert explicit_area(reference + " 근처에서 갈 곳을 찾아줘") == ""


@pytest.mark.parametrize("area", ["성수동", "광교동", "신사동"])
def test_named_area_is_preserved(area):
    from we2day_api.ai_place_policy import explicit_area

    assert explicit_area(area + " 근처에서 갈 곳을 찾아줘") == area


@pytest.mark.parametrize("preserve", ["순서는 유지해줘", "순서는 그대로", "순서를 바꾸지 마"])
def test_preserved_order_does_not_turn_metadata_edits_into_swaps(preserve):
    from datetime import date

    from we2day_api.ai_control import prepare
    from we2day_api.ai_planner import ChatInput, Message
    from we2day_api.plans import PlanContent

    plan = PlanContent(
        title="합성 코스", date="2030-06-15", budget=30000, activities=[{"title": "산책"}]
    )
    text = "날짜를 2030년 6월 20일, 예산을 45000원, 이동수단을 도보로 바꿔줘. " + preserve
    decision = prepare(
        ChatInput(messages=[Message(role="user", content=text)]), {}, plan, date(2026, 11, 8)
    )
    assert decision.directive.plan is not None
    assert decision.directive.plan.date == "2030-06-20"
    assert decision.directive.plan.budget == 45000
    assert decision.directive.plan.transport == "도보"
    assert decision.directive.plan.activities == plan.activities
