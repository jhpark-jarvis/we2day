"""Effect invariants of the new engine, separate from real-language evaluations."""

import asyncio
import copy
import json
from datetime import date
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from test_ai_capabilities import Flow

from we2day_api import ai_control, ai_dialogue, ai_location, ai_planner
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_turn_contract import DateSpec, TurnPlan
from we2day_api.ai_turn_engine import bind_continuation, edit_proposal, project, validate_effects
from we2day_api.ai_wire import inline_schema
from we2day_api.config import Settings
from we2day_api.plans import PlanContent

TODAY = date(2026, 11, 10)
BASE = {
    "date": "2026-11-14",
    "region": "성수동",
    "budget": 50000,
    "transport": "자동차",
    "activities": ["카페"],
    "requirements": "조용한 곳",
}
PROPOSAL = {
    "title": "가을",
    "date": "2026-11-14",
    "budget": 50000,
    "transport": "자동차",
    "activities": [
        {"title": "산책", "place": "서울숲", "time": "14:00"},
        {"title": "차", "place": "성수 카페", "time": "16:00"},
    ],
    "preparation": ["우산"],
}


def response_output(response):
    """Adapt synthetic legacy fixtures; wire contract has its own strict tests."""
    if response.status_code != 200 or "choices" not in response.json():
        return response
    choice = response.json()["choices"][0]
    message = choice["message"]
    return httpx.Response(
        200,
        json={
            "status": "incomplete" if choice.get("finish_reason") == "length" else "completed",
            "output": [
                {"type": "reasoning", "content": [{"text": "PRIVATE_REASONING"}]},
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": message.get("content", "")}],
                },
            ],
        },
    )


def sent_schema(data):
    native = data["text"]["format"].get("schema")
    if native:
        return native
    messages = data.get("input", data.get("messages"))
    text = messages[0]["content"].split("JSON only):\n", 1)[1]
    return json.JSONDecoder().raw_decode(text)[0]


def test_responses_wire_separates_reasoning_and_preserves_inference_contract():
    from we2day_api.ai_wire import inference_usage, responses_inputs, responses_result

    original = {
        "model": "@cf/openai/gpt-oss-120b",
        "reasoning_effort": "low",
        "messages": [{"role": "user", "content": "장소 검색"}],
        "max_tokens": 768,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "route", "strict": True, "schema": {"type": "object"}},
        },
    }
    frozen = copy.deepcopy(original)
    request = responses_inputs(original)
    assert original == frozen
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 768
    assert request["store"] is False and request["stream"] is False
    assert request["input"][-1] == original["messages"][-1]
    assert request["input"][0]["role"] == "system"
    assert '"type":"object"' in request["input"][0]["content"]
    assert request["text"]["format"]["schema"] == {"type": "object"}
    response = response_output(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":"성수동"}'}, "finish_reason": "stop"}]
            },
        )
    ).json()
    response["usage"] = {"input_tokens": 12, "output_tokens": 34}
    result = responses_result(response)
    assert result["choices"][0]["message"]["content"] == '{"value":"성수동"}'
    assert "PRIVATE_REASONING" not in json.dumps(result)
    assert inference_usage(response)["usage"] == {"prompt_tokens": 12, "completion_tokens": 34}
    response.pop("usage")
    assert "PRIVATE_REASONING" not in json.dumps(responses_result(response))


@pytest.mark.parametrize(
    "invalid",
    [
        {"status": "incomplete", "output": []},
        {"status": "completed", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "completed", "output": None},
        {"status": "completed", "output": [None]},
        {"status": "completed", "output": [{"type": "reasoning"}]},
        {"status": "completed", "output": [{"type": "function_call", "name": "delete"}]},
        {"status": "completed", "output": [{"type": "message", "role": "user"}]},
    ],
)
def test_responses_wire_rejects_incomplete_reasoning_or_action_outputs(invalid):
    from we2day_api.ai_wire import responses_result

    with pytest.raises(ValueError):
        responses_result(invalid)


@pytest.mark.parametrize("change", ["refusal", "duplicate", "message_incomplete", "empty"])
def test_responses_wire_rejects_ambiguous_or_refused_final_messages(change):
    from we2day_api.ai_wire import responses_result

    data = response_output(
        httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        )
    ).json()
    message = data["output"][-1]
    if change == "refusal":
        message["content"] = [{"type": "refusal", "refusal": "unavailable"}]
    elif change == "duplicate":
        data["output"].append(copy.deepcopy(message))
    elif change == "message_incomplete":
        message["status"] = "in_progress"
    else:
        message["content"][0]["text"] = " "
    with pytest.raises(ValueError):
        responses_result(data)


def test_grounded_completion_uses_the_same_responses_protocol_and_reference_contract():
    from types import SimpleNamespace

    from test_ai_tools import session

    current = session()
    current.direct_final = current.require_plan = current.responses_api = True
    current.plan_date = "2030-01-01"
    candidate = current.add("합성 전시장", "서울특별시 합성로 1", "naver")
    current.fresh_refs.add(candidate.ref)
    stats = RunStats("test")

    def provider(request):
        data = json.loads(request.content)
        assert request.url.path.endswith("/responses")
        assert data["store"] is False and data["stream"] is False and "tools" not in data
        assert data["text"]["format"] == {"type": "text"}
        assert candidate.ref in json.dumps(sent_schema(data))
        response = response_output(
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reply": "코스 초안",
                                        "plan": {
                                            "title": "전시",
                                            "date": "2030-01-01",
                                            "activities": [
                                                {"title": "전시", "place_ref": candidate.ref}
                                            ],
                                        },
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        ).json()
        response["usage"] = {"input_tokens": 100, "output_tokens": 80}
        return httpx.Response(200, json=response)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await ai_planner.complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "코스로 정리"}],
                current,
                client=client,
                budget=Budget(),
                stats=stats,
            )

    result = asyncio.run(run())
    assert result.plan and result.plan.activities[0].place == candidate.destination
    assert "PRIVATE_REASONING" not in json.dumps(result.model_dump())
    assert stats.counts["completion_tokens"] == 80 and stats.counts["model_calls"] == 1


def test_edit_metadata_cannot_be_written_as_activity_goals_and_repair_is_atomic(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    wrong = decision(
        operation="edit",
        delta={
            "evidence": "두 번째 활동 시간만 18:00으로 바꿔줘",
            "activities": ["activity_2", "time", "absolute", "18:00"],
        },
    )
    correct = decision(
        operation="edit",
        activity_edits=[{"ref": "activity_2", "operation": "update", "time": "18:00"}],
    )
    result = asyncio.run(
        flow.turn(
            "두 번째 활동 시간만 18:00으로 바꿔줘",
            wrong,
            responses=[native(("plan_turn", wrong)), native(("plan_turn", correct))],
        )
    )
    expected = copy.deepcopy(PROPOSAL)
    expected["activities"][1]["time"] = "18:00"
    assert result.plan == PlanContent.model_validate(expected)
    assert result.context.activities == BASE["activities"]
    assert flow.stats[-1]["selection_repair_attempts"] == 1
    assert not flow.queries


def test_new_calendar_value_is_a_candidate_for_fixed_plan_not_an_implicit_effect():
    from we2day_api.ai_turn_selector import messages

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="2026년 11월 28일 전시 코스를 만들어줘")]
    )
    projection = messages(body, BASE, None, TODAY, kind="plan")
    value = json.loads(projection[1]["content"].split("\n", 1)[1])
    assert value["latest_calendar_candidate"] == "2026-11-28"
    assert value["conditions"]["date"] == BASE["date"]
    assert BASE["date"] == "2026-11-14"


def test_provider_and_prompt_share_one_field_contract_without_weakening_validation():
    from we2day_api.ai_turn_selector import format_json
    from we2day_api.ai_wire import presentation_schema, responses_inputs

    fmt = json.loads(format_json(False, "edit", 2))
    schema = fmt["json_schema"]["schema"]
    original = copy.deepcopy(schema)
    result = responses_inputs(
        {
            "model": "@cf/openai/gpt-oss-120b",
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": "Fixed operation edit"},
                {"role": "user", "content": "두 번째 활동 시간 수정"},
            ],
            "max_tokens": 1600,
            "response_format": fmt,
        }
    )
    guidance = json.loads(result["input"][0]["content"].split("JSON only):\n", 1)[1])
    assert guidance == presentation_schema(schema)
    assert result["text"]["format"]["schema"] == original == schema
    assert "activity_edits" in guidance["$defs"]["EditTurn"]["required"]
    assert (
        "delta.activities"
        in guidance["$defs"]["EditTurn"]["properties"]["activity_edits"]["description"]
    )
    assert guidance["$defs"]["ActivityPatch"]["properties"]["ref"]["enum"] == [
        "activity_1",
        "activity_2",
    ]


@pytest.mark.parametrize("mutation", ["date", "count", "reference", "null_plan", "unknown_field"])
def test_full_server_schema_enforces_dynamic_final_constraints(mutation):
    from we2day_api.ai_tools import ModelAnswer
    from we2day_api.ai_wire import validate_json_schema

    schema = ai_planner.answer_format("2030-01-01", 2, allowed_refs=["p1", "p2"])["json_schema"][
        "schema"
    ]
    value = ModelAnswer.model_validate(
        {
            "reply": "초안",
            "plan": {
                "title": "코스",
                "date": "2030-01-01",
                "activities": [
                    {"title": "첫 활동", "place_ref": "p1"},
                    {"title": "다음 활동", "place_ref": "p2"},
                ],
            },
        }
    ).model_dump()
    validate_json_schema(value, schema)
    if mutation == "date":
        value["plan"]["date"] = "2030-01-02"
    elif mutation == "count":
        value["plan"]["activities"].pop()
    elif mutation == "reference":
        value["plan"]["activities"][0]["place_ref"] = "unobserved"
    elif mutation == "null_plan":
        value["plan"] = None
    else:
        value["unrequested"] = "effect"
    with pytest.raises(ValueError):
        validate_json_schema(value, schema)


