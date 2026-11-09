"""Current capability runtime transitions, not legacy routing or model accuracy."""

import asyncio
import copy
import json
import random

import httpx
import pytest
from test_ai_capabilities import Flow, native

from we2day_api import ai_planner
from we2day_api.places import SearchResults
from we2day_api.plans import PlanContent

DAY = "2030-06-15"
AREA = "샘플시 예시로"
ADDRESS = "경기도 샘플시 예시로 42"
PLAN = PlanContent(
    title="기존 코스",
    date=DAY,
    activities=[{"title": "기준 장소", "place": f"기준 장소 ({ADDRESS})"}],
).model_dump()


def runtime(monkeypatch, *, context=None, proposal=None, failed=False):
    flow = Flow(
        monkeypatch,
        context=context if context is not None else {"date": DAY, "region": AREA},
        proposal=proposal,
    )
    flow.fail_selected = failed
    flow.weather_error = None
    flow.selected_label = "기준 장소"

    class IO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            flow.queries.append(action)
            if action[0] == "data":
                if flow.fail_selected:
                    raise httpx.ConnectError("synthetic unavailable")
                return [{"id": flow.selected, "label": flow.selected_label, "destination": ADDRESS}]
            if action[0] == "weather":
                if flow.weather_error:
                    return {"error": flow.weather_error}
                return {
                    "forecast": {
                        "city": "서울",
                        "date": "2026-11-06",
                        "min_celsius": 5.0,
                        "max_celsius": 12.0,
                        "rain_probability_percent": 20.0,
                    }
                }
            assert action[0] == "places"
            target = action[1].replace(AREA, "").strip()
            return SearchResults.model_validate(
                {
                    "items": [
                        {
                            "title": f"합성 {target}",
                            "category": target,
                            "roadAddress": "경기도 샘플시 예시로 60",
                        }
                    ]
                }
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    return flow


def question(field="target", resume="plan"):
    return {
        "date": DAY,
        "region": AREA,
        "dialogue": {
            "turn_version": 0,
            "pending": {"field": field, "resume": resume},
        },
    }


@pytest.mark.parametrize("selection", ["search_places", "continue_planning"])
@pytest.mark.parametrize("usage", ["anchor", "include"])
@pytest.mark.parametrize("proposal", [False, True])
def test_reselected_identity_keeps_its_explicit_role_after_existing_course_seed(
    monkeypatch, usage, proposal, selection
):
    flow = runtime(monkeypatch, proposal=copy.deepcopy(PLAN) if proposal else None)
    result = asyncio.run(
        flow.send(
            "근처 카페 찾아줘",
            (
                selection,
                {
                    "query": "카페",
                    "targets": ["카페"],
                    "area": AREA,
                }
                if selection == "search_places"
                else {},
            ),
            selected=[{"source": "favorite", "id": flow.selected, "usage": usage}],
        )
    )
    assert result.candidates and any(a[0] == "places" for a in flow.queries)
    assert any(a[0] == "data" for a in flow.queries)
    assert "현재 목록에서 확인할 수 없어요" not in result.reply
    assert flow.store.proposal == (PLAN if proposal else None)


@pytest.mark.parametrize("target", ["수영장", "전망대", "먹을거"])
def test_fresh_language_search_cannot_reuse_the_last_selected_exact_name(monkeypatch, target):
    flow = runtime(
        monkeypatch,
        proposal=copy.deepcopy(PLAN),
        context={
            "date": DAY,
            "region": AREA,
            "search_scope": {"area": AREA, "exact_name": "기준 장소"},
        },
    )
    action = {"operation": "search", "area": AREA, "targets": [target]}
    interpreted = httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(action, ensure_ascii=False)}}]}
    )
    result = asyncio.run(
        flow.send(
            f"{target} 추천좀 해줘",
            responses=[
                native(("continue_planning", {})),
                interpreted,
            ],
        )
    )
    assert result.candidates
    assert any(
        a[0] == "places" and target in a[1] and "기준 장소" not in a[1] for a in flow.queries
    )
    assert flow.store.proposal == PLAN


