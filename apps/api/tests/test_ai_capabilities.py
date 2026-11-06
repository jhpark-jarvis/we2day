"""Native function selection and real planner adapters, with controlled external I/O."""

import asyncio
import json
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore
from fastapi import HTTPException

from we2day_api import ai_planner
from we2day_api.ai_capabilities import (
    BY_NAME,
    CAPABILITIES,
    SESSION_NAMES,
    definitions,
    model_result,
)
from we2day_api.ai_capability_router import MODELS, selection_messages
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import TOOLS
from we2day_api.config import Settings
from we2day_api.places import SearchResults


def native(*calls):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": str(i),
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                            for i, (name, args) in enumerate(calls)
                        ]
                    }
                }
            ]
        },
    )


class Flow:
    def __init__(self, monkeypatch, context=None, proposal=None):
        class Clock:
            @classmethod
            def now(cls, zone):
                return datetime(2026, 11, 6, tzinfo=zone)

        monkeypatch.setattr(ai_planner, "datetime", Clock)
        self.store = MemoryStore({"initial": {"context": context or {}, "proposal": proposal}})
        self.history, self.models, self.queries, self.reads = [], [], [], []
        self.cid, self.selected = str(uuid4()), str(uuid4())
        self.appointments = [
            {
                "id": "a",
                "title": "PRIVATE SAVED TITLE",
                "kind": "shared",
                "date": "2026-11-06",
                "time": "19:00:00",
                "place": "PRIVATE ADDRESS",
            }
        ]
        self.plans, self.replies, self.stats = [], [], []
        self.failure = False
        flow = self

        async def read(method, table, params):
            assert method == "GET"
            flow.reads.append((table, params))
            if flow.failure:
                raise HTTPException(503, "PRIVATE ERROR")
            if table == "appointments":
                assert params["kind"] == "eq.shared"
                return [a for a in flow.appointments if "eq." + a["date"] == params["date"]]
            assert table == "date_plans"
            return flow.plans

        self.store.call = read

        class IO:
            def __init__(self, *args):
                pass

            async def perform(self, action):
                flow.queries.append(action)
                if action[0] == "places":
                    return SearchResults.model_validate(
                        {
                            "items": [
                                {
                                    "title": "성수 카페",
                                    "category": "카페,디저트",
                                    "roadAddress": "서울특별시 성동구 성수동 1",
                                }
                            ]
                        }
                    )
                if action[0] == "weather":
                    return {
                        "forecast": {
                            "city": "서울",
                            "date": "2026-11-06",
                            "min_celsius": 5.0,
                            "max_celsius": 12.0,
                            "rain_probability_percent": 20.0,
                        }
                    }
                if action[0] == "data":
                    assert action[1] == "favorite_places"
                    assert action[2]["id"] == "in.(" + flow.selected + ")"
                    return [{"id": flow.selected, "label": "선택 카페", "destination": "성수동"}]
                pytest.fail("Unexpected data operation")

        monkeypatch.setattr(ai_planner, "ToolIO", IO)

    async def send(self, text, *calls, status=None, selected=None):
        self.history.append({"role": "user", "content": text})
        self.replies = [status or native(*calls)]

        def provider(request):
            data = json.loads(request.content)
            self.models.append(data)
            assert "PRIVATE" not in json.dumps(data)
            if self.replies:
                return self.replies.pop(0)
            assert "response_format" in data
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"reply": "확인한 결과예요.", "plan": None})
                            }
                        }
                    ]
                },
            )

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
                    }
                ),
                Settings(_env_file=None, ai_capabilities_enabled=True),
                self.store,
                client,
                Budget(),
                stats,
            )
            self.stats.append(stats.counts)
        self.history.append({"role": "assistant", "content": result.reply})
        return result


def test_registry_schema_effect_and_executor_coverage():
    assert len(BY_NAME) == len(CAPABILITIES)
    assert len({c.id for c in CAPABILITIES}) == len(CAPABILITIES)
    assert {c.executor for c in CAPABILITIES} == {
        "schedule",
        "plan",
        "session",
        "planner",
        "clarify",
        "check",
    }
    assert set(MODELS) == {c.name for c in CAPABILITIES if c.exposed}
    assert {t["function"]["name"] for t in TOOLS} == SESSION_NAMES
    assert all(c.effect != "write" for c in CAPABILITIES)
    assert {t["function"]["name"] for t in definitions(MODELS, selected=False)} == set(MODELS) - {
        "lookup_selected_places"
    }
    with pytest.raises(ValueError):
        definitions(MODELS, {"arbitrary_sql"})
    with pytest.raises(ValueError):
        model_result("read_shared_calendar", {"items": ["PRIVATE"]})
    assert model_result("search_places", {"items": []})["status"] == "empty"
    assert model_result("search_places", {"error": "tool_unavailable"})["status"] == "unavailable"