def test_server_schema_never_fetches_external_references():
    from we2day_api.ai_wire import validate_json_schema

    with pytest.raises(ValueError, match="External schema"):
        validate_json_schema({}, {"$ref": "https://invalid.test/schema"})


def test_two_activity_course_runs_full_validation_then_preserves_other_fields_on_edit(monkeypatch):
    from we2day_api.places import SearchResults

    flow = EngineFlow(monkeypatch, {**BASE, "budget": None, "requirements": ""})

    class IO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            flow.queries.append(action)
            return SearchResults(
                items=[
                    {
                        "title": "검증 전시관",
                        "category": "문화시설>미술관",
                        "roadAddress": "대전광역시 중구 검증로 1",
                    },
                    {
                        "title": "검증 저녁식사",
                        "category": "음식점>한식",
                        "roadAddress": "대전광역시 중구 검증로 2",
                    },
                ]
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    text = "2026년 11월 28일 대전광역시에서 전시와 저녁식사 코스를 만들어줘"
    choice = decision(
        operation="plan",
        delta={
            "evidence": text,
            "date": {"mode": "absolute", "source": "2026년 11월 28일"},
            "region": "대전광역시",
        },
        searches=[
            {"target": "전시", "kind": "museum", "area": "대전광역시"},
            {"target": "저녁식사", "kind": "restaurant", "area": "대전광역시"},
        ],
    )
    final = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "reply": "코스 초안",
                                "plan": {
                                    "title": "전시와 식사",
                                    "date": "2026-11-28",
                                    "activities": [
                                        {"title": "전시", "place_ref": "p1"},
                                        {"title": "저녁식사", "place_ref": "p2"},
                                    ],
                                },
                            }
                        )
                    }
                }
            ]
        },
    )
    created = asyncio.run(flow.turn(text, choice, responses=[native(("plan_turn", choice)), final]))
    assert created.plan and created.plan.date == "2026-11-28"
    assert created.context.activities == ["전시", "저녁식사"]
    assert flow.stats[-1]["model_calls"] == 3 and len(flow.queries) == 2
    before = created.plan.model_dump()
    edited = asyncio.run(
        flow.turn(
            "두 번째 활동 시간만 18:00으로 바꿔줘",
            decision(
                operation="edit",
                activity_edits=[{"ref": "activity_2", "operation": "update", "time": "18:00"}],
            ),
        )
    )
    before["activities"][1]["time"] = "18:00"
    assert edited.plan.model_dump() == before
    assert edited.context.activities == created.context.activities


def native(*calls):
    """Synthetic structured decision; real model quality is evaluated separately."""
    assert len(calls) == 1 and calls[0][0] == "plan_turn"
    payload = dict(calls[0][1])
    operation = payload.pop("operation", "answer")
    payload.pop("act", None)
    answer = payload.pop("answer", "conversation")
    if operation == "answer":
        kind = (
            "read"
            if any(payload.get(k) for k in ("reads", "weather", "selected", "inspect"))
            else ("chat" if answer == "conversation" else answer)
        )
        payload.pop("pending", None)
        if kind != "chat":
            payload.pop("reply", None)
    else:
        kind = operation
        if kind not in {"search", "plan", "edit"}:
            payload.pop("pending", None)
    if kind not in {"chat", "read", "date", "status", "help"}:
        payload.pop("reply", None)
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": json.dumps({"decision": {"kind": kind, **payload}})},
                    "finish_reason": "stop",
                }
            ]
        },
    )


class EngineFlow(Flow):
    async def turn(self, text, decision, *, responses=None, selected=None, **extra):
        self.history.append({"role": "user", "content": text})
        self.replies = list(responses or [native(("plan_turn", decision))])

        def legacy_provider(request):
            data = json.loads(request.content)
            assert request.url.path.endswith("/responses")
            assert data["store"] is False and data["stream"] is False
            data["messages"] = data.pop("input")
            data["response_format"] = {
                "type": "json_schema",
                "json_schema": sent_schema(data),
            }
            self.models.append(data)
            assert "PRIVATE" not in json.dumps(data)
            assert self.replies, "Unexpected extra inference"
            route_properties = (
                data.get("response_format", {}).get("json_schema", {}).get("properties", {})
            )
            if set(route_properties) == {"kind", "continuation", "value"}:
                response = self.replies[0]
                if response.status_code != 200:
                    return self.replies.pop(0)
                try:
                    kind = json.loads(response.json()["choices"][0]["message"]["content"])[
                        "decision"
                    ]["kind"]
                except (ValueError, KeyError, TypeError):
                    return self.replies.pop(0)
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"content": json.dumps({"kind": kind, "value": None})},
                                "finish_reason": "stop",
                            }
                        ]
                    },
                )
            return self.replies.pop(0)

        def provider(request):
            return response_output(legacy_provider(request))

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            stats = RunStats("test")
            result = await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": self.history[-11:],
                        "conversation_id": self.cid,
                        "request_id": str(uuid4()),
                        "version": self.store.version,
                        "selected_places": selected or [],
                        **extra,
                    }
                ),
                Settings(_env_file=None, ai_dialogue_engine_enabled=True),
                self.store,
                client,
                Budget(),
                stats,
            )
        self.stats.append(stats.counts)
        self.history.append({"role": "assistant", "content": result.reply})
        return result


def decision(**kwargs):
    return {"act": "information", "operation": "answer", "answer": "status", **kwargs}


@pytest.mark.parametrize(
    "field", ["date", "region", "budget", "transport", "title", "target", "activity_time"]
)
@pytest.mark.parametrize("answer", ["date", "status", "help", "conversation"])
def test_side_answer_never_changes_conditions_proposal_or_pending(monkeypatch, field, answer):
    context = {
        **BASE,
        "dialogue": {"turn_version": 0, "pending": {"field": field, "resume": "edit"}},
        "activity_edit": None,
        "turn_engine": {
            "version": 1,
            "pending": {"field": field, "resume": "edit", "searches": []},
        },
    }
    flow = EngineFlow(monkeypatch, context, PROPOSAL)
    payload = decision(answer=answer, reply="괜찮아요.")
    if answer == "date":
        payload["query_date"] = {"mode": "weekday", "weekday": 5}
    result = asyncio.run(flow.turn("이번주 토요일이 언제지", payload))
    actual = result.context.model_dump()
    assert {k: actual[k] for k in BASE} == BASE
    assert result.plan is None and not flow.queries
    assert actual["dialogue"]["pending"]["field"] == field
    assert actual["dialogue"]["turn_version"] == 1
    assert actual["turn_engine"]["pending"] == context["turn_engine"]["pending"]


@pytest.mark.parametrize(
    "field,value",
    [("region", "질문"), ("budget", 0), ("activities", ["산책"]), ("transport", "도보")],
)
def test_information_cannot_smuggle_effects(field, value):
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(decision(delta={field: value, "evidence": "질문"}))


def test_new_engine_never_calls_legacy_interpreters(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Legacy language path invoked")

    for module, name in [
        (ai_planner, "prepare"),
        (ai_planner, "direct_request"),
        (ai_planner, "interpret"),
        (ai_control, "apply_action"),
        (ai_dialogue, "analyze"),
        (ai_location, "resume_location"),
    ]:
        monkeypatch.setattr(module, name, forbidden)
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    asyncio.run(flow.turn("뭘 정했지", decision()))
    result = asyncio.run(
        flow.turn(
            "예산 0원으로 바꿔",
            decision(act="request", operation="edit", delta={"budget": 0, "evidence": "예산 0원"}),
        )
    )
    assert result.plan.budget == 0
    assert result.plan.activities == PlanContent.model_validate(PROPOSAL).activities
    assert result.context.region == "성수동"


@pytest.mark.parametrize("status", [429, 500])
def test_transport_failure_does_not_persist_or_fallback(monkeypatch, status):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    with pytest.raises(HTTPException):
        asyncio.run(flow.turn("바꿔줘", {}, responses=[httpx.Response(status)]))
    assert flow.store.version == 0
    assert not flow.queries


def test_invalid_route_cannot_carry_condition_changes_or_reach_tools(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    invalid = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "kind": "status",
                                "value": None,
                                "delta": {"region": "이번주 토요일이 언제지"},
                            }
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    )
    with pytest.raises(HTTPException):
        asyncio.run(flow.turn("이번주 토요일이 언제지", {}, responses=[invalid, invalid]))
    assert flow.store.version == 0 and not flow.queries
    assert len(flow.models) == 2


def test_region_clarification_side_question_then_answer_search(monkeypatch):
    flow = EngineFlow(monkeypatch, {**BASE, "region": ""}, PROPOSAL)
    tasks = [{"target": "카페", "kind": "cafe"}]
    first = asyncio.run(
        flow.turn(
            "근처 카페 찾아줘",
            decision(
                act="request", operation="clarify", ask="region", resume="search", searches=tasks
            ),
        )
    )
    assert first.context.location_request["basis"] == 1
    asyncio.run(flow.turn("뭘 할 수 있어", decision(answer="help")))
    result = asyncio.run(
        flow.turn(
            "성수동",
            decision(
                act="slot_answer",
                operation="resume",
                pending="resolve",
                delta={"region": "성수동", "evidence": "성수동"},
            ),
        )
    )
    assert len(result.candidates) == 1 and not result.plan
    assert result.context.dialogue.pending is None
    assert result.context.location_request is None
    assert result.context.date == BASE["date"]