SIDE_TASKS = [
    ("저장된 오늘 공동 약속 알려줘", ("read_shared_calendar", {"date": "2026-11-06"})),
    ("저장한 산책 플랜 보여줘", ("read_shared_plan", {"title": "산책"})),
    ("지금 코스 입력 상태 점검해줘", ("validate_course", {})),
    ("저장해줘", ("ask_user", {"field": "save"})),
    ("사진도 보여줘", ("ask_user", {"field": "unsupported"})),
    ("서울 2026-11-06 날씨 알려줘", ("get_weather", {"city": "서울", "date": "2026-11-06"})),
]


@pytest.mark.parametrize(
    "field,resume", [("target", "plan"), ("date", "plan"), ("region", "search")]
)
@pytest.mark.parametrize(
    "side", SIDE_TASKS, ids=["calendar", "saved_plan", "check", "save", "unsupported", "weather"]
)
def test_server_side_answer_does_not_expire_the_unanswered_question(
    monkeypatch, field, resume, side
):
    flow = runtime(monkeypatch, context=question(field, resume))
    result = asyncio.run(flow.send(side[0], side[1]))
    pending = result.context.dialogue.pending
    assert pending and (pending.field, pending.resume) == (field, resume)
    assert result.context.dialogue.turn_version == flow.store.version
    assert result.context.date == DAY and result.context.region == AREA


@pytest.mark.parametrize("usage", ["anchor", "include"])
def test_failed_selected_read_preserves_plan_purpose_and_is_not_a_location_question(
    monkeypatch, usage
):
    flow = runtime(
        monkeypatch, context={"date": DAY, "region": AREA, "activities": ["카페"]}, failed=True
    )
    result = asyncio.run(
        flow.send(
            "카페 코스 만들어줘",
            (
                "propose_course",
                {
                    "operation": "plan",
                    "area": AREA,
                    "targets": ["카페"],
                },
            ),
            selected=[{"source": "favorite", "id": flow.selected, "usage": usage}],
        )
    )
    assert result.context.control["outcome"] == "failed"
    assert result.context.control["last_action"]["operation"] == "plan"
    assert not result.context.location_request and not result.context.dialogue.pending
    assert flow.store.proposal is None


def test_native_clarification_has_a_typed_question_and_accepts_a_bare_date(monkeypatch):
    flow = runtime(monkeypatch, context={"region": AREA})

    async def run():
        first = await flow.send("새 데이트 코스 만들어줘", ("ask_user", {"field": "date"}))
        assert first.context.dialogue.pending.field == "date"
        assert first.context.dialogue.pending.resume == "plan"
        flow.history = []  # Browser reload must not lose the current question.
        result = await flow.send(DAY)
        assert result.context.date == DAY
        assert result.context.dialogue.pending.field == "target"
        assert result.context.dialogue.pending.resume == "plan"
        assert flow.stats[-1]["model_calls"] == 0 and not flow.queries

    asyncio.run(run())


@pytest.mark.parametrize("seed", [13, 37, 83])
def test_current_runtime_keeps_question_across_long_side_tasks_reload_and_activity_answer(
    monkeypatch, seed
):
    from we2day_api.ai_tools import ModelPlan

    flow = runtime(monkeypatch, context=question())

    async def completion(settings, messages, session, **kwargs):
        assert session.require_plan and session.plan_date == DAY
        assert session.requested_activities == ["카페"]
        candidates = session.visible_candidates()
        assert candidates
        model = ModelPlan(
            title="합성 코스",
            date=DAY,
            activities=[{"title": "카페", "place_ref": candidates[0].ref}],
        )
        plan, issues = session.guard_plan(model, session.resolve(model))
        assert plan and not issues
        return ai_planner.ChatResult(reply="코스 초안", plan=plan)

    monkeypatch.setattr(ai_planner, "complete", completion)

    async def run():
        rng = random.Random(seed)
        # Pure server-side tasks avoid involving the completion stub until the answer.
        for turn in range(42):
            text, call = rng.choice(SIDE_TASKS[:-1])
            result = await flow.send(text, call)
            assert result.context.dialogue.pending.field == "target"
            assert result.context.dialogue.pending.resume == "plan"
            assert result.context.dialogue.turn_version == flow.store.version
            assert result.context.date == DAY and result.context.region == AREA
            assert not result.plan and not flow.queries
            if turn % 7 == 0:
                flow.history = []
        result = await flow.send("카페")
        assert result.plan and result.plan.date == DAY
        assert len(result.plan.activities) == 1
        assert flow.stats[-1]["model_calls"] == 0

    asyncio.run(run())


