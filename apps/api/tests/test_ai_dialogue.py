import asyncio
import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from dialogue_evaluation import MemoryStore, grade, set_path

from we2day_api.ai_dialogue import DialogueState, analyze, merge_context
from we2day_api.ai_planner import ChatInput, _chat
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import ChosenPlace
from we2day_api.plans import PlanContent

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/ai_dialogue_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"])
def test_frozen_korean_request_control(case):
    context = copy.deepcopy(case["initial"].get("context", {}))
    proposal = (
        PlanContent.model_validate(case["initial"]["proposal"])
        if "proposal" in case["initial"]
        else None
    )
    chosen = case.get("chosen", [])
    for step in case["steps"]:
        chosen = step.get("chosen", chosen)
        directive = analyze(
            step["text"],
            context,
            proposal,
            [ChosenPlace.model_validate(p) for p in chosen],
            date(2026, 10, 27),
        )
        expected = step["expect"]
        if "patch" in expected:
            target = proposal.model_dump()
            for path, value in expected["patch"].items():
                set_path(target, path, value)
            assert directive.plan and directive.plan.model_dump() == target
        if expected.get("reply_any"):
            assert any(
                "".join(v.split()) in "".join(directive.reply.split())
                for v in expected["reply_any"]
            )
        if expected.get("no_search"):
            assert "search_places" not in directive.allowed_tools
        if expected.get("needs_search"):
            assert "search_places" in directive.allowed_tools
        for key, value in expected.get("scope", {}).items():
            assert getattr(directive.scope, key) == value
        context = merge_context(context, {}, directive)
        if directive.plan:
            proposal = directive.plan


def test_pending_edit_reloads_and_only_named_activity_changes():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze("시간만 15:00로 바꿔줘", {}, proposal, [], date(2026, 10, 27))
    state = DialogueState.model_validate_json(first.state.model_dump_json())
    second = analyze(
        "두 번째 활동", {"dialogue": state.model_dump()}, proposal, [], date(2026, 10, 27)
    )
    assert second.plan.activities[0] == proposal.activities[0]
    assert second.plan.activities[1].time == "15:00" and second.state.pending is None


def test_rejection_is_current_conversation_and_explicitly_reversible():
    first = analyze("'샘플카페A'는 제외해줘", {}, None, [], date(2026, 10, 27))
    assert first.state.rejected_places == ["샘플카페A"]
    second = analyze(
        "샘플카페A 제외 취소", {"dialogue": first.state.model_dump()}, None, [], date(2026, 10, 27)
    )
    assert not second.state.rejected_places
    assert not analyze("중랑구 카페 검색", {}, None, [], date(2026, 10, 27)).state.rejected_places


def test_explicit_date_clear_does_not_reuse_previous_plan_date():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze(
        "날짜는 미정으로 할게", {"date": proposal.date}, proposal, [], date(2026, 10, 27)
    )
    context = merge_context({"date": proposal.date}, {}, first)
    second = analyze("코스에 반영해줘", context, proposal, [], date(2026, 10, 27))
    assert context["date"] is None and second.state.pending.field == "date"
    assert not second.plan and not second.allowed_tools


def test_unknown_future_fields_survive_without_becoming_model_conditions():
    directive = analyze("고마워", {}, None, [], date(2026, 10, 27))
    updated = merge_context(
        {"date": "2030-01-05", "future": {"opaque": True}}, {"date": None, "budget": 5}, directive
    )
    assert updated["date"] == "2030-01-05" and updated["future"] == {"opaque": True}
    assert updated.get("budget") is None


def test_deterministic_edit_uses_no_model_or_provider_reservation():
    async def run():
        case = CORPUS["cases"][0]
        store, rpc_names = MemoryStore(case), []
        original = store.rpc

        async def rpc(name, values=None):
            rpc_names.append(name)
            return await original(name, values)

        store.rpc = rpc
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected model I/O"))
        ) as client:
            result = await _chat(
                ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": case["steps"][0]["text"]}],
                        "conversation_id": "00000000-0000-0000-0000-000000000001",
                        "request_id": "00000000-0000-0000-0000-000000000002",
                    }
                ),
                SimpleNamespace(),
                store,
                client,
                Budget(),
                RunStats("test"),
            )
        assert not grade(
            case, case["steps"][0], result.model_dump(mode="json"), [], case["initial"]["proposal"]
        )
        assert (
            "reserve_ai_planner_request" not in rpc_names
            and store.context["dialogue"]["turn_version"] == 1
        )

    asyncio.run(run())


def test_evaluation_rubric_detects_unintended_edits_and_ignored_rejection():
    case = CORPUS["cases"][0]
    wrong = PlanContent.model_validate(case["initial"]["proposal"]).model_dump()
    wrong["title"] = "조용한 하루"
    wrong["activities"][0]["note"] = "unexpected rewrite"
    assert "unintended_edit_or_missing_patch" in grade(
        case, case["steps"][0], {"plan": wrong}, [], case["initial"]["proposal"]
    )
    assert "rejected_or_outside_candidate" in grade(
        {},
        {"expect": {"candidate_not": ["샘플카페A"]}},
        {"candidates": [{"title": "샘플카페A"}]},
        [],
        None,
    )


@pytest.mark.parametrize("number", ["0", "9", "12", "-1", "열"])
def test_invalid_explicit_activity_number_never_falls_back_to_another_activity(number):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(
        f"{number}번째 카페 활동 시간만 15:00로 바꿔줘", {}, proposal, [], date(2026, 10, 27)
    )
    assert result.plan is None and result.state.pending.field == "activity_time"