def test_private_read_never_enters_next_model_context(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    read = asyncio.run(
        flow.turn(
            "오늘 일정 보여줘",
            decision(reads=[{"name": "read_shared_calendar", "date": {"mode": "offset"}}]),
        )
    )
    assert "PRIVATE SAVED TITLE" in read.reply
    asyncio.run(flow.turn("도와줘", decision(answer="help")))
    assert all("PRIVATE" not in json.dumps(m) for m in flow.models)


def test_search_candidates_cannot_change_existing_proposal(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "성수동 카페 찾아줘",
            decision(
                act="request",
                operation="search",
                searches=[{"target": "카페", "kind": "cafe", "area": "성수동"}],
            ),
        )
    )
    assert result.plan is None
    assert len(result.candidates) == 1
    assert {k: result.context.model_dump()[k] for k in BASE} == BASE


@pytest.mark.parametrize("days", [-7, 0, 1, 3, 25])
def test_relative_dates_are_server_computed(days):
    from datetime import timedelta

    assert (
        DateSpec(mode="offset", days=days).resolve(TODAY)
        == (TODAY + timedelta(days=days)).isoformat()
    )


def test_date_question_does_not_set_date_but_date_edit_does(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    first = asyncio.run(
        flow.turn(
            "다음주 토요일이 언제야",
            decision(answer="date", query_date={"mode": "weekday", "weekday": 5, "weeks": 1}),
        )
    )
    # Test clock is fixed by Flow to November 6; next calendar week's Saturday.
    assert "2026-11-14" in first.reply and first.context.date == BASE["date"]
    second = asyncio.run(
        flow.turn(
            "내일로 바꿔",
            decision(
                act="request",
                operation="edit",
                delta={"date": {"mode": "offset", "days": 1}, "evidence": "내일"},
            ),
        )
    )
    assert second.plan.date == "2026-11-07"


def test_multiple_edits_reference_original_indices_and_preserve_other_fields():
    before = PlanContent.model_validate(PROPOSAL)
    plan = TurnPlan.model_validate(
        decision(
            act="request",
            operation="edit",
            activity_edits=[
                {"ref": "activity_1", "operation": "move", "to_index": 1},
                {"ref": "activity_2", "time": "17:00"},
            ],
        )
    )
    changed = edit_proposal(before, plan, {})
    assert changed.activities[0].time == "17:00"
    assert changed.activities[1] == before.activities[0]
    assert before.model_dump() == PlanContent.model_validate(PROPOSAL).model_dump()


def test_cancellation_preserves_conditions_and_proposal(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(flow.turn("취소", decision(act="request", operation="cancel")))
    assert result.plan is None
    assert {k: result.context.model_dump()[k] for k in BASE} == BASE
    assert result.context.control["last_action"] is None


@pytest.mark.parametrize("field", list(BASE))
def test_explicit_clear_is_separate_from_omission(field):
    before = {**BASE, "dialogue": {"turn_version": 0}}
    snapshot = copy.deepcopy(before)
    plan = TurnPlan.model_validate(
        decision(act="request", operation="edit", delta={"clear": [field]})
    )
    actual = project(before, plan, plan.delta.values(TODAY), 0).model_dump()
    assert before == snapshot
    assert all(actual[k] == BASE[k] for k in BASE if k != field)
    assert actual[field] != BASE[field]


def test_ungrounded_region_rejected_before_any_effect():
    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="바꿔줘")])
    plan = TurnPlan.model_validate(
        decision(act="request", operation="edit", delta={"region": "부산", "evidence": "바꿔줘"})
    )
    with pytest.raises(ValueError):
        validate_effects(plan, body, BASE, PlanContent.model_validate(PROPOSAL), TODAY)


def test_native_schema_has_no_unresolved_nested_definitions():
    schema = inline_schema(TurnPlan.model_json_schema())
    encoded = json.dumps(schema)
    assert '"$ref"' not in encoded and '"$defs"' not in encoded
    date = schema["properties"]["query_date"]["anyOf"][0]
    assert date["required"] == ["mode"]
    assert date["properties"]["weekday"]["maximum"] == 6


def test_schema_repair_receives_field_diagnostics_without_rejected_values(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    valid = decision(
        act="request",
        operation="search",
        searches=[{"target": "카페", "kind": "cafe", "area": "성수동"}],
    )
    invalid = decision(act="request", operation="search", searches="SYNTHETIC_REJECTED_VALUE")
    result = asyncio.run(
        flow.turn(
            "성수동 카페 찾아줘",
            {},
            responses=[native(("plan_turn", invalid)), native(("plan_turn", valid))],
        )
    )
    repair = flow.models[-1]["messages"][0]["content"]
    assert "searches" in repair and "SYNTHETIC_REJECTED_VALUE" not in repair
    assert not result.plan and result.context.date == BASE["date"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("region", "성수동"),
        ("budget", 0),
        ("transport", "도보"),
        ("date", {"mode": "offset", "days": 1}),
        ("activities", ["산책"]),
    ],
)
@pytest.mark.parametrize("resume", ["search", "plan", "edit"])
def test_typed_resume_binds_original_task_without_reinterpreting_text(field, value, resume):
    pending_field = "target" if field == "activities" else field
    before = {
        "turn_engine": {
            "pending": {
                "field": pending_field,
                "resume": resume,
                "searches": [{"target": "카페", "kind": "cafe"}],
            }
        }
    }
    plan = TurnPlan.model_validate(
        {
            "act": "slot_answer",
            "operation": "resume",
            "delta": {field: value, "evidence": "합성 답변"},
        }
    )
    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="합성 답변")])
    actual = bind_continuation(plan, before, body)
    assert actual.operation == resume and actual.pending == "resolve"
    assert before["turn_engine"]["pending"]["resume"] == resume
    if resume in {"search", "plan"}:
        assert actual.searches[0].target == (value[0] if field == "activities" else "카페")


def test_read_date_resume_does_not_edit_planning_date(monkeypatch):
    context = {
        **BASE,
        "dialogue": {"turn_version": 0},
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "date",
                "resume": "answer",
                "reads": [{"name": "read_shared_calendar"}],
            },
        },
    }
    flow = EngineFlow(monkeypatch, context, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "오늘",
            {
                "act": "slot_answer",
                "operation": "resume",
                "delta": {"date": {"mode": "offset"}, "evidence": "오늘"},
            },
        )
    )
    assert result.context.date == BASE["date"] and not result.plan
    assert result.context.dialogue.pending is None
    assert flow.reads[0][1]["date"] == "eq.2026-11-06"


def test_time_window_changes_are_typed_and_do_not_edit_activity_times(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "시작 13:00 종료 19:00",
            decision(
                act="request",
                operation="edit",
                delta={
                    "start_time": "13:00",
                    "end_time": "19:00",
                    "evidence": "시작 13:00 종료 19:00",
                },
            ),
        )
    )
    assert result.context.intake.data.start_time == "13:00"
    assert result.context.intake.data.end_time == "19:00"
    assert result.plan.activities == PlanContent.model_validate(PROPOSAL).activities
    unchanged = asyncio.run(
        flow.turn("오늘 날짜가 뭐지", decision(answer="date", query_date={"mode": "offset"}))
    )
    assert unchanged.context.intake.data.end_time == "19:00"


def test_invalid_window_rejected_before_any_tools_or_mutations(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "시작 19:00 종료 13:00",
                decision(
                    act="request",
                    operation="edit",
                    delta={
                        "start_time": "19:00",
                        "end_time": "13:00",
                        "evidence": "시작 19:00 종료 13:00",
                    },
                ),
            )
        )
    assert not flow.queries and flow.store.version == 0


def test_conditions_can_be_changed_before_a_proposal_exists(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    result = asyncio.run(
        flow.turn(
            "예산은 2만원",
            decision(
                act="request", operation="edit", delta={"budget": 20000, "evidence": "예산은 2만원"}
            ),
        )
    )
    assert result.context.budget == 20000 and result.plan is None


def test_successful_generation_does_not_accept_completion_context_mutations(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)

    async def completed(settings, messages, session, **kwargs):
        assert session.direct_final and session.plan_updates["budget"] == 50000
        return ai_planner.ChatResult(
            reply="합성 초안",
            plan=PlanContent.model_validate(PROPOSAL),
            context={"region": "UNREQUESTED"},
        )

    monkeypatch.setattr(ai_planner, "complete", completed)
    result = asyncio.run(
        flow.turn(
            "이 장소를 코스에 넣어줘",
            decision(act="request", operation="plan"),
            chosen_places=[{"title": "합성 장소", "address": "성수동"}],
        )
    )
    assert result.plan and result.context.region == BASE["region"]
    assert result.context.activities == [activity.title for activity in result.plan.activities]
    followup = asyncio.run(flow.turn("현재 조건 알려줘", decision()))
    assert followup.context.activities == result.context.activities
    assert all(label in followup.reply for label in result.context.activities)


def test_selected_rows_require_explicit_selection(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    with pytest.raises(HTTPException):
        bad = decision(selected=True)
        asyncio.run(
            flow.turn(
                "집 근처", bad, responses=[native(("plan_turn", bad)), native(("plan_turn", bad))]
            )
        )
    assert not flow.reads and not flow.queries and flow.store.version == 0


def test_legacy_region_is_preserved_but_requires_confirmation_before_implicit_search(monkeypatch):
    flow = EngineFlow(monkeypatch, {**BASE, "region": "합성 미검증 값"})
    result = asyncio.run(
        flow.turn(
            "카페 찾아줘",
            decision(
                act="request", operation="search", searches=[{"target": "카페", "kind": "cafe"}]
            ),
        )
    )
    assert not flow.queries
    assert result.context.region == "합성 미검증 값"
    assert result.context.turn_engine["unverified_fields"] == ["region"]
    assert result.context.dialogue.pending.field == "region"
    confirmed = asyncio.run(
        flow.turn(
            "성수동",
            {
                "act": "slot_answer",
                "operation": "resume",
                "delta": {"region": "성수동", "evidence": "성수동"},
            },
        )
    )
    assert confirmed.context.region == "성수동"
    assert confirmed.context.turn_engine["unverified_fields"] == []
    assert confirmed.candidates


def test_new_course_without_searches_or_explicit_evidence_is_rejected(monkeypatch):
    flow = EngineFlow(monkeypatch, {**BASE, "activities": []})
    missing = decision(act="request", operation="plan")
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "코스 만들어줘",
                {},
                responses=[native(("plan_turn", missing)), native(("plan_turn", missing))],
            )
        )
    assert not flow.queries and flow.store.version == 0


