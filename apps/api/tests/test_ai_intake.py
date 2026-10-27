import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import ControlledTools, MemoryStore
from pydantic import ValidationError

from we2day_api import ai_planner
from we2day_api.ai_dialogue import merge_context
from we2day_api.ai_intake import PlanningBrief, change_window, start_brief, window_checks
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import ModelAnswer, ModelPlan, StoredContext, ToolSession
from we2day_api.plans import PlanContent

BRIEF = dict(
    date="2030-01-05",
    start_time="13:00",
    end_time="19:00",
    region="중랑구",
    transport="도보",
    activities=["도서관", "카페"],
    budget=0,
    requirements="걷기 적게",
)


@pytest.mark.parametrize(
    "patch",
    [
        {"date": "2030-02-30"},
        {"date": "1999-01-01"},
        {"end_time": "13:00"},
        {"start_time": "25:00"},
        {"budget": True},
        {"budget": -1},
        {"budget": "100"},
        {"activities": []},
        {"recommend": True},
        {"activities": ["카페", "카페"]},
        {"activities": [" "]},
        {"permissions": ["read-all"]},
        {"model": "other"},
    ],
)
def test_strict_brief_rejects_ambiguous_or_privileged_input(patch):
    with pytest.raises(ValidationError):
        PlanningBrief.model_validate({**BRIEF, **patch})


def test_unknowns_recommendation_and_canonical_message():
    brief = PlanningBrief(region=" 성수동 ", recommend=True)
    assert brief.date is brief.budget is brief.start_time is brief.end_time is None
    assert brief.message() == "\n".join(
        [
            "입력한 조건으로 장소 후보만 찾아줘. 날짜는 미정이야.",
            "날짜: 미정",
            "시간대: 미정 ~ 미정",
            "지역: 성수동",
            "이동수단: 미정",
            "활동: 자유롭게 추천",
            "예산: 미정",
            "추가 조건: 없음",
        ]
    )


def test_structured_input_only_first_turn_and_explicit_location():
    payload = {"messages": [{"role": "user", "content": "조건"}], "brief": BRIEF}
    assert ai_planner.ChatInput.model_validate(payload).brief.budget == 0
    for patch in [
        {"version": 1},
        {"messages": payload["messages"] * 2},
        {"brief": {**BRIEF, "region": ""}},
        {"chosen_places": [{"title": "집"}]},
    ]:
        with pytest.raises(ValidationError):
            ai_planner.ChatInput.model_validate({**payload, **patch})
    assert ai_planner.ChatInput.model_validate(
        {
            **payload,
            "brief": {**BRIEF, "region": ""},
            "selected_places": [{"source": "favorite", "id": str(uuid4())}],
        }
    ).brief


def test_server_conditions_win_over_model_defaults_and_control_state_is_not_model_input():
    brief = PlanningBrief.model_validate(BRIEF)
    directive = start_brief(brief, {})
    context = merge_context(
        {},
        {
            "date": "2031-01-01",
            "budget": 10000,
            "activities": ["영화"],
            "region": "성수",
            "intake": {"data": {}},
        },
        directive,
    )
    stored = StoredContext.model_validate(context)
    assert stored.date == brief.date and stored.budget == 0
    assert stored.activities == brief.activities and stored.region == "중랑구"
    assert stored.intake.data == brief
    with pytest.raises(ValidationError):
        ModelAnswer.model_validate({"reply": "시도", "context": context})


def test_unknown_date_and_conflicting_activities_are_not_a_plan():
    brief = PlanningBrief.model_validate({**BRIEF, "date": None})
    directive = start_brief(brief, {})
    assert directive.intent == "search" and directive.scope.search_only
    assert directive.state.cleared_date
    conflict = start_brief(PlanningBrief.model_validate({**BRIEF, "requirements": "카페 제외"}), {})
    assert conflict.reply and conflict.intent == "clarify" and not conflict.allowed_tools