def test_weather_and_search_dates_are_read_parameters_not_course_date_edits(monkeypatch):
    flow = runtime(
        monkeypatch,
        proposal=copy.deepcopy(PLAN),
        context={
            "date": DAY,
            "region": AREA,
        },
    )
    result = asyncio.run(
        flow.send(
            "서울 2026-11-06 날씨랑 샘플시 예시로 카페 찾아줘",
            ("get_weather", {"city": "서울", "date": "2026-11-06"}),
            ("search_places", {"query": "카페", "targets": ["카페"], "area": AREA}),
        )
    )
    assert result.context.date == DAY and flow.store.proposal == PLAN
    assert result.candidates
    assert result.weather and result.weather[0].date == "2026-11-06"
    assert "2026-11-06" in result.reply and "5°C" in result.reply and "카페" in result.reply


@pytest.mark.parametrize("delta", [-1, 0, 1])
@pytest.mark.parametrize("field", ["date", "region", "target", "title", "budget", "transport"])
def test_versioned_continuation_projection_keeps_facts_and_never_mutates_loaded_state(delta, field):
    from we2day_api.ai_state import advance_context, current_context

    before = question(field, "plan")
    before.update(budget=0, transport="", requirements="", activities=["카페"])
    before["dialogue"]["turn_version"] = 7 + delta
    before["location_request"] = {"basis": 7 + delta, "scope": {"kinds": ["cafe"]}}
    original = copy.deepcopy(before)
    current = current_context(before, 7)
    advanced = advance_context(current, 7)
    for key in ["date", "region", "budget", "transport", "requirements", "activities"]:
        assert advanced[key] == before[key]
    if delta == 0:
        assert advanced["dialogue"]["pending"]["field"] == field
        assert advanced["dialogue"]["turn_version"] == advanced["location_request"]["basis"] == 8
    else:
        assert not advanced["dialogue"]["pending"] and not advanced["location_request"]
    assert before == original


@pytest.mark.parametrize(
    "title", ["2020-06-15 코스", "2020년 6월 15일 데이트", "2020년6월15일 나들이"]
)
@pytest.mark.parametrize("owner", ["model", "user", "existing"])
def test_generated_date_labels_are_checked_without_renaming_explicit_or_existing_titles(
    title, owner
):
    from we2day_api.ai_plan_metadata import generated_title

    text = f"제목은 ‘{title}’로 해줘" if owner == "user" else "새 코스를 만들어줘"
    actual = generated_title(title, DAY, text, existing=owner == "existing")
    if owner == "model":
        assert "2030" in actual and "2020" not in actual
    else:
        assert actual == title


@pytest.mark.parametrize("usage", ["anchor", "include"])
@pytest.mark.parametrize("field", ["target", "date", "region"])
def test_selected_place_read_does_not_turn_an_open_question_into_a_course(
    monkeypatch, usage, field
):
    flow = runtime(monkeypatch, context=question(field))
    result = asyncio.run(
        flow.send(
            "지금 체크한 장소 목록 보여줘",
            ("lookup_selected_places", {}),
            selected=[{"source": "favorite", "id": flow.selected, "usage": usage}],
        )
    )
    assert result.context.dialogue.pending.field == field
    assert result.context.dialogue.turn_version == flow.store.version
    assert result.context.date == DAY and result.plan is None
    assert flow.queries and all(q[0] == "data" for q in flow.queries)