@pytest.mark.parametrize(
    "text", ["오늘 뭐 잡혀 있어?", "오늘 어디 가기로 했지?", "11월 6일 약속 좀 훑어줘"]
)
def test_unfamiliar_calendar_phrases_use_actual_read(monkeypatch, text):
    flow = Flow(monkeypatch)
    r = asyncio.run(flow.send(text, ("read_shared_calendar", {"date": "2026-11-06"})))
    assert "PRIVATE SAVED TITLE" in r.reply and "PRIVATE ADDRESS" in r.reply
    assert flow.stats[-1]["model_calls"] == 1 and len(flow.reads) == 2
    assert r.plan is None and r.tools[0]["status"] == "ok"


def test_calendar_followup_and_then_search_never_export_business_reply(monkeypatch):
    flow = Flow(monkeypatch)

    async def run():
        await flow.send("오늘 뭐 잡혔어?", ("read_shared_calendar", {"date": "2026-11-06"}))
        r = await flow.send("그럼 내일은?", ("read_shared_calendar", {"date": "2026-11-07"}))
        assert "없어요" in r.reply
        r = await flow.send(
            "성수동 카페 후보 볼래",
            (
                "search_places",
                {"query": "카페", "area": "성수동", "kind": "cafe", "mode": "category"},
            ),
        )
        assert r.candidates and flow.queries and r.context.region == "성수동"

    asyncio.run(run())
    assert len(flow.reads) == 4 and len(flow.queries) == 1


def test_calendar_and_public_search_are_both_completed_without_private_projection(monkeypatch):
    flow = Flow(monkeypatch)
    r = asyncio.run(
        flow.send(
            "오늘 약속 보고 성수동 카페도 찾아줘",
            ("read_shared_calendar", {"date": "2026-11-06"}),
            (
                "search_places",
                {"query": "카페", "area": "성수동", "kind": "cafe", "mode": "category"},
            ),
        )
    )
    assert "PRIVATE SAVED TITLE" in r.reply and r.candidates
    assert {t["name"] for t in r.tools} == {"read_shared_schedule", "search_places"}


def test_search_location_question_preserves_original_target(monkeypatch):
    flow = Flow(monkeypatch)

    async def run():
        first = await flow.send(
            "근처에 카페 괜찮은 곳 있나",
            ("search_places", {"query": "카페", "area": "", "kind": "cafe", "mode": "nearby"}),
        )
        assert first.context.location_request and not flow.queries
        r = await flow.send("성수동", ("continue_planning", {}))
        assert r.candidates and "성수동" in flow.queries[0][1]

    asyncio.run(run())


@pytest.mark.parametrize("args", [{"date": "2026-11-07"}, {"date": ""}])
def test_missing_or_ungrounded_calendar_date_cannot_query_arbitrary_date(monkeypatch, args):
    flow = Flow(monkeypatch)
    text = "오늘 뭐 잡혔어?" if args["date"] else "저장한 약속 볼래"
    r = asyncio.run(flow.send(text, ("read_shared_calendar", args)))
    if args["date"]:
        assert "2026-11-06 공동 일정" in r.reply
        assert all(
            p.get("date", "eq.2026-11-06") == "eq.2026-11-06"
            for table, p in flow.reads
            if table == "appointments"
        )
    else:
        assert "날짜" in r.reply and not flow.reads


@pytest.mark.parametrize("kind", ["failure", "empty"])
def test_failed_and_empty_reads_are_distinct(monkeypatch, kind):
    flow = Flow(monkeypatch)
    flow.failure = kind == "failure"
    flow.appointments = []
    r = asyncio.run(flow.send("오늘 약속", ("read_shared_calendar", {"date": "2026-11-06"})))
    assert ("불러오지 못" in r.reply) == flow.failure
    assert ("없어요" in r.reply) != flow.failure
    assert flow.stats[-1]["model_calls"] == 1