@pytest.mark.parametrize(
    "text,amount", [("예산만 5만으로 바꿔줘", 50000), ("예산만 2.5만원으로 수정해줘", 25000)]
)
def test_currency_units_are_preserved(text, amount):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(text, {}, proposal, [], date(2026, 10, 27))
    assert result.plan.budget == amount


@pytest.mark.parametrize("text", ["예산만 100달러로 바꿔줘", "예산만 각자 3만원으로 해줘"])
def test_ambiguous_budget_is_a_question(text):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(text, {}, proposal, [], date(2026, 10, 27))
    assert result.plan is None and result.state.pending.field == "budget"


def test_addition_remains_a_plan_request_and_can_be_cancelled():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze("기존 활동 유지하고 카페 하나 추가해줘", {}, proposal, [], date(2026, 10, 27))
    assert result.intent == "plan" and "search_places" in result.allowed_tools
    assert result.state.append_pending
    cancelled = analyze(
        "취소해줘", {"dialogue": result.state.model_dump()}, proposal, [], date(2026, 10, 27)
    )
    assert cancelled.plan is None and not cancelled.state.append_pending and cancelled.reply


def test_append_restores_every_existing_activity_field_and_plan_metadata():
    from we2day_api.ai_planner import complete
    from we2day_api.ai_tools import ToolSession

    async def run():
        proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.previous_plan, session.append_only, session.direct_final = proposal, True, True
        old = [session.seed(a) for a in proposal.activities]
        new = session.add("샘플카페B", "서울 중랑구 동일로4", "naver")
        answer = {
            "reply": "추가",
            "plan": {
                "title": "unwanted rewrite",
                "date": "2030-01-05",
                "activities": [
                    {
                        "title": "변조된 기존 활동",
                        "time": "01:00",
                        "cost": 9999,
                        "note": "changed",
                        "place_ref": old[0].ref,
                    },
                    {"title": "새 카페", "place_ref": new.ref},
                ],
            },
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(answer)}}]}
                )
            )
        ) as client:
            result = await complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "카페 추가"}],
                session,
                client=client,
            )
        assert result.plan.activities[:2] == proposal.activities
        assert (
            result.plan.title == proposal.title and result.plan.preparation == proposal.preparation
        )
        assert len(result.plan.activities) == 3 and "샘플카페B" in result.plan.activities[-1].place

    asyncio.run(run())


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).parent / "fixtures/ai_dialogue_regressions.json").read_text(
            encoding="utf-8"
        )
    )["cases"],
    ids=lambda c: c["id"],
)
def test_supplemental_control_regressions(case):
    context = copy.deepcopy(case["initial"].get("context", {}))
    proposal = (
        PlanContent.model_validate(case["initial"]["proposal"])
        if "proposal" in case["initial"]
        else None
    )
    chosen = [ChosenPlace.model_validate(p) for p in case.get("chosen", [])]
    for step in case["steps"]:
        directive = analyze(step["text"], context, proposal, chosen, date(2026, 10, 27))
        expect = step["expect"]
        if expect.get("preserve_prefix"):
            assert directive.intent == "plan" and directive.state.append_pending
            assert "search_places" in directive.allowed_tools
        if expect.get("reply_any"):
            assert any(v in directive.reply for v in expect["reply_any"])
        if "retain_only" in expect:
            target = proposal.model_dump()
            target["activities"] = [target["activities"][i] for i in expect["retain_only"]]
            assert directive.plan and directive.plan.model_dump() == target
        context = merge_context(context, {}, directive)
        if directive.plan:
            proposal = directive.plan


def test_selected_saved_place_needs_no_guessed_region_or_unrelated_search():
    from uuid import uuid4

    async def run():
        selected_id = str(uuid4())
        case = {
            "initial": {
                "context": {"date": "2030-01-05", "future_control": "opaque-private-synthetic"}
            }
        }
        store, calls, reads = MemoryStore(case), [], []

        async def read(method, table, params):
            reads.append((method, table, params))
            return [
                {
                    "id": selected_id,
                    "label": "샘플선택장소",
                    "destination": "샘플선택장소 (서울 중랑구 신내로1)",
                }
            ]

        store.call = read

        def handler(request):
            inputs = json.loads(request.content)
            assert "opaque-private-synthetic" not in json.dumps(inputs)
            calls.append(inputs)
            if len(calls) == 1:
                assert [t["function"]["name"] for t in inputs["tools"]] == [
                    "lookup_selected_places"
                ]
                message = {
                    "tool_calls": [
                        {"function": {"name": "lookup_selected_places", "arguments": "{}"}}
                    ]
                }
            else:
                message = {
                    "content": json.dumps(
                        {
                            "reply": "선택 장소 코스",
                            "plan": {
                                "title": "합성",
                                "date": "2030-01-05",
                                "activities": [{"title": "선택 장소", "place_ref": "p1"}],
                            },
                        }
                    )
                }
            return httpx.Response(200, json={"choices": [{"message": message}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await _chat(
                ChatInput.model_validate(
                    {
                        "messages": [
                            {"role": "user", "content": "선택한 저장 장소로 코스를 만들어줘"}
                        ],
                        "selected_places": [{"source": "favorite", "id": selected_id}],
                    "conversation_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    }
                ),
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                store,
                client,
                Budget(),
                RunStats("test"),
            )
        assert result.plan.activities[0].place == "샘플선택장소 (서울 중랑구 신내로1)"
        assert len(calls) == 2 and reads[0][1] == "favorite_places"
        assert reads[0][2]["id"] == f"in.({selected_id})"

    asyncio.run(run())