def test_explicit_saved_place_answers_location_using_verified_row_not_alias(monkeypatch):
    context = {
        **BASE,
        "region": "",
        "dialogue": {"turn_version": 0},
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [{"target": "카페", "kind": "cafe"}],
            },
        },
    }
    flow = EngineFlow(monkeypatch, context)
    result = asyncio.run(
        flow.turn(
            "여기 주변에서",
            {"act": "slot_answer", "operation": "resume", "selected": True},
            selected=[{"source": "favorite", "id": flow.selected, "usage": "anchor"}],
        )
    )
    assert result.context.region == "성수동"
    assert result.context.dialogue.pending is None and result.candidates


def test_unresolved_private_alias_does_not_replace_existing_region(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "지인집으로 바꿔줘",
            decision(
                act="request",
                operation="edit",
                delta={"region": "지인집", "evidence": "지인집으로 바꿔줘"},
            ),
        )
    )
    assert result.context.region == BASE["region"]
    assert result.context.dialogue.pending.field == "region" and result.plan is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("region", "성수동"),
        ("budget", 25000),
        ("transport", "도보"),
        ("date", {"mode": "offset", "days": 1, "source": "내일"}),
    ],
)
def test_explicit_slot_answer_fulfills_original_task_without_reinterpreting_edits(field, value):
    from we2day_api.ai_turn_engine import compile_turn

    before = {
        **BASE,
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": field,
                "resume": "search",
                "searches": [{"target": "카페", "kind": "cafe"}],
            },
        },
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "내일 성수동 도보 25000"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "slot_answer",
            "operation": "resume",
            "delta": {field: value, "evidence": body.messages[-1].content},
        }
    )
    actual = compile_turn(plan, body, before, None, TODAY)
    assert actual.operation == "search" and actual.pending == "resolve"
    assert actual.searches[0].target == "카페"


def test_explicitly_suppressed_resume_changes_only_the_requested_field():
    from we2day_api.ai_turn_engine import compile_turn

    before = {
        **BASE,
        "turn_engine": {
            "version": 1,
            "pending": {"field": "budget", "resume": "search", "searches": [{"target": "카페"}]},
        },
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "검색은 말고 예산만 25000원으로"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "request",
            "operation": "edit",
            "suppress_resume": True,
            "pending": "resolve",
            "delta": {"budget": 25000, "evidence": body.messages[-1].content},
        }
    )
    actual = compile_turn(plan, body, before, None, TODAY)
    assert actual.operation == "edit" and actual.pending == "resolve" and not actual.searches


def test_date_arithmetic_uses_grounded_latest_phrase_instead_of_model_guess():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "다음주 월요일로 바꿔줘"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "request",
            "operation": "edit",
            "delta": {
                "date": {"mode": "absolute", "value": "2026-11-14", "source": "다음주 월요일"},
                "evidence": body.messages[-1].content,
            },
        }
    )
    actual = compile_turn(plan, body, BASE, None, TODAY)
    assert actual.delta.values(TODAY)["date"] == "2026-11-16"
    plan.delta.date.source = "이번주 토요일"
    with pytest.raises(ValueError, match="Date source"):
        compile_turn(plan, body, BASE, None, TODAY)


def test_activity_time_clarification_keeps_entity_and_rejects_changed_proposal():
    from we2day_api.ai_search_spec import anchor_key
    from we2day_api.ai_turn_engine import compile_turn

    proposal = PlanContent.model_validate(PROPOSAL)
    pending = {
        "field": "activity_time",
        "resume": "edit",
        "target_ref": "activity_2",
        "target_key": anchor_key(proposal.activities[1]),
    }
    before = {**BASE, "turn_engine": {"version": 1, "pending": pending}}
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "17시로"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "slot_answer",
            "operation": "resume",
            "activity_edits": [{"ref": "activity_2", "time": "17:00"}],
        }
    )
    actual = compile_turn(plan, body, before, proposal, TODAY)
    assert actual.pending == "resolve" and actual.activity_edits[0].ref == "activity_2"
    proposal.activities.reverse()
    with pytest.raises(ValueError, match="Pending activity changed"):
        compile_turn(plan, body, before, proposal, TODAY)


def test_model_projection_exposes_stable_activity_refs_not_private_read_results():
    from we2day_api.ai_turn_selector import messages

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "두번째 시간을 바꿔줘"}]}
    )
    data = json.loads(
        messages(body, BASE, PlanContent.model_validate(PROPOSAL), TODAY)[1]["content"].split(
            "\n", 1
        )[1]
    )
    assert [a["ref"] for a in data["current_proposal"]["activities"]] == [
        "activity_1",
        "activity_2",
    ]


def test_clarification_retains_verbatim_task_and_resumes_without_reusing_stale_goal(monkeypatch):
    context = {**BASE, "turn_engine": {"version": 1}}
    flow = EngineFlow(monkeypatch, context)
    asked = asyncio.run(
        flow.turn(
            "지인 집 근처 고깃집 찾아줘",
            decision(act="request", operation="clarify", ask="region", resume="search"),
        )
    )
    pending = asked.context.turn_engine["pending"]
    assert pending["original_request"] == "지인 집 근처 고깃집 찾아줘" and pending["searches"] == []
    assert not flow.queries
    answered = asyncio.run(
        flow.turn(
            "성수동이야",
            {
                "act": "slot_answer",
                "operation": "resume",
                "delta": {"region": "성수동", "evidence": "성수동이야"},
                "searches": [{"target": "고깃집", "kind": "restaurant"}],
            },
        )
    )
    assert answered.context.dialogue.pending is None
    assert flow.queries and all("카페" not in q[1] for q in flow.queries)


def test_missing_retained_task_extraction_is_rejected_before_stale_search():
    from we2day_api.ai_turn_engine import compile_turn

    before = {
        **BASE,
        "place_search": {"targets": [{"query": "카페", "kind": "cafe"}]},
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [],
                "original_request": "고깃집 찾아줘",
            },
        },
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "성수동"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "slot_answer",
            "operation": "resume",
            "delta": {"region": "성수동", "evidence": "성수동"},
        }
    )
    with pytest.raises(ValueError, match="Extract search tasks"):
        compile_turn(plan, body, before, None, TODAY)


def test_explicit_answer_supplies_pending_search_dependencies(monkeypatch):
    before = {
        **BASE,
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [],
                "original_request": "고깃집 찾아줘",
            },
        },
    }
    flow = EngineFlow(monkeypatch, before)
    result = asyncio.run(
        flow.turn(
            "성수동",
            decision(
                act="slot_answer",
                operation="resume",
                delta={"region": "성수동", "evidence": "성수동"},
                searches=[{"target": "고깃집", "kind": "restaurant"}],
            ),
        )
    )
    assert result.context.dialogue.pending is None
    assert flow.queries and all("고깃집" in q[1] for q in flow.queries)


def test_unrequested_search_cannot_hide_inside_an_edit(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    bad = decision(
        act="request",
        operation="edit",
        delta={"budget": 25000, "evidence": "25000원"},
        searches=[{"target": "카페"}],
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "25000원", bad, responses=[native(("plan_turn", bad)), native(("plan_turn", bad))]
            )
        )
    assert not flow.queries and flow.store.version == 0


def test_place_provider_failure_never_commits_other_condition_changes(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)

    class FailingIO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            raise HTTPException(503, "place_search_unavailable")

    monkeypatch.setattr(ai_planner, "ToolIO", FailingIO)
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "성수동에서 카페 찾아줘",
                decision(
                    act="request",
                    operation="search",
                    delta={"region": "성수동", "evidence": "성수동에서 카페 찾아줘"},
                    searches=[{"target": "카페", "kind": "cafe"}],
                ),
            )
        )
    assert flow.store.version == 0 and flow.store.context == BASE


def test_window_and_existing_preferences_remain_in_the_only_semantic_projection():
    from we2day_api.ai_turn_selector import messages

    context = {
        **BASE,
        "intake": {"data": {"start_time": "14:00", "end_time": "18:00"}},
        "dialogue": {"excluded_kinds": ["cafe"], "rejected_places": ["합성 제외 장소"]},
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "다른 곳으로 추천해줘"}]}
    )
    data = json.loads(messages(body, context, None, TODAY)[1]["content"].split("\n", 1)[1])
    assert data["time_window"] == {"start_time": "14:00", "end_time": "18:00"}
    assert data["preferences"]["excluded_kinds"] == ["cafe"]