def test_window_change_is_atomic_pending_can_reload_and_cancel():
    initial = merge_context({}, {}, start_brief(PlanningBrief.model_validate(BRIEF), {}))
    original = copy.deepcopy(initial)
    first = change_window("종료 시간 바꿔줘", initial)
    pending = StoredContext.model_validate(merge_context(initial, {}, first)).model_dump()
    assert pending["intake"]["pending"] == "end_time"
    invalid = change_window("12:00", pending)
    invalid_context = merge_context(pending, {}, invalid)
    assert invalid_context["intake"]["data"]["end_time"] == "19:00"
    changed = change_window("20:00", json.loads(json.dumps(invalid_context)))
    assert changed.slots["intake"]["data"]["end_time"] == "20:00"
    assert changed.slots["intake"]["pending"] is None
    cancelled = change_window("취소해줘", pending)
    assert cancelled.slots["intake"]["pending"] is None
    assert change_window("카페 검색해줘", pending) is None
    assert initial == original and changed.plan is None


def test_known_activity_times_only_are_checked_against_window():
    plan = PlanContent(
        title="예시",
        date=BRIEF["date"],
        activities=[
            {"title": "하나", "time": "12:00"},
            {"title": "둘", "time": None},
            {"title": "셋", "time": "20:00"},
        ],
    )
    stored = StoredContext.model_validate(
        merge_context({}, {}, start_brief(PlanningBrief.model_validate(BRIEF), {}))
    )
    before = plan.model_dump()
    assert len(window_checks(plan, stored.intake)) == 2 and plan.model_dump() == before


def test_generated_schema_activity_cap_and_guard_order_no_invented_time_cost():
    schema = ai_planner.answer_format(BRIEF["date"], 2)["json_schema"]["schema"]
    assert schema["$defs"]["ModelPlan"]["properties"]["activities"]["maxItems"] == 2
    assert "intake" not in json.dumps(schema)
    session = ToolSession(SimpleNamespace(), None, [], [])
    session.operation, session.activity_limit = "plan", 2
    session.initial_activities = ["도서관", "카페"]
    library = session.add("샘플도서관", "공공 주소1", "naver")
    cafe = session.add("샘플카페", "공공 주소2", "naver")
    session.candidate_kinds = {library.ref: "library", cafe.ref: "cafe"}
    plan = ModelPlan(
        title="하루",
        date=BRIEF["date"],
        activities=[
            {"title": "도서관", "place_ref": library.ref, "time": "14:00", "cost": 1000},
            {"title": "카페", "place_ref": cafe.ref, "time": "16:00", "cost": 5000},
        ],
    )
    valid, checks = session.guard_plan(plan, session.resolve(plan))
    assert valid and not checks and all(a.time is a.cost is None for a in valid.activities)
    plan.activities.reverse()
    assert session.guard_plan(plan, session.resolve(plan))[0] is None
    plan.activities.pop()
    assert session.guard_plan(plan, session.resolve(plan))[0] is None


def test_full_turn_canonical_input_receipt_preserves_conditions_no_business_write(monkeypatch):
    async def run():
        brief = PlanningBrief.model_validate(BRIEF)
        store = MemoryStore({"initial": {}})
        original = store.rpc
        calls = []

        async def rpc(name, values=None):
            calls.append((name, values))
            return await original(name, values)

        store.rpc = rpc

        async def complete(settings, messages, session, **kwargs):
            assert messages[-1]["content"] == brief.message()
            assert session.initial_activities == brief.activities
            assert session.direct_final and len(session.searches) == 2
            assert set(session.candidate_kinds.values()) == {"library", "cafe"}
            return ai_planner.ChatResult(reply="확인했어요.")

        monkeypatch.setattr(ai_planner, "complete", complete)
        monkeypatch.setattr(ai_planner, "ToolIO", ControlledTools)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Network"))
        ) as client:
            result = await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "brief": BRIEF,
                        "messages": [{"role": "user", "content": "모순된 원문"}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                    }
                ),
                SimpleNamespace(),
                store,
                client,
                Budget(),
                RunStats("synthetic"),
            )
        assert result.context.intake.data == brief and result.context.budget == 0
        assert calls[0][1]["p_user"] == calls[-1][1]["p_user"] == brief.message()
        assert [v[0] for v in calls] == [
            "begin_ai_planner_turn",
            "reserve_ai_planner_request",
            "finish_ai_planner_turn",
        ]

    asyncio.run(run())


