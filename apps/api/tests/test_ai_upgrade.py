import copy
import json
from datetime import date
from pathlib import Path

import pytest
from dialogue_evaluation import grade

from we2day_api.ai_dialogue import analyze, merge_context
from we2day_api.ai_tools import StoredContext, check_course
from we2day_api.plans import PlanContent

CORPUS = json.loads((Path(__file__).parent / "fixtures/ai_upgrade_cases.json").read_text("utf-8"))


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"])
def test_new_compound_and_expression_corpus(case):
    context = copy.deepcopy(case["initial"]["context"])
    plan = PlanContent.model_validate(case["initial"]["proposal"])
    for step in case["steps"]:
        result = analyze(step["text"], context, plan, [], date(2026, 10, 27))
        context = merge_context(context, {}, result)
        if step["expect"].get("needs_search"):
            assert "search_places" in result.allowed_tools
        else:
            value = {
                "plan": result.plan.model_dump() if result.plan else None,
                "reply": result.reply,
                "context": context,
                "candidates": [],
            }
            assert grade(case, step, value, [], plan.model_dump()) == []
        StoredContext.model_validate(context)
        if result.plan:
            plan = result.plan


def test_course_warnings_use_only_entered_costs_and_times():
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    original = plan.model_dump()
    assert check_course(plan) == []
    plan.budget = 10000
    plan.activities[1].time = plan.activities[0].time
    issues = check_course(plan)
    assert any("50,000" in s and "10,000" in s for s in issues)
    assert any("같은 시각" in s for s in issues)
    assert plan.activities[0].cost is None
    plan.budget = None
    assert not any("예산" in s for s in check_course(plan))
    assert original["activities"][0]["cost"] is None


def test_invalid_shift_never_partially_updates_the_course():
    initial = CORPUS["cases"][8]["initial"]
    plan = PlanContent.model_validate(initial["proposal"])
    before = plan.model_dump()
    directive = analyze("전체 30분 미뤄줘", {}, plan, [], date(2026, 10, 27))
    assert directive.plan is None and plan.model_dump() == before


def test_unrelated_request_cancels_pending_compound_edit():
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze("두 활동 순서 바꿔줘", {}, plan, [], date(2026, 10, 27))
    context = merge_context({}, {}, first)
    second = analyze("예산만 3만원으로 바꿔줘", context, plan, [], date(2026, 10, 27))
    assert second.plan.budget == 30000 and second.plan.activities == plan.activities
    assert second.slots["activity_edit"] is None


def test_search_does_not_relabel_old_course_places_as_new_results():
    from we2day_api.ai_tools import ToolSession

    session = ToolSession(None, None, [], [])
    session.operation = "search"
    session.seed(
        PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"]).activities[0]
    )
    assert session.visible_candidates() == []


def test_multiple_fields_wait_for_clarification_and_apply_together():
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze(
        "날짜는 2030-01-06으로 바꾸고 예산은 2달러로 바꿔줘", {}, plan, [], date(2026, 10, 27)
    )
    context = merge_context({}, {}, first)
    assert first.plan is None and context.get("date") is None
    assert context["pending_fields"]["values"] == {"date": "2030-01-06"}
    second = analyze("3만원으로 해줘", context, plan, [], date(2026, 10, 27))
    assert second.plan.date == "2030-01-06" and second.plan.budget == 30000
    assert second.plan.activities == plan.activities
    cancelled = analyze("취소해줘", context, plan, [], date(2026, 10, 27))
    assert cancelled.plan is None and cancelled.slots["pending_fields"] is None


def test_long_conversation_resumes_only_the_current_pending_operation():
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4

    import httpx
    from dialogue_evaluation import MemoryStore

    from we2day_api.ai_planner import ChatInput, _chat
    from we2day_api.ai_runtime import Budget, RunStats

    async def run():
        store = MemoryStore(CORPUS["cases"][0])
        store.version = 20
        cid = str(uuid4())
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "과거 합성 문장"}
            for i in range(10)
        ]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No model needed"))
        ) as client:
            for text, prior in [("두 활동 순서 교환해줘", history), ("첫 번째와 세 번째야", [])]:
                stats = RunStats("synthetic")
                result = await _chat(
                    ChatInput.model_validate(
                        {
                            "messages": prior + [{"role": "user", "content": text}],
                            "conversation_id": cid,
                            "request_id": str(uuid4()),
                            "version": store.version,
                        }
                    ),
                    SimpleNamespace(),
                    store,
                    client,
                    Budget(),
                    stats,
                )
                assert stats.counts["model_calls"] == 0
                store.context = json.loads(json.dumps(store.context))
            expected = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
            assert result.plan.activities == [
                expected.activities[2],
                expected.activities[1],
                expected.activities[0],
            ]
            assert result.plan.preparation == expected.preparation

    asyncio.run(run())


def test_relative_shift_rejects_signed_and_fractional_ambiguity():
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    for text in ["전체 -30분 미뤄줘", "전체 1.5시간 미뤄줘"]:
        result = analyze(text, {}, plan, [], date(2026, 10, 27))
        assert result.plan is None and "몇 분" in result.reply


@pytest.mark.parametrize(
    "text", ["1번과 2번 시간을 14:00, 16:00로 바꿔줘", "1번과 2번 시간을 25:00, 15:00로 바꿔줘"]
)
def test_multiple_different_or_invalid_clocks_are_never_collapsed_into_one(text):
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    before = plan.model_dump()
    result = analyze(text, {}, plan, [], date(2026, 10, 27))
    assert result.plan is None and "활동별 시간" in result.reply
    assert plan.model_dump() == before


def test_existing_twenty_activity_contract_remains_bounded_in_small_context():
    plan = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    plan.activities = [plan.activities[0].model_copy(deep=True) for _ in range(20)]
    result = analyze("전체 10분 미뤄줘", {}, plan, [], date(2026, 10, 27))
    assert len(result.plan.activities) == 20 and all(
        a.time == "14:10" for a in result.plan.activities
    )
    assert len(StoredContext.model_validate(merge_context({}, {}, result)).activities) == 8


def test_old_writer_cannot_resume_a_stale_compound_operation():
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4

    import httpx
    from dialogue_evaluation import MemoryStore

    from we2day_api.ai_planner import ChatInput, _chat
    from we2day_api.ai_runtime import Budget, RunStats

    async def run():
        case = copy.deepcopy(CORPUS["cases"][0])
        case["initial"]["context"]["activity_edit"] = {"operation": "swap", "turn_version": 1}
        store = MemoryStore(case)
        store.version = 2

        def model(request):
            assert '"operation": "swap"' not in request.content.decode()
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"reply": "변경할 내용을 알려주세요."})}}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
            result = await _chat(
                ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": "첫 번째와 두 번째야"}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                        "version": 2,
                    }
                ),
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                store,
                client,
                Budget(),
                RunStats("synthetic"),
            )
        assert result.plan is None and result.context.activity_edit is None

    asyncio.run(run())