def test_quoted_pending_status_is_not_a_background_promise_classifier(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    reply = (
        "현재 지역을 확인하는 질문이 남아 있고 카페를 찾는 중이라는 요청이 보관돼 있어요. "
        "예산은 50,000원이에요."
    )
    result = asyncio.run(
        flow.turn("지금 상태 알려줘", decision(answer="conversation", reply=reply))
    )
    assert result.reply == reply and result.context.budget == BASE["budget"]


def test_unavailable_saved_place_capability_is_narrowed_in_model_schema():
    from we2day_api.ai_turn_selector import format_json

    schema = json.loads(format_json(False))["json_schema"]["schema"]

    def visit(value):
        if isinstance(value, dict):
            if "selected" in value.get("properties", {}):
                assert value["properties"]["selected"]["enum"] == [False]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def test_region_label_cannot_replace_the_search_goal(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    bad = decision(
        act="request",
        operation="search",
        searches=[{"target": "성수동", "kind": "restaurant", "area": "성수동"}],
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "성수동에서 먹을 곳",
                bad,
                responses=[native(("plan_turn", bad)), native(("plan_turn", bad))],
            )
        )
    assert not flow.queries and flow.store.version == 0


def test_exclusion_restore_and_side_question_preserve_the_existing_course(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "성수 카페는 앞으로 후보에서 제외해줘",
            decision(
                act="request",
                operation="edit",
                preferences={
                    "exclude_places": ["성수 카페"],
                    "evidence": "성수 카페는 앞으로 후보에서 제외해줘",
                },
            ),
        )
    )
    assert result.plan is None and result.context.dialogue.rejected_places == ["성수 카페"]
    assert flow.store.proposal == PROPOSAL
    question = asyncio.run(flow.turn("얼마였지", decision()))
    assert question.context.dialogue.rejected_places == ["성수 카페"]
    restored = asyncio.run(
        flow.turn(
            "성수 카페 제외 취소",
            decision(
                act="request",
                operation="edit",
                preferences={"restore_places": ["성수 카페"], "evidence": "성수 카페 제외 취소"},
            ),
        )
    )
    assert restored.context.dialogue.rejected_places == [] and restored.plan is None


def test_information_cannot_change_preferences():
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(
            decision(preferences={"exclude_kinds": ["cafe"], "evidence": "카페"})
        )


def test_exclusion_names_require_current_explicit_evidence(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    bad = decision(
        act="request",
        operation="edit",
        preferences={"exclude_places": ["명시하지 않은 장소"], "evidence": "카페는 빼줘"},
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "카페는 빼줘",
                bad,
                responses=[native(("plan_turn", bad)), native(("plan_turn", bad))],
            )
        )
    assert flow.store.version == 0


def test_time_shift_and_swap_are_server_arithmetic_with_untouched_metadata(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "두 활동을 30분씩 미뤄줘",
            decision(
                act="request",
                operation="edit",
                activity_edits=[
                    {"ref": "activity_1", "operation": "shift", "offset_minutes": 30},
                    {"ref": "activity_2", "operation": "shift", "offset_minutes": 30},
                ],
            ),
        )
    )
    assert [a.time for a in result.plan.activities] == ["14:30", "16:30"]
    assert [a.place for a in result.plan.activities] == ["서울숲", "성수 카페"]
    swapped = asyncio.run(
        flow.turn(
            "첫째랑 둘째 순서만 바꿔줘",
            decision(
                act="request",
                operation="edit",
                activity_edits=[
                    {"ref": "activity_1", "operation": "swap", "swap_with": "activity_2"}
                ],
            ),
        )
    )
    assert [a.place for a in swapped.plan.activities] == ["성수 카페", "서울숲"]
    assert swapped.plan.preparation == ["우산"]


def test_unknown_or_cross_midnight_shift_is_atomic(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    bad = decision(
        act="request",
        operation="edit",
        activity_edits=[{"ref": "activity_2", "operation": "shift", "offset_minutes": 600}],
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            flow.turn(
                "10시간 미뤄줘",
                bad,
                responses=[native(("plan_turn", bad)), native(("plan_turn", bad))],
            )
        )
    assert flow.store.version == 0 and flow.store.proposal == PROPOSAL


def test_cancel_does_not_restore_an_exclusion_from_a_still_open_place_selection(monkeypatch):
    flow = EngineFlow(
        monkeypatch,
        {**BASE, "dialogue": {"turn_version": 0, "rejected_places": ["성수 카페"]}},
        PROPOSAL,
    )
    result = asyncio.run(
        flow.turn(
            "취소해",
            decision(act="request", operation="cancel", pending="resolve"),
            chosen_places=[{"title": "성수 카페", "address": "성수동"}],
        )
    )
    assert result.context.dialogue.rejected_places == ["성수 카페"]
    assert not flow.queries


@pytest.mark.parametrize(
    "source,expected",
    [
        ("2만5천원", 25000),
        ("0원", 0),
        ("3.5만원", 35000),
        ("12,000원", 12000),
        ("인당2만원", None),
        ("알아서", None),
    ],
)
def test_budget_normalization_only_consumes_numeric_slot_values(source, expected):
    from we2day_api.ai_turn_routing import quoted_money

    assert quoted_money(source) == expected


def test_bound_argument_schema_does_not_offer_another_operation():
    from we2day_api.ai_turn_selector import format_json

    schema = json.loads(format_json(False, "resume"))["json_schema"]["schema"]
    assert schema["properties"]["decision"]["$ref"].endswith("/ResumeTurn")
    assert "ReadTurn" not in schema["$defs"] and "PlanTurn" not in schema["$defs"]


def test_answer_slot_is_quoted_and_does_not_reinterpret_a_side_question():
    from we2day_api.ai_turn_routing import Route, ready_route

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "성수동에서 보면 돼"}]}
    )
    context = {**BASE, "turn_engine": {"pending": {"field": "region", "resume": "search"}}}
    plan = ready_route(Route(kind="resume", value="성수동"), body, context, TODAY)
    assert plan.delta.region == "성수동" and plan.operation == "resume"
    assert ready_route(Route(kind="resume", value="다른 동네"), body, context, TODAY) is None
    assert ready_route(Route(kind="status"), body, context, TODAY).operation == "answer"


def test_argument_extraction_cannot_switch_a_fixed_search_into_a_calendar_read(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    search = decision(
        act="request",
        operation="search",
        searches=[{"target": "카페", "kind": "cafe", "area": "성수동"}],
    )
    wrong = decision(reads=[{"name": "read_shared_calendar"}])
    from we2day_api import ai_turn_selector
    from we2day_api.ai_turn_routing import Route

    async def fixed(*args):
        return Route(kind="search")

    monkeypatch.setattr(ai_turn_selector, "classify", fixed)
    result = asyncio.run(
        flow.turn(
            "성수동 카페",
            {},
            responses=[native(("plan_turn", wrong)), native(("plan_turn", search))],
        )
    )
    assert not flow.reads and result.candidates
    assert len(flow.models) == 2


@pytest.mark.parametrize(
    "kind,continuation,expected",
    [("search", True, "resume"), ("resume", False, "resume"), ("status", False, "status")],
)
def test_dialogue_relation_is_independent_of_underlying_work_kind(kind, continuation, expected):
    from we2day_api.ai_turn_routing import classify

    context = {
        "turn_engine": {
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [{"target": "카페", "kind": "cafe"}],
            }
        }
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "성수동에서 보면 돼"}]}
    )

    def provider(request):
        encoded = json.loads(request.content)
        assert "current_proposal" not in json.loads(encoded["input"][1]["content"])
        return response_output(
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "kind": kind,
                                        "continuation": continuation,
                                        "value": "성수동" if expected == "resume" else None,
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await classify(
                body,
                context,
                TODAY,
                Settings(_env_file=None),
                client,
                Budget(),
                RunStats("test"),
                __import__("time").monotonic() + 30,
            )

    assert asyncio.run(run()).kind == expected


def test_informational_route_cannot_also_consume_a_pending_answer():
    from we2day_api.ai_turn_routing import classify

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "이번주 토요일 언제지"}]}
    )

    async def run():
        def provider(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"kind": "date", "continuation": True, "value": "토요일"}
                                )
                            }
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await classify(
                body,
                {"dialogue": {"pending": {"field": "region", "resume": "search"}}},
                TODAY,
                Settings(_env_file=None),
                client,
                Budget(),
                RunStats("test"),
                __import__("time").monotonic() + 30,
            )

    with pytest.raises(HTTPException):
        asyncio.run(run())


def test_model_only_receives_current_activity_refs_and_cannot_invent_an_anchor():
    from we2day_api.ai_turn_selector import format_json

    empty = json.loads(format_json(False, "search", 0))["json_schema"]["schema"]
    assert empty["$defs"]["SearchTask"]["properties"]["anchor_ref"]["enum"] == [""]
    active = json.loads(format_json(False, "search", 2))["json_schema"]["schema"]
    assert active["$defs"]["SearchTask"]["properties"]["anchor_ref"]["enum"] == [
        "",
        "activity_1",
        "activity_2",
    ]


def test_current_is_not_a_saved_plan_identifier():
    from we2day_api.ai_turn_contract import ReadTask

    with pytest.raises(ValidationError):
        ReadTask(name="read_shared_plan", plan_id="current")


def test_truncated_route_cannot_change_or_consume_pending_state(monkeypatch):
    context = {
        **BASE,
        "dialogue": {"turn_version": 0, "pending": {"field": "region", "resume": "search"}},
    }
    flow = EngineFlow(monkeypatch, context, PROPOSAL)
    truncated = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": '{"kind":"resume","continuation'},
                    "finish_reason": "length",
                }
            ]
        },
    )
    with pytest.raises(HTTPException):
        asyncio.run(flow.turn("성수동", {}, responses=[truncated, truncated]))
    assert flow.store.version == 0 and flow.store.context == context and not flow.queries