def test_explicit_saved_plan_title_is_read_and_rendered_locally(monkeypatch):
    flow = Flow(monkeypatch)
    flow.plans = [
        {
            "id": "p",
            "draft_title": "주말 산책",
            "draft_date": "2026-11-06",
            "draft_activities": [{"title": "PRIVATE ACTIVITY"}],
        }
    ]
    r = asyncio.run(
        flow.send(
            "주말 산책이라는 저장 플랜 좀 보여줘", ("read_shared_plan", {"title": "주말 산책"})
        )
    )
    assert "PRIVATE ACTIVITY" in r.reply and "미확정" in r.reply
    assert all(p["archived"] == "eq.false" for _, p in flow.reads)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("delete_appointment", {}),
        ("lookup_selected_places", {}),
        ("read_shared_calendar", {"date": "2026-11-06", "table": "photos"}),
        ("read_shared_plan", {"plan_id": "00000000-0000-0000-0000-000000000001"}),
    ],
)
def test_unavailable_functions_and_ungrounded_ids_never_access_data(monkeypatch, name, args):
    flow = Flow(monkeypatch)
    r = asyncio.run(flow.send("알아서 해줘", (name, args)))
    assert not flow.reads and r.plan is None
    assert flow.stats[-1]["model_calls"] == 1


@pytest.mark.parametrize("field", ["unsupported", "save", "selection"])
def test_clarification_has_no_business_side_effect(monkeypatch, field):
    flow = Flow(monkeypatch)
    r = asyncio.run(flow.send("이거 할래", ("ask_user", {"field": field})))
    assert r.reply and not flow.reads and not flow.queries and r.plan is None


def test_current_proposal_edit_preserved_through_typed_continue(monkeypatch):
    proposal = {
        "title": "현재 초안",
        "date": "2026-11-06",
        "budget": 50000,
        "activities": [{"title": "카페", "time": "19:00", "place": "선택한 카페", "note": "메모"}],
    }
    flow = Flow(monkeypatch, context={"date": "2026-11-06"}, proposal=proposal)
    r = asyncio.run(flow.send("예산을 3만원으로 바꿔줘", ("continue_planning", {})))
    assert r.plan and r.plan.budget == 30000
    assert r.plan.activities[0].place == "선택한 카페" and r.plan.activities[0].note == "메모"
    assert not flow.reads


def test_selector_does_not_use_assistant_or_private_context_extras(monkeypatch):
    body = ai_planner.ChatInput.model_validate(
        {
            "messages": [
                {"role": "assistant", "content": "PRIVATE SCHEDULE"},
                {"role": "user", "content": "안녕"},
            ]
        }
    )
    messages = selection_messages(body, {"private": "PRIVATE DATA"}, None, datetime.now().date())
    assert "PRIVATE" not in json.dumps(messages)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"choices": [{"message": {"content": "조회했어요"}}]}),
        httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {}}]}),
    ],
)
def test_untyped_or_truncated_selection_does_not_claim_execution(monkeypatch, response):
    flow = Flow(monkeypatch)
    r = asyncio.run(flow.send("오늘 뭐 잡혔어", status=response))
    assert "구분하지 못" in r.reply and not flow.reads


def test_weather_and_private_read_do_not_mix_model_projections(monkeypatch):
    flow = Flow(monkeypatch)
    r = asyncio.run(
        flow.send(
            "오늘 약속 확인하고 서울 날씨도 볼래",
            ("read_shared_calendar", {"date": "2026-11-06"}),
            ("get_weather", {"city": "서울", "date": "2026-11-06"}),
        )
    )
    assert "PRIVATE SAVED TITLE" in r.reply and r.weather and len(flow.queries) == 1
    assert flow.stats[-1]["model_calls"] <= 3


def test_failed_public_argument_keeps_completed_private_read(monkeypatch):
    flow = Flow(monkeypatch)
    r = asyncio.run(
        flow.send(
            "오늘 약속이랑 날씨 확인해줘",
            ("read_shared_calendar", {"date": "2026-11-06"}),
            ("get_weather", {"city": "부산", "date": "2026-11-06"}),
        )
    )
    assert "PRIVATE SAVED TITLE" in r.reply and "도시와 날짜" in r.reply and not flow.queries


