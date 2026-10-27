import pytest
from pydantic import ValidationError

from we2day_api.ai_planner import ChatInput
from we2day_api.ai_tools import PlanningContext, StoredContext


def test_owner_stored_future_fields_round_trip_but_are_not_model_conditions():
    context = StoredContext.model_validate(
        {
            "date": "2030-01-05",
            "future_control": {"opaque": "server-only-synthetic"},
        }
    )
    assert context.model_dump()["future_control"] == {"opaque": "server-only-synthetic"}
    assert "server-only-synthetic" not in context.model_dump_json(
        include=set(PlanningContext.model_fields)
    )


def test_known_conditions_remain_strict_and_client_cannot_supply_context():
    with pytest.raises(ValidationError):
        StoredContext.model_validate({"budget": "30000", "future_control": {}})
    with pytest.raises(ValidationError):
        ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": "합성"}],
                "context": {"future_control": {}},
            }
        )