@pytest.mark.parametrize("valid_arguments", [True, False])
def test_routing_and_argument_recovery_share_one_repair_and_three_calls(
    monkeypatch, valid_arguments
):
    context = {
        **BASE,
        "region": "",
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [{"target": "카페", "kind": "cafe"}],
            },
        },
    }
    flow = EngineFlow(monkeypatch, context)
    incomplete = httpx.Response(200, json={"status": "incomplete", "output": []})
    payload = decision(
        operation="resume", act="slot_answer", delta={"region": "성수동", "evidence": "성수동이야"}
    )
    if not valid_arguments:
        payload["delta"]["budget"] = -1

    async def run():
        return await flow.turn(
            "성수동이야", payload, responses=[incomplete, native(("plan_turn", payload))]
        )

    if valid_arguments:
        result = asyncio.run(run())
        assert result.candidates and result.context.region == "성수동"
        assert flow.stats[-1]["selection_repair_attempts"] == 1
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(run())
        assert error.value.detail == "ai_selection_failed"
        assert flow.store.version == 0 and not flow.queries
    assert len(flow.models) == 3


@pytest.mark.parametrize("status", [429, 503])
def test_route_provider_limits_and_failures_never_enter_format_retry(monkeypatch, status):
    flow = EngineFlow(monkeypatch, BASE)
    with pytest.raises(HTTPException) as error:
        asyncio.run(flow.turn("현재 조건 알려줘", {}, responses=[httpx.Response(status, json={})]))
    assert error.value.status_code == status and len(flow.models) == 1
    assert flow.store.version == 0 and not flow.queries


def test_unreviewed_results_are_not_reported_as_an_empty_search_after_repair(monkeypatch):
    from we2day_api.places import SearchResults

    flow = EngineFlow(monkeypatch, BASE)

    class IO:
        def __init__(self, *args):
            self.stats, self.budget = args[-1], args[-2]

        async def perform(self, action):
            flow.queries.append(action)
            return SearchResults(
                items=[
                    {
                        "title": "합성 식당",
                        "category": "음식점>한식",
                        "roadAddress": "서울특별시 성동구 성수동 1",
                    }
                ]
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    payload = decision(
        operation="search",
        searches=[
            {
                "target": "먹을 만한 곳",
                "kind": "restaurant",
                "mode": "category",
                "area": "성수동",
                "category_retrieval": True,
            }
        ],
    )
    incomplete = httpx.Response(200, json={"status": "incomplete", "output": []})
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            flow.turn(
                "성수동에서 먹을 만한 곳 찾아줘",
                payload,
                responses=[incomplete, native(("plan_turn", payload))],
            )
        )
    assert error.value.detail == "ai_selection_failed"
    assert len(flow.models) == 3 and len(flow.queries) == 1
    assert flow.store.version == 0 and flow.store.context == BASE
    assert all(model["text"]["format"] == {"type": "text"} for model in flow.models)


@pytest.mark.parametrize(
    "area", ["지인 집 근처", "누군가 회사 주변", "친구 직장 인근에서", "우리집 주위"]
)
def test_private_alias_proximity_is_not_a_public_search_location(monkeypatch, area):
    flow = EngineFlow(monkeypatch, BASE)
    text = f"{area} 고깃집 찾아줘"
    result = asyncio.run(
        flow.turn(
            text,
            decision(
                act="request",
                operation="search",
                delta={"region": area, "evidence": text},
                searches=[{"target": "고깃집", "kind": "restaurant", "area": area}],
            ),
        )
    )
    assert not flow.queries and result.context.dialogue.pending.field == "region"
    assert result.context.region == BASE["region"]
    assert result.context.turn_engine["pending"]["searches"][0]["target"] == "고깃집"


@pytest.mark.parametrize("alias", ["누군가 집", "누군가 회사", "아주 긴 이름의 개인 직장"])
@pytest.mark.parametrize("relation", ["근처", "주변", "인근", "주위"])
@pytest.mark.parametrize("tail", ["", "에서", " 카페"])
def test_relative_private_location_keeps_its_basis_even_with_trailing_activity(
    alias, relation, tail
):
    from we2day_api.ai_place_answers import private_anchor

    assert private_anchor(f"{alias} {relation}{tail}")


def test_authored_form_has_a_fixed_operation_without_semantic_model_routing(monkeypatch):
    from we2day_api import ai_turn_selector

    async def forbidden(*args):
        raise AssertionError("Form operation is already explicit")

    monkeypatch.setattr(ai_turn_selector, "classify", forbidden)
    flow = EngineFlow(monkeypatch, BASE)
    result = asyncio.run(
        flow.turn(
            "입력한 조건",
            decision(
                act="request", operation="search", searches=[{"target": "카페", "kind": "cafe"}]
            ),
            brief={"date": None, "region": "성수동", "activities": ["카페"], "recommend": False},
        )
    )
    assert result.candidates and result.plan is None and result.context.date is None
    assert flow.stats[-1]["model_calls"] == 1


def test_unknown_private_basis_cannot_fall_back_to_an_old_course_anchor(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "지인 집 근처에서 고깃집 찾아줘",
            decision(
                act="request",
                operation="search",
                delta={"region": "지인 집 근처", "evidence": "지인 집 근처에서 고깃집 찾아줘"},
                searches=[
                    {
                        "target": "고깃집",
                        "kind": "restaurant",
                        "area": "지인 집 근처",
                        "anchor_ref": "activity_2",
                    }
                ],
            ),
        )
    )
    assert not flow.queries and result.context.dialogue.pending.field == "region"
    assert result.context.region == BASE["region"]


def test_explicit_new_query_area_takes_precedence_over_an_old_course_reference(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "부산시에서 카페 찾아줘",
            decision(
                act="request",
                operation="search",
                searches=[
                    {"target": "카페", "kind": "cafe", "area": "부산시", "anchor_ref": "activity_1"}
                ],
            ),
        )
    )
    assert flow.queries and all("부산시" in q[1] for q in flow.queries)
    assert result.context.region == BASE["region"]


def test_final_place_refs_are_request_local_and_only_include_current_evidence():
    one = ai_planner.answer_format("2026-11-14", 1, allowed_refs=["public_a"])
    two = ai_planner.answer_format("2026-11-14", 1, allowed_refs=["public_b"])

    def refs(fmt):
        return fmt["json_schema"]["schema"]["$defs"]["ModelActivity"]["properties"][
            "place_ref"
        ].get("enum")

    assert refs(one) == ["public_a"] and refs(two) == ["public_b"]
    assert refs(ai_planner.ANSWER_FORMAT) is None


def test_new_edit_does_not_silently_resume_an_old_search(monkeypatch):
    before = {
        **BASE,
        "turn_engine": {
            "version": 1,
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [{"target": "카페", "kind": "cafe"}],
            },
        },
    }
    flow = EngineFlow(monkeypatch, before, PROPOSAL)
    result = asyncio.run(
        flow.turn(
            "검색 말고 지역만 부산시로 바꿔줘",
            decision(
                act="request",
                operation="edit",
                delta={"region": "부산시", "evidence": "지역만 부산시로 바꿔줘"},
            ),
        )
    )
    assert result.context.region == "부산시" and result.context.dialogue.pending is None
    assert not flow.queries


@pytest.mark.parametrize("area", ["여기", "내 근처", "현재 위치", "그곳"])
def test_unknown_relative_location_is_a_question_not_a_literal_query(monkeypatch, area):
    flow = EngineFlow(monkeypatch, BASE, PROPOSAL)
    text = f"{area} 카페 찾아줘"
    result = asyncio.run(
        flow.turn(
            text,
            decision(
                act="request",
                operation="search",
                delta={"region": area, "evidence": text},
                searches=[
                    {"target": "카페", "kind": "cafe", "area": area, "anchor_ref": "activity_2"}
                ],
            ),
        )
    )
    assert not flow.queries and result.context.dialogue.pending.field == "region"
    assert result.context.region == BASE["region"]


def test_location_answer_substitutes_the_original_unresolved_search_argument():
    from we2day_api.ai_turn_engine import compile_turn

    before = {
        **BASE,
        "turn_engine": {
            "pending": {
                "field": "region",
                "resume": "search",
                "searches": [{"target": "고깃집", "kind": "restaurant", "area": "친구집 주변"}],
            }
        },
    }
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "성수동"}]}
    )
    plan = TurnPlan.model_validate(
        {
            "act": "slot_answer",
            "operation": "resume",
            "delta": {"region": "성수동", "evidence": "성수동"},
        }
    )
    actual = compile_turn(plan, body, before, None, TODAY)
    assert actual.searches[0].area == "성수동" and actual.searches[0].target == "고깃집"


@pytest.mark.parametrize(
    "payload",
    [
        {"clear": ["date"]},
        {"date": {"mode": "absolute", "value": "2026-11-15"}, "budget": 0},
        {"date": {"mode": "absolute", "value": "2026-11-15"}, "clear": ["region"]},
    ],
)
def test_read_continuation_rejects_planning_patches_before_execution(payload):
    before = {
        **BASE,
        "turn_engine": {
            "pending": {
                "field": "date",
                "resume": "answer",
                "reads": [{"name": "read_shared_calendar"}],
            }
        },
    }
    snapshot = copy.deepcopy(before)
    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="2026-11-15")])
    plan = TurnPlan.model_validate({"act": "slot_answer", "operation": "resume", "delta": payload})
    with pytest.raises(ValueError, match="Read answers cannot patch planning state"):
        bind_continuation(plan, before, body)
    assert before == snapshot