def test_exact_name_native_argument_normalization(monkeypatch):
    from datetime import date

    from we2day_api.ai_capability_router import Selection, apply_selection
    from we2day_api.ai_control import prepare

    Flow(monkeypatch)
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "서울숲 이름 그대로 검색해줘"}]}
    )
    decision = prepare(body, {}, None, date(2026, 11, 6))
    selection = Selection(
        calls=[
            (
                "search_places",
                {"query": "서울숲", "name": "", "mode": "exact_name", "area": "", "kind": "park"},
            )
        ]
    )
    apply_selection(selection, decision, body.messages[-1].content)
    assert (
        decision.directive.scope.exact_name == "서울숲"
        or decision.directive.slots["place_search"]["targets"][0]["query"] == "서울숲"
    )


def test_stale_pending_metadata_is_not_reused_by_selector(monkeypatch):
    from datetime import date

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "다시"}], "version": 3}
    )
    raw = selection_messages(
        body,
        {
            "dialogue": {"turn_version": 2, "pending": {"field": "date"}},
            "schedule_read": {"basis": 2, "date": "2026-11-06"},
        },
        None,
        date(2026, 11, 6),
    )
    view = json.loads(raw[-1]["content"])
    assert view["pending"] is None and view["saved_read_date"] is None


def test_explicit_relative_date_is_precomputed_for_selection():
    from datetime import date

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "모레 잡아둔 약속 정리해줘"}]}
    )
    value = selection_messages(body, {"date": "2026-11-06"}, None, date(2026, 11, 6))
    assert json.loads(value[-1]["content"])["resolved_request_date"] == "2026-11-08"


def test_unrequested_context_date_does_not_hide_named_plan(monkeypatch):
    flow = Flow(monkeypatch, context={"date": "2026-11-06"})
    flow.plans = [
        {
            "id": "p",
            "draft_title": "겨울 산책",
            "draft_date": "2026-12-01",
            "draft_activities": [{"title": "산책"}],
        }
    ]
    r = asyncio.run(
        flow.send(
            "겨울 산책이라는 저장 플랜 보여줘",
            ("read_shared_plan", {"title": "겨울 산책", "date": "2026-11-06"}),
        )
    )
    assert "2026-12-01" in r.reply and r.tools[0]["status"] == "ok"


def test_duplicate_calls_execute_once_and_conflicting_calls_do_not_read(monkeypatch):
    flow = Flow(monkeypatch)
    call = ("read_shared_calendar", {"date": "2026-11-06"})
    r = asyncio.run(flow.send("오늘 약속", call, call))
    assert r.tools[0]["status"] == "ok" and len(flow.reads) == 2
    flow.reads.clear()
    r = asyncio.run(flow.send("오늘 약속", call, ("ask_user", {"field": "target"})))
    assert "구분하지 못" in r.reply and not flow.reads