@pytest.mark.parametrize(
    "text",
    [
        "2030년 6월 15일에 2020년 6월 15일의 첫 만남을 기념할 거야",
        "2020-06-15 추억을 기념하는 코스는 날짜를 2030-06-15로 정해줘",
    ],
)
def test_user_supplied_historical_dates_are_not_misclassified_as_generated_errors(text):
    from we2day_api.ai_plan_metadata import generated_title

    title = "2020년 6월 15일 기념 코스"
    assert generated_title(title, DAY, text) == title


@pytest.mark.parametrize("proposal", [False, True])
@pytest.mark.parametrize(
    "text,key,value",
    [
        ("날짜는 2030-06-20로 바꿔줘", "date", "2030-06-20"),
        ("날짜는 미정으로 바꿔줘", "date", None),
        ("예산은 미정으로 바꿔줘", "budget", None),
        ("예산은 0원으로 바꿔줘", "budget", 0),
        ("이동수단은 미정으로 바꿔줘", "transport", ""),
        ("추가 조건은 없음으로 바꿔줘", "requirements", ""),
        ("지역은 성수동으로 바꿔줘", "region", "성수동"),
    ],
)
def test_current_capability_runtime_keeps_explicit_conditions_and_clears(
    monkeypatch, proposal, text, key, value
):
    from test_ai_long_dialogue import BRIEF
    from test_ai_long_dialogue import PLAN as TIMED_PLAN

    from we2day_api.ai_dialogue import merge_context
    from we2day_api.ai_intake import PlanningBrief, start_brief

    context = merge_context({}, {}, start_brief(PlanningBrief(**BRIEF), {}))
    flow = runtime(
        monkeypatch, context=context, proposal=copy.deepcopy(TIMED_PLAN) if proposal else None
    )
    result = asyncio.run(flow.send(text, ("continue_planning", {})))
    assert getattr(result.context, key) == value
    assert getattr(result.context.intake.data, key) == value
    if proposal:
        assert flow.store.proposal["activities"] == TIMED_PLAN["activities"]
        assert flow.store.proposal["preparation"] == TIMED_PLAN["preparation"]
    assert not flow.queries


@pytest.mark.parametrize(
    "side", SIDE_TASKS, ids=["calendar", "plan", "check", "save", "unsupported", "weather"]
)
@pytest.mark.parametrize(
    "edit_request,answer,expected",
    [
        ("예산 바꿔줘", "3만원", "budget"),
        ("제목 바꿔줘", "새로운 제목", "title"),
        ("첫 번째 활동을 미뤄줘", "30분", "activity_time"),
        ("종료 시간 바꿔줘", "20:00", "end_time"),
    ],
)
def test_read_side_tasks_preserve_all_edit_controllers_until_the_answer(
    monkeypatch, side, edit_request, answer, expected
):
    from test_ai_long_dialogue import BRIEF
    from test_ai_long_dialogue import PLAN as TIMED_PLAN

    from we2day_api.ai_dialogue import merge_context
    from we2day_api.ai_intake import PlanningBrief, start_brief

    context = merge_context({}, {}, start_brief(PlanningBrief(**BRIEF), {}))
    flow = runtime(monkeypatch, context=context, proposal=copy.deepcopy(TIMED_PLAN))

    async def run():
        await flow.send(edit_request, ("continue_planning", {}))
        await flow.send(side[0], side[1])
        flow.history = []
        result = await flow.send(answer, ("continue_planning", {}))
        if expected == "budget":
            assert result.plan and result.plan.budget == 30000
        elif expected == "title":
            assert result.plan and result.plan.title == answer
        elif expected == "activity_time":
            assert result.plan and result.plan.activities[0].time == "14:30"
        else:
            assert result.context.intake.data.end_time == answer
        assert not flow.queries or all(a[0] == "weather" for a in flow.queries)

    asyncio.run(run())