def test_read_title_answer_binds_only_to_query_not_current_proposal():
    before = {
        **BASE,
        "turn_engine": {
            "pending": {
                "field": "title",
                "resume": "answer",
                "reads": [{"name": "read_shared_plan"}],
            }
        },
    }
    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="가을 산책")])
    plan = TurnPlan(act="slot_answer", operation="resume", title="가을 산책")
    compiled = bind_continuation(plan, before, body)
    assert compiled.reads[0].title == "가을 산책"
    assert compiled.title is None and compiled.delta.values(TODAY) == {}
    assert before["turn_engine"]["pending"]["field"] == "title"


@pytest.mark.parametrize("target", ["카afe", "unrequested venue", "가짜검색", "선택하지않은활동"])
def test_search_arguments_cannot_invent_or_corrupt_user_terms(target):
    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동 카페 찾아줘")]
    )
    plan = TurnPlan(
        act="request", operation="search", searches=[{"target": target, "area": "성수동"}]
    )
    with pytest.raises(ValueError, match="Search target must quote"):
        validate_effects(plan, body, BASE, None, TODAY)


@pytest.mark.parametrize(
    "target,wrong", [("음식점", "cafe"), ("카페", "restaurant"), ("도서관", "park")]
)
def test_quoted_search_kind_cannot_silently_change_activity_scope(target, wrong):
    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content=f"성수동 {target} 찾아줘")]
    )
    plan = TurnPlan(act="request", operation="search", searches=[{"target": target, "kind": wrong}])
    with pytest.raises(ValueError, match="Search kind conflicts"):
        validate_effects(plan, body, BASE, None, TODAY)


def test_wire_schema_requires_explicit_condition_preservation_without_default_effects():
    from we2day_api.ai_turn_selector import format_json

    schema = json.loads(format_json(False, "search", 0))["json_schema"]["schema"]
    assert set(schema["$defs"]["SearchTurn"]["required"]) == {"kind", "searches", "delta"}
    assert set(schema["$defs"]["SearchTask"]["required"]) == {
        "target",
        "kind",
        "mode",
        "area",
        "category_retrieval",
    }
    assert set(schema["$defs"]["Delta"]["required"]) == set(schema["$defs"]["Delta"]["properties"])
    assert schema["$defs"]["Delta"]["additionalProperties"] is False


def test_provider_schema_omits_regex_without_weakening_server_validation():
    from we2day_api.ai_turn_contract import SearchTask
    from we2day_api.ai_turn_selector import format_json

    schema = json.loads(format_json(False, "plan", 0))["json_schema"]["schema"]
    assert "pattern" not in json.dumps(schema)
    with pytest.raises(ValidationError):
        SearchTask(target="카페<script>")
    with pytest.raises(ValidationError):
        SearchTask(target="카페", anchor_ref="activity_999")
    assert schema["$defs"]["SearchTask"]["properties"]["anchor_ref"]["enum"] == [""]


def test_unchanged_echo_is_not_a_new_condition_change():
    from we2day_api.ai_turn_engine import compile_turn

    context = {**BASE, "turn_engine": {"version": 1, "unverified_fields": []}}
    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="정한 날짜 그대로 카페 코스 만들어 줘")]
    )
    plan = TurnPlan.model_validate(
        {
            "act": "request",
            "operation": "plan",
            "delta": {
                "date": {"mode": "absolute", "value": BASE["date"], "source": BASE["date"]},
                "region": BASE["region"],
                "budget": BASE["budget"],
                "transport": BASE["transport"],
                "activities": BASE["activities"],
                "evidence": "model paraphrase is not new evidence",
            },
        }
    )
    compiled = compile_turn(plan, body, context, None, TODAY)
    assert compiled.delta.values(TODAY) == {}
    assert compiled.searches[0].target == "카페"
    assert context["date"] == BASE["date"]


def test_changed_value_still_requires_user_evidence_after_noop_normalization():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="카페 코스 만들어 줘")]
    )
    plan = TurnPlan.model_validate(
        {
            "act": "request",
            "operation": "plan",
            "delta": {
                "region": BASE["region"],
                "budget": 100000,
                "evidence": "not the latest user quote",
            },
        }
    )
    with pytest.raises(ValueError, match="Ungrounded condition change"):
        compile_turn(plan, body, BASE, None, TODAY)


def test_explicit_clear_and_unverified_reconfirmation_are_not_dropped_as_noops():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동으로, 날짜는 미정으로 해줘")]
    )
    context = {**BASE, "date": None}
    plan = TurnPlan.model_validate(
        {
            "act": "request",
            "operation": "edit",
            "delta": {"region": "성수동", "clear": ["date"], "evidence": body.messages[-1].content},
        }
    )
    # The legacy region is explicitly confirmed even though its text is equal.
    actual = compile_turn(plan, body, context, None, TODAY)
    assert actual.delta.region == "성수동" and actual.delta.clear == ["date"]


@pytest.mark.parametrize("region", ["성수동", "중랑구", "양주시", "해운대구"])
def test_literal_region_reconfirmation_does_not_need_a_duplicate_quote(region):
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content=f"{region} 카페 찾아줘")]
    )
    before = {**BASE, "region": region}
    plan = TurnPlan(
        act="request",
        operation="search",
        delta={"region": region},
        searches=[{"target": "카페", "area": region}],
    )
    actual = compile_turn(plan, body, before, None, TODAY)
    assert actual.delta.region == region
    assert actual.delta.values(TODAY) == {"region": region}


def test_intrinsic_region_proof_cannot_authorize_an_unrelated_change():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동 카페 찾아줘")]
    )
    plan = TurnPlan(
        act="request",
        operation="search",
        delta={"region": "성수동", "budget": 1},
        searches=[{"target": "카페"}],
    )
    with pytest.raises(ValueError, match="Ungrounded condition change"):
        compile_turn(plan, body, BASE, None, TODAY)


def test_optional_kind_and_area_prefix_are_normalized_before_policy_binding():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동에서 카페 찾아줘")]
    )
    plan = TurnPlan(
        act="request", operation="search", searches=[{"target": "성수동 카페", "area": "성수동"}]
    )
    actual = compile_turn(plan, body, BASE, None, TODAY)
    assert actual.searches[0].target == "카페" and actual.searches[0].kind == "cafe"


def test_generic_activity_does_not_restore_an_exact_name_filter():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="카페 찾아줘")])
    plan = TurnPlan(
        act="request", operation="search", searches=[{"target": "카페", "mode": "exact_name"}]
    )
    actual = compile_turn(plan, body, BASE, None, TODAY)
    assert actual.searches[0].mode == "category" and actual.searches[0].kind == "cafe"


def test_exact_venue_with_area_in_its_name_preserves_the_literal_title():
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동 하루카페 찾아줘")]
    )
    plan = TurnPlan(
        act="request",
        operation="search",
        searches=[{"target": "성수동 하루카페", "area": "성수동", "mode": "exact_name"}],
    )
    actual = compile_turn(plan, body, BASE, None, TODAY)
    assert (
        actual.searches[0].target == "성수동 하루카페" and actual.searches[0].mode == "exact_name"
    )


def test_model_date_arguments_do_not_offer_conflicting_offset_slots():
    from we2day_api.ai_turn_selector import format_json

    spec = json.loads(format_json(False, "edit", 0))["json_schema"]["schema"]["$defs"]["DateSpec"]
    assert set(spec["properties"]) == {"mode", "source", "value"}
    assert spec["properties"]["mode"]["enum"] == ["absolute"]
    assert set(spec["required"]) == {"mode", "source"}


def test_inferred_kind_keeps_query_and_relevance_policy_in_the_same_identity(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    result = asyncio.run(
        flow.turn(
            "성수동에서 카페 찾아줘",
            decision(
                act="request",
                operation="search",
                searches=[{"target": "성수동 카페", "area": "성수동"}],
            ),
        )
    )
    assert len(result.candidates) == 1 and result.candidates[0].title == "성수 카페"
    assert result.plan is None
    assert flow.queries[0][1] == "성수동 카페"


@pytest.mark.parametrize("has_pending", [False, True])
def test_route_schema_only_offers_existing_pending_task_relations(has_pending):
    from we2day_api.ai_turn_routing import classify

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="예산을 3만원으로 바꿔")]
    )
    context = (
        {"dialogue": {"pending": {"field": "region", "resume": "search"}}} if has_pending else {}
    )

    async def run():
        def provider(request):
            schema = sent_schema(json.loads(request.content))
            props = schema["properties"]
            if has_pending:
                assert "resume" in props["kind"]["enum"]
            else:
                assert "resume" not in props["kind"]["enum"]
                assert props["continuation"]["enum"] == [False]
                assert props["value"]["type"] == "null"
            return response_output(
                httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {"kind": "edit", "continuation": False, "value": None}
                                    )
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    },
                )
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await classify(
                body,
                context,
                TODAY,
                Settings(_env_file=None),
                client,
                Budget(),
                RunStats("test"),
                __import__("time").monotonic() + 45,
            )

    assert asyncio.run(run()).kind == "edit"


def test_native_workers_ai_schema_envelope_preserves_constraints_and_input():
    from we2day_api.ai_wire import workers_ai_inputs

    template = {
        "type": "object",
        "properties": {"value": {"type": "integer", "minimum": 0}},
        "required": ["value"],
        "additionalProperties": False,
    }
    original = {
        "model": "@cf/openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "synthetic"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "test_response", "strict": True, "schema": template},
        },
    }
    before = copy.deepcopy(original)
    actual = workers_ai_inputs(original)
    assert original == before
    schema = actual["response_format"]["json_schema"]
    assert "schema" not in schema and "strict" not in schema and "name" not in schema
    assert schema == {**template, "title": "test_response"}
    actual["messages"][0]["content"] = "changed"
    assert original == before