def test_native_selection_cancellation_releases_lease_without_completion(monkeypatch):
    flow = Flow(monkeypatch)
    events = []
    original = flow.store.rpc

    async def rpc(name, values=None):
        events.append(name)
        return await original(name, values)

    flow.store.rpc = rpc

    async def run():
        entered = asyncio.Event()

        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(ai_planner, "select_capability", blocked)
        task = asyncio.create_task(flow.send("오늘 약속"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert "release_ai_planner_turn" in events
    assert "finish_ai_planner_turn" not in events and not flow.reads


@pytest.mark.parametrize("code", [3036, 3040])
def test_native_provider_quota_and_busy_do_not_execute_or_finish(monkeypatch, code):
    flow = Flow(monkeypatch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            flow.send("오늘 약속", status=httpx.Response(429, json={"errors": [{"code": code}]}))
        )
    assert error.value.detail == ("ai_provider_limited" if code == 3036 else "ai_provider_busy")
    assert not flow.reads and not flow.queries and flow.store.version == 0


def test_named_plan_recovery_requires_the_complete_saved_title_in_user_request(monkeypatch):
    flow = Flow(monkeypatch)
    flow.plans = [
        {
            "id": "one",
            "draft_title": "가을 나들이",
            "draft_date": "2026-11-06",
            "draft_activities": [{"title": "산책"}],
        },
        {
            "id": "two",
            "draft_title": "가을 나들이 확장",
            "draft_date": "2026-11-06",
            "draft_activities": [{"title": "추가 일정"}],
        },
    ]
    r = asyncio.run(
        flow.send(
            "가을 나들이라고 저장해둔 플랜 열어줄래?",
            ("read_shared_plan", {"title": "가을 나들"}),
        )
    )
    assert r.tools[0]["status"] == "ok" and "산책" in r.reply and "추가 일정" not in r.reply
    assert all(
        p[column] == "like.가을 나들*"
        for _, p in flow.reads
        for column in ["content->>title", "published_content->>title"]
        if column in p
    )


def test_plan_title_page_limit_never_returns_a_false_unique_match(monkeypatch):
    flow = Flow(monkeypatch)
    flow.plans = [{"id": str(i), "draft_title": "산책"} for i in range(11)]
    r = asyncio.run(flow.send("산책 플랜 보여줘", ("read_shared_plan", {"title": "산책"})))
    assert r.tools[0]["status"] == "ambiguous" and "정확한 제목" in r.reply


def test_private_read_after_a_question_is_excluded_from_every_later_model_call(monkeypatch):
    flow = Flow(monkeypatch)
    flow.plans = [
        {
            "id": "p",
            "draft_title": "겨울 산책",
            "draft_date": "2026-12-01",
            "draft_activities": [{"title": "PRIVATE ACTIVITY"}],
        }
    ]

    async def run():
        first = await flow.send(
            "저장한 약속이랑 겨울 산책 플랜 보여줘",
            ("read_shared_calendar", {}),
            ("read_shared_plan", {"title": "겨울 산책"}),
        )
        assert first.reply.startswith("어느 날짜") and "PRIVATE ACTIVITY" in first.reply
        await flow.send(
            "성수동 카페 찾아줘",
            ("search_places", {"query": "카페", "area": "성수동", "kind": "cafe"}),
        )

    asyncio.run(run())


def test_selected_lookup_uses_only_explicit_request_ids(monkeypatch):
    flow = Flow(monkeypatch)
    r = asyncio.run(
        flow.send(
            "지금 체크한 장소 정보를 볼래",
            ("lookup_selected_places", {}),
            selected=[{"source": "favorite", "id": flow.selected}],
        )
    )
    assert any(t["name"] == "lookup_selected_places" and t["count"] == 1 for t in r.tools)
    assert len(flow.queries) == 1 and not flow.reads


def test_proposal_uses_the_date_supplied_in_the_same_request():
    from datetime import date

    from we2day_api.ai_capability_router import Selection, apply_selection
    from we2day_api.ai_control import prepare

    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": "2030년 4월 5일 성수동 식사와 카페 코스 짜줘"}]}
    )
    decision = prepare(body, {}, None, date(2026, 11, 6))
    apply_selection(
        Selection(
            calls=[
                (
                    "propose_course",
                    {"operation": "plan", "area": "성수동", "targets": ["식사", "카페"]},
                )
            ]
        ),
        decision,
        body.messages[-1].content,
    )
    assert not decision.directive.reply and decision.directive.slots["date"] == "2030-04-05"
    assert decision.directive.intent == "plan"


@pytest.mark.parametrize(
    ("text", "targets", "expected"),
    [
        ("카페를 찾고 싶은데 지역을 아직 안 정했어", [], "카페"),
        ("양식집을 찾고 싶은데 동네는 미정이야", ["양식집"], "양식집"),
    ],
)
def test_location_clarification_retains_the_grounded_target(monkeypatch, text, targets, expected):
    flow = Flow(monkeypatch)
    r = asyncio.run(flow.send(text, ("ask_user", {"field": "region", "targets": targets})))
    assert r.context.location_request and not flow.queries
    assert r.context.location_request["search"]["targets"][0]["query"] == expected
    assert flow.stats[-1]["model_calls"] == 1


def test_saved_read_does_not_become_an_edit_when_a_proposal_is_open(monkeypatch):
    proposal = {
        "title": "현재 초안",
        "date": "2026-12-01",
        "activities": [{"title": "산책", "place": "선택 공원"}],
    }
    flow = Flow(monkeypatch, proposal=proposal)
    r = asyncio.run(flow.send("오늘 어디 가기로 했지?", ("read_shared_calendar", {})))
    assert "PRIVATE SAVED TITLE" in r.reply and r.plan is None
    assert flow.store.proposal == proposal and flow.stats[-1]["model_calls"] == 1
