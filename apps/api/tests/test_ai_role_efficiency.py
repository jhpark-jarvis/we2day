"""Wire constraints, caller isolation and role telemetry across controlled dialogues."""

import asyncio
import copy
import json
import logging
from datetime import date

import pytest
from test_ai_capabilities import Flow

from we2day_api import ai_planner
from we2day_api.ai_capabilities import definitions
from we2day_api.ai_capability_router import MODELS, selection_messages
from we2day_api.ai_metrics import aggregate
from we2day_api.ai_runtime import MODEL_ROLES, RunStats
from we2day_api.ai_wire import compact_schema
from we2day_api.plans import PlanContent


def test_wire_metadata_compaction_preserves_data_names_and_constraints():
    original = {
        "title": "Decorative",
        "required": ["title"],
        "additionalProperties": False,
        "properties": {
            "title": {"title": "Title", "type": "string", "minLength": 1, "maxLength": 50},
            "kind": {"title": "Kind", "enum": ["title", "any"], "default": "any"},
            "value": {"default": {"title": "literal"}, "examples": [{"title": "example"}]},
            "optional": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "constant": {"const": "plan", "default": "plan"},
            "empty": {"default": []},
            "zero": {"default": 0},
            "false": {"default": False},
        },
    }
    before = copy.deepcopy(original)
    wire = compact_schema(original)
    assert original == before
    assert "title" not in wire and wire["required"] == ["title"]
    assert wire["additionalProperties"] is False
    props = wire["properties"]
    assert props["title"] == {"type": "string", "minLength": 1, "maxLength": 50}
    assert props["kind"]["enum"] == ["title", "any"] and props["kind"]["default"] == "any"
    assert props["value"] == original["properties"]["value"]
    assert props["constant"] == {"const": "plan"}
    assert "default" not in props["optional"] and "default" not in props["empty"]
    assert props["zero"]["default"] == 0 and props["false"]["default"] is False
    wire["properties"]["value"]["default"]["title"] = "changed"
    assert original == before


def test_all_static_schemas_keep_validation_and_caller_filters_without_cache_mutation():
    first = definitions(MODELS)
    raw_bytes = sum(len(json.dumps(m.model_json_schema()).encode()) for m in MODELS.values())
    compact_bytes = sum(len(json.dumps(t["function"]["parameters"]).encode()) for t in first)
    assert compact_bytes < raw_bytes
    for tool in first:
        schema = tool["function"]["parameters"]
        raw = MODELS[tool["function"]["name"]].model_json_schema()
        assert schema.get("required") == raw.get("required")
        assert schema.get("additionalProperties") == raw.get("additionalProperties")
        assert set(schema.get("properties", {})) == set(raw.get("properties", {}))
        schema.clear()
    second = definitions(MODELS, {"search_places"}, selected=False)
    assert len(second) == 1 and second[0]["function"]["parameters"]["required"] == [
        "query",
        "targets",
    ]
    assert not definitions(MODELS, {"lookup_selected_places"}, selected=False)
    assert definitions(MODELS, {"lookup_selected_places"}, selected=True)
    assert all(t["function"]["parameters"] for t in definitions(MODELS))


@pytest.mark.parametrize(
    "conditions", [{}, {"date": "2030-06-20", "budget": 0}, {"date": "2030-06-21", "budget": 100}]
)
def test_selector_projection_preserves_different_unknown_and_zero_conditions(conditions):
    proposal = PlanContent.model_validate(
        {
            "title": "합성 코스",
            "date": "2030-06-20",
            "budget": 0,
            "activities": [
                {"title": "산책", "place": "합성 공원 (서울특별시 합성 주소)", "time": "14:00"}
            ],
        }
    )
    before = proposal.model_dump()
    messages = [{"role": "user", "content": f"이전 요청 {i}"} for i in range(7)]
    body = ai_planner.ChatInput.model_validate(
        {
            "messages": messages
            + [
                {"role": "assistant", "content": "PRIVATE"},
                {"role": "user", "content": "첫 활동 근처 카페"},
            ]
        }
    )
    value = json.loads(
        selection_messages(body, conditions, proposal, date(2026, 11, 8))[1]["content"]
    )
    assert value["previous_requests"] == [f"이전 요청 {i}" for i in range(2, 7)]
    current = value["current_proposal"]
    for key in ("date", "budget"):
        assert (key in current) == (before[key] != conditions.get(key))
        if key in current:
            assert current[key] == before[key]
    assert current["activities"][0] == {
        "ref": "activity_1",
        "title": "산책",
        "time": "14:00",
        "place": "합성 공원",
    }
    assert "PRIVATE" not in json.dumps(value) and proposal.model_dump() == before


