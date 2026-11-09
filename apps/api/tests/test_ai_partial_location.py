"""Incomplete planning answers and selected city/road addresses, with synthetic places."""

import asyncio

import pytest
from test_ai_capabilities import Flow

from we2day_api import ai_planner
from we2day_api.ai_dialogue import planning_request
from we2day_api.ai_place_answers import address_area
from we2day_api.places import SearchResults
from we2day_api.plans import PlanContent


def selected_flow(monkeypatch, context=None, destination="경기도 샘플시 예시로 42"):
    flow = Flow(monkeypatch, context=context)

    class IO:
        def __init__(self, *args):
            pass

        async def perform(self, action):
            flow.queries.append(action)
            if action[0] == "data":
                assert action[1] == "favorite_places" and action[2]["id"] == f"in.({flow.selected})"
                return [
                    {"id": flow.selected, "label": "고른 기준 장소", "destination": destination}
                ]
            assert action[0] == "places"
            return SearchResults.model_validate(
                {
                    "items": [
                        {
                            "title": "합성 카페",
                            "category": "카페,디저트",
                            "roadAddress": "경기도 샘플시 예시로 60",
                        }
                    ]
                }
            )

    monkeypatch.setattr(ai_planner, "ToolIO", IO)
    return flow


@pytest.mark.parametrize(
    "address,expected",
    [
        ("경기도 샘플시 예시로 42", "샘플시 예시로"),
        ("세종특별자치시 도움로 42", "세종특별자치시 도움로"),
        ("강원특별자치도 샘플군 새길 11", "샘플군 새길"),
        ("서울특별시 중랑구 신내동 1", "중랑구 신내동"),
        ("샘플시", "샘플시"),
        ("https://naver.me/Example12", ""),
    ],
)
def test_selected_locality_uses_only_public_city_and_road_without_building_number(
    address, expected
):
    assert address_area(address, allow_road=True) == expected
    if "예시로" in address:
        assert address_area(address) == "샘플시"


@pytest.mark.parametrize(
    "text", ["2030년 6월 15일에 데이트 일정 잡아줘", "주말 약속을 잡아줘", "새 코스 만들어줘"]
)
def test_planning_request_variants(text):
    assert planning_request(text)


@pytest.mark.parametrize(
    "text", ["오늘 무슨 약속 잡혀 있어?", "코스 아직 만들지 마", "저장한 일정 보여줘"]
)
def test_saved_reads_and_negation_are_not_new_plans(text):
    assert not planning_request(text)


def test_date_only_proposal_asks_for_missing_activities_and_preserves_plan_operation(monkeypatch):
    flow = selected_flow(monkeypatch)
    result = asyncio.run(
        flow.send(
            "2030년 6월 15일에 데이트 일정 잡아줘",
            ("propose_course", {"operation": "plan", "area": "", "targets": []}),
        )
    )
    assert result.context.date == "2030-06-15" and result.context.dialogue.pending.field == "target"
    assert result.context.dialogue.pending.resume == "plan" and not result.context.location_request
    assert not flow.queries and result.plan is None


def test_legacy_location_answer_keeps_date_and_asks_activity_instead_of_repeating_location(
    monkeypatch,
):
    context = {
        "date": "2030-06-15",
        "location_request": {
            "version": 1,
            "basis": 0,
            "operation": "search",
            "scope": {},
            "search": None,
        },
    }
    flow = selected_flow(monkeypatch, context)
    flow.history = [
        {"role": "user", "content": "2030년 6월 15일에 데이트 일정 잡아줘"},
        {"role": "assistant", "content": "어느 지역인가요?"},
    ]
    result = asyncio.run(
        flow.send(
            "선택한 장소 주변에서 찾아줘.",
            selected=[{"source": "favorite", "id": flow.selected, "usage": "anchor"}],
        )
    )
    assert result.context.date == "2030-06-15" and result.context.region == "샘플시 예시로"
    assert (
        result.context.dialogue.pending.field == "target"
        and result.context.dialogue.pending.resume == "plan"
    )
    assert "활동" in result.reply and "동네를 확인할 수 없어요" not in result.reply
    assert len(flow.queries) == 1 and not flow.models
    assert "42" not in result.context.region and not result.context.location_request


def test_selected_city_road_searches_real_target_without_neighborhood_retry_loop(monkeypatch):
    flow = selected_flow(
        monkeypatch,
        {
            "date": "2030-06-15",
            "region": "",
            "activities": ["카페"],
            "location_request": {
                "version": 1,
                "basis": 0,
                "operation": "search",
                "scope": {"kinds": ["cafe"]},
                "search": {"targets": [{"kind": "cafe", "query": "카페"}]},
            },
        },
    )
    result = asyncio.run(
        flow.send(
            "선택한 장소 주변에서 찾아줘.",
            selected=[{"source": "favorite", "id": flow.selected, "usage": "anchor"}],
        )
    )
    assert result.candidates and not result.context.location_request
    searches = [a[1] for a in flow.queries if a[0] == "places"]
    assert searches and all("샘플시 예시로" in q and "42" not in q for q in searches)
    assert result.context.date == "2030-06-15"