def test_restored_window_short_answer_uses_server_only_and_stale_pending_cannot_resume():
    async def run():
        context = merge_context({}, {}, start_brief(PlanningBrief.model_validate(BRIEF), {}))
        store = MemoryStore({"initial": {"context": context}})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No model"))
        ) as client:
            for text in ["종료 시간 바꿔줘", "20:00"]:
                result = await ai_planner._chat(
                    ai_planner.ChatInput.model_validate(
                        {
                            "messages": [{"role": "user", "content": text}],
                            "version": store.version,
                            "conversation_id": str(uuid4()),
                            "request_id": str(uuid4()),
                        }
                    ),
                    SimpleNamespace(),
                    store,
                    client,
                    Budget(),
                    RunStats("synthetic"),
                )
                store.context = json.loads(json.dumps(store.context))
        assert result.context.intake.data.end_time == "20:00" and result.plan is None

    asyncio.run(run())


def test_legacy_fingerprint_matches_previous_deployed_v8_image():
    import hashlib

    vectors = [
        {"messages": [{"role": "user", "content": "중랑구 도서관 후보만 찾아줘"}]},
        {
            "consent": True,
            "messages": [{"role": "user", "content": "도서관"}],
            "conversation_id": "11111111-1111-4111-8111-111111111111",
            "request_id": "22222222-2222-4222-8222-222222222222",
            "version": 7,
            "selected_places": [
                {"source": "favorite", "id": "33333333-3333-4333-8333-333333333333"}
            ],
            "chosen_places": [{"title": "샘플도서관", "address": "합성 주소"}],
        },
    ]
    expected = [
        "0c5737f13ba86914cff322ff9763087f10d48581724e5d42feb41747f1711858",
        "7c0c752c98a4c8ab3a3014a3837b3384a25a3690e6d757a25a9a577b58762a03",
    ]
    assert [
        hashlib.sha256(
            ai_planner.ChatInput.model_validate(v).model_dump_json(exclude={"brief"}).encode()
        ).hexdigest()
        for v in vectors
    ] == expected


def test_multiple_window_values_do_not_select_first_and_explicit_unknown_clears():
    context = merge_context({}, {}, start_brief(PlanningBrief.model_validate(BRIEF), {}))
    changed = change_window("종료 시간 18:00 또는 20:00", context)
    assert changed.slots["intake"]["data"]["end_time"] == "19:00"
    assert changed.slots["intake"]["pending"] == "end_time"
    cleared = change_window("종료 시간은 미정", context)
    assert cleared.slots["intake"]["data"]["end_time"] is None


def test_stale_pending_from_older_writer_is_cleared_before_model(monkeypatch):
    async def run():
        context = merge_context({}, {}, start_brief(PlanningBrief.model_validate(BRIEF), {}))
        context["intake"].update(pending="end_time", turn_version=1)
        store = MemoryStore({"initial": {"context": context}})
        store.version = 5

        async def complete(settings, messages, session, **kwargs):
            return ai_planner.ChatResult(reply="시간 변경 대상을 알려주세요.")

        monkeypatch.setattr(ai_planner, "complete", complete)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Network"))
        ) as client:
            result = await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": "20:00"}],
                        "version": 5,
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                    }
                ),
                SimpleNamespace(),
                store,
                client,
                Budget(),
                RunStats("synthetic"),
            )
        assert result.context.intake.pending is None
        assert result.context.intake.data.end_time == "19:00"

    asyncio.run(run())