@pytest.mark.parametrize("usage", ["anchor", "include"])
def test_cancellation_and_retry_do_not_restart_a_selected_place_task(monkeypatch, usage):
    flow = runtime(monkeypatch, proposal=copy.deepcopy(PLAN))

    async def run():
        selected = [{"source": "favorite", "id": flow.selected, "usage": usage}]
        await flow.send(
            "카페 찾아줘",
            ("search_places", {"query": "카페", "targets": ["카페"], "area": AREA}),
            selected=selected,
        )
        count = len(flow.queries)
        await flow.send("검색 취소해줘", selected=selected)
        result = await flow.send("다시", ("continue_planning", {}), selected=selected)
        assert len(flow.queries) == count and result.plan is None
        assert not result.context.control.get("last_action")
        assert flow.store.proposal == PLAN

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["forecast_out_of_range", "city_not_found", "weather_unavailable"]
)
def test_partial_weather_failure_is_visible_beside_successful_search_results(monkeypatch, failure):
    flow = runtime(monkeypatch)
    flow.weather_error = failure
    result = asyncio.run(
        flow.send(
            "서울 2026-11-06 날씨랑 샘플시 예시로 카페 찾아줘",
            ("get_weather", {"city": "서울", "date": "2026-11-06"}),
            ("search_places", {"query": "카페", "targets": ["카페"], "area": AREA}),
        )
    )
    assert result.candidates and not result.weather
    assert "날씨" in result.reply and ("못했어요" in result.reply or "확인" in result.reply)
    assert any(t["name"] == "get_weather" and t["status"] == "failed" for t in result.tools)
    assert result.context.date == DAY


def test_selected_read_reply_is_not_exported_after_selection_is_cleared(monkeypatch):
    flow = runtime(monkeypatch)
    flow.selected_label = "PRIVATE SELECTED LOCATION"

    async def run():
        first = await flow.send(
            "체크한 장소 목록 보여줘",
            ("lookup_selected_places", {}),
            selected=[{"source": "favorite", "id": flow.selected, "usage": "include"}],
        )
        assert "PRIVATE SELECTED LOCATION" in first.reply
        assert flow.stats[-1]["model_calls"] == 1
        # The next model receives neither selected IDs nor the server-rendered address list.
        await flow.send("데이트 준비에 대해 이야기하자", ("continue_planning", {}))
        assert all("PRIVATE SELECTED LOCATION" not in json.dumps(m) for m in flow.models)

    asyncio.run(run())


@pytest.mark.parametrize("parts", [2, 3, 4])
def test_bounded_compound_answer_keeps_each_requested_task_and_discloses_partial_display(parts):
    from we2day_api.ai_read_answers import join_replies

    values = [f"TASK {index}\n" + str(index) * 2500 for index in range(parts)]
    result = join_replies(values)
    assert len(result) <= 4000
    assert all(f"TASK {index}\n" in result for index in range(parts))
    assert result.count("일부 내용만 표시") == parts


@pytest.mark.parametrize(
    "title", ["새로운 제목", "2020년 6월 15일 첫 만남", "자동차 산책 코스", "‘예산 5만원’"]
)
def test_literal_title_answer_cannot_change_dates_budgets_transport_or_activity_scope(
    monkeypatch, title
):
    flow = runtime(
        monkeypatch,
        proposal=copy.deepcopy(PLAN),
        context={
            **question("title", "edit"),
            "budget": 50000,
            "transport": "도보",
        },
    )
    result = asyncio.run(flow.send(title, ("continue_planning", {})))
    assert result.plan
    assert result.plan.title == title.strip("‘’")
    for field in ["date", "activities", "preparation"]:
        assert result.plan.model_dump()[field] == PLAN[field]
    assert result.context.budget == 50000 and result.context.transport == "도보"