@pytest.mark.parametrize("text", ["고마워", "안녕하세요", "감사합니다"])
def test_existing_safe_social_control_avoids_inference_and_preserves_proposal(monkeypatch, text):
    proposal = {
        "title": "합성",
        "date": "2030-06-20",
        "activities": [{"title": "산책", "place": "합성 공원"}],
    }
    flow = Flow(monkeypatch, proposal=proposal)
    asyncio.run(flow.send(text))
    assert not flow.models and flow.stats[-1]["model_calls"] == 0
    assert flow.store.proposal == proposal


def test_new_search_and_shared_read_still_use_selection_after_social(monkeypatch):
    flow = Flow(monkeypatch)

    async def run():
        await flow.send("고마워")
        await flow.send(
            "성수동 카페 찾아줘",
            (
                "search_places",
                {"query": "카페", "targets": ["카페"], "area": "성수동", "kind": "cafe"},
            ),
        )
        assert flow.queries and flow.stats[-1]["selection_model_calls"] == 1
        result = await flow.send("오늘 어디 가기로 했지?", ("read_shared_calendar", {}))
        assert "PRIVATE SAVED TITLE" in result.reply
        assert flow.stats[-1]["selection_model_calls"] == 1

    asyncio.run(run())


@pytest.mark.parametrize("label", ["제목", "코스 이름", "플랜 명칭"])
def test_explicit_labeled_title_updates_only_the_current_title_without_inference(
    monkeypatch, label
):
    proposal = {
        "title": "기존 코스",
        "date": "2030-06-20",
        "budget": 0,
        "activities": [{"title": "산책", "place": "합성 공원", "time": "14:00"}],
    }
    flow = Flow(monkeypatch, context={"date": proposal["date"], "budget": 0}, proposal=proposal)
    result = asyncio.run(flow.send(label + ": 합성 오후 코스"))
    assert result.plan and result.plan.title == "합성 오후 코스"
    assert not flow.models and not flow.reads and not flow.queries
    expected = PlanContent.model_validate(proposal).model_dump()
    expected["title"] = "합성 오후 코스"
    assert result.plan.model_dump() == expected


@pytest.mark.parametrize("role", sorted(MODEL_ROLES))
def test_role_metrics_include_failed_and_cancelled_attempts_but_not_missing_usage(role, caplog):
    stats = RunStats("we2-ai-2026-11-09-v20")
    with pytest.raises(asyncio.CancelledError), stats.inference(role):
        raise asyncio.CancelledError()
    with pytest.raises(RuntimeError), stats.inference(role):
        raise RuntimeError("PRIVATE")
    stats.usage({}, role=role)
    assert f"{role}_prompt_tokens" not in stats.counts
    stats.usage(
        {"usage": {"prompt_tokens": 0, "completion_tokens": 12, "total_tokens": 12}}, role=role
    )
    assert stats.counts[f"{role}_model_calls"] == 2
    assert stats.counts[f"{role}_prompt_tokens"] == 0
    assert stats.counts["completion_tokens"] == 12
    assert stats.durations[f"model_{role}"] >= 0 and stats.durations["model"] >= 0
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        stats.emit(502)
    summary = aggregate(caplog.text.splitlines())["versions"][stats.version]["roles"][role]
    assert summary["model_calls"] == 2 and summary["prompt_tokens"] == 0
    assert summary["request_latency_ms"]["observations"] == 1
    assert "PRIVATE" not in caplog.text


def test_role_metrics_reject_unknown_names_and_untrusted_values():
    stats = RunStats("we2-ai-2026-11-09-v20")
    with pytest.raises(ValueError), stats.inference("private-address"):
        pass
    with pytest.raises(ValueError):
        stats.usage({}, role="private-address")
    line = {
        "version": stats.version,
        "status": "ok",
        "ms": {"model_selection": float("nan"), "model_completion": True, "model_private": 99},
        "selection_model_calls": 1,
        "selection_prompt_tokens": -1,
        "private_model_calls": 99,
    }
    summary = aggregate(["ai_run " + json.dumps(line)])["versions"][stats.version]
    assert summary["roles"]["selection"]["prompt_tokens"] is None
    assert summary["roles"]["selection"]["request_latency_ms"]["p50"] is None
    assert "private" not in json.dumps(summary) and "completion" not in summary["roles"]