def test_link_only_saved_place_is_not_treated_as_a_geocode(monkeypatch):
    flow = selected_flow(
        monkeypatch,
        {
            "activities": ["카페"],
            "location_request": {
                "version": 1,
                "basis": 0,
                "operation": "search",
                "scope": {"kinds": ["cafe"]},
                "search": {"targets": [{"kind": "cafe", "query": "카페"}]},
            },
        },
        destination="https://naver.me/Example12",
    )
    result = asyncio.run(
        flow.send(
            "선택한 장소 주변에서 찾아줘.",
            selected=[{"source": "favorite", "id": flow.selected, "usage": "anchor"}],
        )
    )
    assert not result.candidates and result.context.location_request
    assert not any(a[0] == "places" for a in flow.queries)


def test_literal_city_without_road_still_requires_a_more_precise_location(monkeypatch):
    context = {
        "activities": ["카페"],
        "location_request": {
            "version": 1,
            "basis": 0,
            "operation": "search",
            "scope": {"kinds": ["cafe"]},
            "search": {"targets": [{"kind": "cafe", "query": "카페"}]},
        },
    }
    flow = selected_flow(monkeypatch, context, destination="경기도 샘플시")
    result = asyncio.run(
        flow.send(
            "선택한 장소 주변에서 찾아줘.",
            selected=[{"source": "favorite", "id": flow.selected, "usage": "anchor"}],
        )
    )
    assert result.context.location_request and not result.candidates
    assert not any(a[0] == "places" for a in flow.queries)


def test_activity_answer_resumes_the_same_plan_with_the_selected_road_and_date(monkeypatch):
    context = {
        "date": "2030-06-15",
        "location_request": {
            "version": 1,
            "basis": 0,
            "operation": "search",
            "scope": {},
            "search": None,
        },
    }
    flow = selected_flow(monkeypatch, context)
    flow.history = [
        {"role": "user", "content": "2030년 6월 15일에 데이트 일정 잡아줘"},
        {"role": "assistant", "content": "어느 지역인가요?"},
    ]

    async def completion(settings, messages, session, **kwargs):
        assert session.require_plan and session.plan_date == "2030-06-15"
        assert session.requested_activities == ["카페"]
        assert any(a[0] == "places" for a in flow.queries)
        return ai_planner.ChatResult(
            reply="합성 코스 초안",
            plan=PlanContent(
                title="합성",
                date="2030-06-15",
                activities=[{"title": "카페", "place": "합성 카페"}],
            ),
        )

    monkeypatch.setattr(ai_planner, "complete", completion)

    async def run():
        selected = [{"source": "favorite", "id": flow.selected, "usage": "anchor"}]
        await flow.send("선택한 장소 주변에서 찾아줘.", selected=selected)
        result = await flow.send("카페", ("continue_planning", {}), selected=selected)
        assert result.plan and result.plan.date == "2030-06-15"
        assert result.context.region == "샘플시 예시로"
        assert not result.context.location_request

    asyncio.run(run())


@pytest.mark.parametrize("activity", ["카페", "식당"])
def test_search_selection_cannot_replace_the_pending_plan_purpose(monkeypatch, activity):
    from datetime import date

    from we2day_api.ai_capability_router import apply_selection
    from we2day_api.ai_control import prepare
    from we2day_api.ai_selection import Selection

    flow = selected_flow(monkeypatch)
    context = {
        "date": "2030-06-15",
        "region": "샘플시 예시로",
        "dialogue": {"turn_version": 0, "pending": {"field": "target", "resume": "plan"}},
    }
    body = ai_planner.ChatInput(messages=[{"role": "user", "content": activity}])
    decision = prepare(body, context, None, date(2030, 6, 1))
    selection = Selection(
        calls=[
            (
                "search_places",
                {
                    "query": activity,
                    "targets": [activity],
                    "area": "샘플시 예시로",
                    "mode": "category",
                    "name": "",
                },
            )
        ]
    )
    apply_selection(selection, decision, activity)
    assert decision.directive.intent == "plan"
    assert decision.directive.slots["activities"] == [activity]
    assert decision.directive.slots.get("date", context["date"]) == "2030-06-15"
    assert not flow.queries


@pytest.mark.parametrize("stale", [False, True])
def test_explicit_new_search_or_stale_question_never_generates_a_plan(monkeypatch, stale):
    flow = selected_flow(
        monkeypatch,
        {
            "date": "2030-06-15",
            "region": "샘플시 예시로",
            "dialogue": {
                "turn_version": 1 if stale else 0,
                "pending": {"field": "target", "resume": "plan"},
            },
        },
    )
    text = "카페" if stale else "카페 후보만 찾아줘"
    result = asyncio.run(
        flow.send(
            text,
            (
                "search_places",
                {
                    "query": "카페",
                    "targets": ["카페"],
                    "area": "샘플시 예시로",
                },
            ),
        )
    )
    assert result.plan is None
    if stale:
        assert (result.context.control.get("last_action") or {}).get("operation") != "plan"
    else:
        assert result.candidates
        assert result.context.control["last_action"]["operation"] == "search"