def test_native_workers_ai_format_conversion_is_idempotent_and_leaves_plain_json_alone():
    from we2day_api.ai_wire import workers_ai_inputs

    for fmt in [
        {"type": "json_object"},
        {"type": "json_schema", "json_schema": {"type": "object", "properties": {}}},
    ]:
        original = {"response_format": fmt}
        assert workers_ai_inputs(original) == original
        assert workers_ai_inputs(workers_ai_inputs(original)) == original


def test_only_the_fixed_operation_instructions_are_sent_with_one_leading_system():
    from we2day_api.ai_turn_selector import messages

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content="성수동 카페 찾아줘")]
    )
    actual = messages(body, BASE, None, TODAY, kind="search")
    assert sum(m["role"] == "system" for m in actual) == 1
    assert "Fixed operation search:" in actual[0]["content"]
    assert "Fixed operation edit:" not in actual[0]["content"]
    assert actual[-1]["content"] == body.messages[-1].content


def test_new_plan_requires_a_search_when_no_verified_place_source_is_available():
    from we2day_api.ai_turn_selector import format_json

    schema = json.loads(format_json(False, "plan", 0, True))["json_schema"]["schema"]
    plan = schema["$defs"]["PlanTurn"]
    assert plan["required"] == ["kind", "searches", "delta"]
    assert plan["properties"]["searches"]["minItems"] == 1
    chosen = json.loads(format_json(False, "plan", 0, False))["json_schema"]["schema"]
    assert chosen["$defs"]["PlanTurn"]["required"] == ["kind", "delta"]


def test_exact_venue_query_uses_the_same_identity_as_the_approved_search():
    from we2day_api.ai_place_policy import PlacePolicy, SearchScope
    from we2day_api.places import PlaceResult

    policy = PlacePolicy(
        SearchScope(
            area="용산구", kinds=["museum"], exact_name="국립중앙박물관", name_kind="museum"
        ),
        "용산구 국립중앙박물관 찾아줘",
        queries=[("museum", "국립중앙박물관", "국립중앙박물관")],
    )
    args, error = policy.prepare(
        {
            "mode": "exact_name",
            "name": "국립중앙박물관",
            "query": "국립중앙박물관",
            "kind": "museum",
            "area": "용산구",
        }
    )
    assert not error and policy.query_target(args) == ("museum", "국립중앙박물관")
    item = PlaceResult(
        title="국립중앙박물관",
        category="문화시설>박물관",
        roadAddress="서울특별시 용산구 서빙고로 137",
    )
    assert policy.relevant(item, args)
    other = item.model_copy(update={"title": "국립중앙박물관 옆 카페", "category": "카페"})
    assert not policy.relevant(other, args)


def test_literal_task_area_can_confirm_existing_legacy_region_without_replacing_it(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    result = asyncio.run(
        flow.turn(
            "성수동 카페 후보만",
            decision(
                act="request",
                operation="search",
                searches=[{"target": "카페", "kind": "cafe", "area": "성수동"}],
            ),
        )
    )
    assert result.context.region == BASE["region"]
    assert "region" not in result.context.model_dump()["turn_engine"]["unverified_fields"]
    old = copy.deepcopy(flow.store.context)
    status = asyncio.run(flow.turn("지금 조건은", decision()))
    assert status.context.region == BASE["region"] and not status.plan
    assert flow.store.context["region"] == old["region"]


def test_old_engine_revision_cannot_reuse_trusted_location_provenance():
    from we2day_api.ai_state import current_context

    before = {
        **BASE,
        "turn_engine": {
            "version": 1,
            "basis": 2,
            "unverified_fields": [],
            "pending": {"field": "region", "resume": "search"},
        },
    }
    actual = current_context(before, 3)
    assert actual["region"] == before["region"]
    assert actual["turn_engine"]["pending"] is None
    assert actual["turn_engine"]["unverified_fields"] == ["region"]
    assert before["turn_engine"]["unverified_fields"] == []


@pytest.mark.parametrize(
    "goal,kind", [("먹을 만한 곳", "restaurant"), ("쉴 만한 곳", "cafe"), ("책 읽을 곳", "library")]
)
def test_verbal_goals_and_duplicated_area_particles_cannot_be_exact_venues(goal, kind):
    from we2day_api.ai_turn_engine import compile_turn

    body = ai_planner.ChatInput(
        messages=[ai_planner.Message(role="user", content=f"성수동에서 {goal} 추천해 줘")]
    )
    plan = TurnPlan(
        act="request",
        operation="search",
        searches=[
            {"target": f"성수동에서 {goal}", "kind": kind, "mode": "exact_name", "area": "성수동"}
        ],
    )
    task = compile_turn(plan, body, BASE, None, TODAY).searches[0]
    assert task.target == goal and task.mode == "category" and task.category_retrieval


def test_unambiguous_verified_single_activity_needs_no_completion_inference(monkeypatch):
    context = {**BASE, "requirements": "", "budget": None}
    flow = EngineFlow(monkeypatch, context)

    async def forbidden(*args, **kwargs):
        pytest.fail("Verified deterministic fields must not be regenerated")

    monkeypatch.setattr(ai_planner, "complete", forbidden)
    result = asyncio.run(
        flow.turn(
            "정한 날짜에 성수동 카페 한 곳 코스",
            decision(
                act="request",
                operation="plan",
                searches=[{"target": "카페", "kind": "cafe", "area": "성수동"}],
            ),
        )
    )
    assert result.plan and result.plan.date == BASE["date"] and result.plan.budget is None
    assert len(result.plan.activities) == 1 and result.plan.activities[0].place.startswith(
        "성수 카페"
    )
    assert result.plan.activities[0].time is None and result.plan.activities[0].cost is None
    assert flow.stats[-1]["model_calls"] == 2 and flow.stats[-1]["direct_verified_plans"] == 1


def test_keyword_results_do_not_expand_into_other_activities_or_extra_inference(monkeypatch):
    from we2day_api.places import SearchResults

    flow = EngineFlow(monkeypatch, BASE)

    class IO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            assert action[0] == "places"
            return SearchResults(
                items=[
                    {
                        "title": "수원 책방",
                        "category": "서점",
                        "roadAddress": "경기도 수원시 팔달구 1",
                    },
                    {
                        "title": "수원 카페",
                        "category": "카페",
                        "roadAddress": "경기도 수원시 팔달구 2",
                    },
                ]
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    result = asyncio.run(
        flow.turn(
            "수원시 서점 후보만 찾아줘",
            decision(
                act="request", operation="search", searches=[{"target": "서점", "area": "수원시"}]
            ),
        )
    )
    assert [c.title for c in result.candidates] == ["수원 책방"]
    assert flow.stats[-1]["model_calls"] == 2
    assert result.context.region == BASE["region"]


def test_explicit_region_for_new_course_is_bound_as_a_planning_condition(monkeypatch):
    flow = EngineFlow(monkeypatch, BASE)
    result = asyncio.run(
        flow.turn(
            "부산에서 카페 코스 만들어줘",
            decision(
                act="request",
                operation="plan",
                searches=[{"target": "카페", "kind": "cafe", "area": "부산"}],
            ),
        )
    )
    assert result.context.region == "부산"
    assert result.context.date == BASE["date"] and result.context.budget == BASE["budget"]


@pytest.mark.parametrize(
    "restriction", ["requirements", "window", "new_window", "related", "multiple", "previous"]
)
def test_direct_single_plan_never_bypasses_ambiguous_or_additional_requirements(restriction):
    from types import SimpleNamespace

    from we2day_api.ai_tools import Candidate
    from we2day_api.ai_turn_contract import SearchTask
    from we2day_api.ai_turn_engine import verified_single_plan

    candidate = Candidate(ref="p1", title="검증 후보", address="성수동", source="naver")
    candidates = [candidate]
    working = {**BASE, "requirements": ""}
    changes = {}
    proposal = None
    if restriction == "requirements":
        working["requirements"] = "추가 조건"
    elif restriction == "window":
        working["intake"] = {"data": {"start_time": "14:00"}}
    elif restriction == "new_window":
        changes["start_time"] = "15:00"
    elif restriction == "related":
        candidate.match = "related"
    elif restriction == "multiple":
        candidates.append(candidate.model_copy(update={"ref": "p2", "title": "다른 후보"}))
    else:
        proposal = PlanContent.model_validate(PROPOSAL)
    session = SimpleNamespace(visible_candidates=lambda: candidates)
    body = ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="코스 생성")])
    assert (
        verified_single_plan(
            session, [SearchTask(target="카페")], working, body, proposal, "replace", changes
        )
        is None
    )


def test_mixed_general_and_known_kinds_keep_each_verified_search_result(monkeypatch):
    from we2day_api.places import SearchResults

    flow = EngineFlow(monkeypatch, BASE)

    class IO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            assert action[0] == "places"
            return SearchResults(
                items=[
                    {
                        "title": "수원 서점",
                        "category": "서점",
                        "roadAddress": "경기도 수원시 팔달구 1",
                    },
                    {
                        "title": "수원 카페",
                        "category": "카페",
                        "roadAddress": "경기도 수원시 팔달구 2",
                    },
                ]
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    result = asyncio.run(
        flow.turn(
            "수원시 서점과 카페 후보만",
            decision(
                act="request",
                operation="search",
                searches=[
                    {"target": "서점", "kind": "any", "area": "수원시"},
                    {"target": "카페", "kind": "cafe", "area": "수원시"},
                ],
            ),
        )
    )
    assert {c.title for c in result.candidates} == {"수원 서점", "수원 카페"}
    assert result.plan is None and result.context.region == BASE["region"]
