"""Current proposal checks and sync/async provider contracts, without external I/O."""

import asyncio
import copy
from datetime import date

import httpx
import pytest
from fastapi import HTTPException
from test_ai_capabilities import Flow, native

from we2day_api import places
from we2day_api.ai_capabilities import BY_NAME, batch_definition
from we2day_api.ai_capability_reads import read_plan
from we2day_api.ai_capability_router import MODELS
from we2day_api.ai_course_check import inspect_current_course
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_saved_schedule import ScheduleRead, read_schedule, summarize_schedule
from we2day_api.ai_selection import parse_selection
from we2day_api.ai_tool_runtime import ToolIO
from we2day_api.config import Settings
from we2day_api.plans import PlanContent


def sample(**changes):
    return PlanContent.model_validate(
        {
            "title": "합성 초안",
            "date": "2030-06-15",
            "budget": 18000,
            "activities": [
                {"title": "식사", "time": "14:00", "place": "합성 식당", "cost": 15000},
                {"title": "카페", "time": "14:00", "place": "합성 식당", "cost": 5000},
                {"title": "산책", "time": "13:00"},
            ],
            **changes,
        }
    )


def test_current_inspection_is_exact_and_preserves_every_field():
    plan = sample()
    before = plan.model_dump()
    reply, reports = inspect_current_course(plan)
    assert all(
        t in reply
        for t in [
            "20,000원",
            "18,000원",
            "미정",
            "같은 시각",
            "앞선 활동보다",
            "앞선 장소",
            "장소를 선택",
        ]
    )
    assert reports[0]["name"] == "validate_course" and reports[0]["status"] == "ok"
    assert plan.model_dump() == before
    assert "확인하지 않았어요" in reply


@pytest.mark.parametrize("cost,expected", [(0, "0원"), (None, "미정")])
def test_zero_and_unknown_costs_are_not_interchanged(cost, expected):
    reply, _ = inspect_current_course(
        sample(budget=0, activities=[{"title": "산책", "place": "합성 공원", "cost": cost}])
    )
    assert expected in reply
    if cost is None:
        assert "0원" not in reply.splitlines()[1] and "예산 초과 문제는 없어요" not in reply


def test_missing_and_empty_proposals_have_distinct_guidance():
    reply, reports = inspect_current_course(None)
    assert "먼저" in reply and reports[0]["status"] == "needs_input"
    reply, reports = inspect_current_course(sample(activities=[]))
    assert "활동을 추가" in reply and reports[0]["status"] == "ok"


def test_native_check_is_one_model_selection_without_business_access_or_edit(monkeypatch):
    proposal = sample().model_dump()
    flow = Flow(monkeypatch, context={"date": proposal["date"], "budget": 18000}, proposal=proposal)
    result = asyncio.run(flow.send("현재 코스 점검해줘", ("validate_course", {})))
    assert "20,000" in result.reply and len(flow.models) == 1
    assert not flow.reads and not flow.queries and result.plan is None
    assert flow.store.proposal == proposal and flow.stats[-1]["selection_tool_validate_course"] == 1


def test_check_and_search_can_run_together_without_exporting_a_later_private_read(monkeypatch):
    proposal = sample().model_dump()
    flow = Flow(monkeypatch, context={"date": proposal["date"], "budget": 18000}, proposal=proposal)

    async def run():
        result = await flow.send(
            "현재 코스 점검하고 성수동 카페 후보도 찾아줘",
            ("validate_course", {}),
            (
                "search_places",
                {"query": "카페", "targets": ["카페"], "area": "성수동", "kind": "cafe"},
            ),
        )
        assert "20,000" in result.reply and result.candidates
        result = await flow.send(
            "현재 코스 점검하고 오늘 약속도 보여줘",
            ("validate_course", {}),
            ("read_shared_calendar", {}),
        )
        assert "PRIVATE SAVED TITLE" in result.reply
        await flow.send(
            "성수동 카페 찾아줘",
            (
                "search_places",
                {"query": "카페", "targets": ["카페"], "area": "성수동", "kind": "cafe"},
            ),
        )
        assert flow.store.proposal == proposal

    asyncio.run(run())


def test_model_cannot_supply_a_replacement_plan_to_the_check_tool(monkeypatch):
    proposal = sample().model_dump()
    flow = Flow(monkeypatch, proposal=proposal)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            flow.send(
                "현재 코스 점검",
                responses=[
                    native(("validate_course", {"plan": proposal})),
                    native(("validate_course", {"plan": proposal})),
                ],
            )
        )
    assert error.value.detail == "ai_selection_failed"
    assert flow.store.proposal == proposal and not flow.reads and not flow.queries


def test_one_native_batch_executes_both_requested_actions_without_parallel_calls(monkeypatch):
    proposal = sample().model_dump()
    flow = Flow(monkeypatch, proposal=proposal)
    tasks = [
        {"name": "validate_course", "arguments": {}},
        {
            "name": "search_places",
            "arguments": {"query": "카페", "targets": ["카페"], "area": "성수동", "kind": "cafe"},
        },
    ]
    result = asyncio.run(
        flow.send("코스 점검하고 성수동 카페 찾아줘", ("select_capabilities", {"tasks": tasks}))
    )
    assert result.candidates and "20,000" in result.reply
    assert flow.store.proposal == proposal and len(flow.models) == 1
    assert flow.models[0]["tools"][0]["function"]["name"] == "select_capabilities"


def test_batch_schema_reapplies_selection_filters_and_has_a_fixed_task_limit():
    one = batch_definition(MODELS, selected=False)
    schema = one["function"]["parameters"]["properties"]["tasks"]
    assert schema["minItems"] == 1 and schema["maxItems"] == 4
    names = {s["properties"]["name"]["const"] for s in schema["items"]["oneOf"]}
    assert names == set(MODELS) - {"lookup_selected_places"}
    two = batch_definition(MODELS, selected=True)
    assert len(two["function"]["parameters"]["properties"]["tasks"]["items"]["oneOf"]) == len(
        MODELS
    )


@pytest.mark.parametrize(
    "tasks,expected",
    [
        ([], "invalid_arguments"),
        ([{"name": "unknown", "arguments": {}}], "unknown_tool"),
        ([{"name": "lookup_selected_places", "arguments": {}}], "selection_required"),
        ([{"name": "validate_course", "arguments": {"plan": {}}}], "invalid_arguments"),
        (
            [{"name": "validate_course", "arguments": {}, "url": "https://invalid.example"}],
            "invalid_arguments",
        ),
        ([{"name": "validate_course", "arguments": {}}] * 5, "too_many_calls"),
        (
            [
                {"name": "ask_user", "arguments": {"field": "target"}},
                {"name": "validate_course", "arguments": {}},
            ],
            "conflicting_calls",
        ),
    ],
)
def test_batch_cannot_bypass_per_capability_arguments_permissions_or_combinations(tasks, expected):
    response = native(("select_capabilities", {"tasks": tasks}))
    result = parse_selection(response.content, MODELS, BY_NAME, selected=False)
    assert result.invalid and result.invalid_reason == expected


def test_clipped_schedule_is_reported_partial_and_stays_server_only():
    rows = [
        {"id": str(i), "kind": "shared", "date": "2030-06-15", "title": "합성"} for i in range(11)
    ]

    class Store:
        async def call(self, method, table, **kwargs):
            assert method == "GET" and table in {"appointments", "date_plans"}
            return rows if table == "appointments" else []

    reply, reports = asyncio.run(
        read_schedule(ScheduleRead(date="2030-06-15"), Store(), RunStats("test"))
    )
    assert "일부" in reply and reports[0]["status"] == "partial"
    normal = summarize_schedule("2030-06-15", rows[:1], [])
    assert not normal.partial and normal.count == 1


def test_exact_plan_date_is_filtered_before_limit_and_long_plan_is_partial():
    params = []
    row = {
        "id": "synthetic",
        "draft_title": "합성 초안",
        "draft_date": "2030-06-15",
        "draft_activities": [{"title": "합성" * 50, "place": "합성" * 100} for _ in range(20)],
    }

    class Store:
        async def call(self, method, table, **kwargs):
            params.append(kwargs["params"])
            return [copy.deepcopy(row)]

    result, reports = asyncio.run(
        read_plan(
            {"plan_id": "", "title": "합성 초안", "date": "2030-06-15"},
            "2030년 6월 15일 합성 초안 플랜 보여줘",
            {},
            0,
            date(2026, 11, 9),
            Store(),
            RunStats("test"),
        )
    )
    assert all("or" in p and "2030-06-15" in p["or"] for p in params)
    assert reports[0]["status"] == "partial" and len(result) <= 3900 and "일부" in result


@pytest.mark.parametrize(
    "status,raw,expected",
    [
        (200, b'{"items":[]}', None),
        (429, b"PRIVATE", (429, "place_search_limited")),
        (503, b"PRIVATE", (503, "place_search_unavailable")),
        (200, b"PRIVATE", (503, "place_search_unavailable")),
        (200, b'{"items":[]}' + b" " * 65536, (503, "place_search_unavailable")),
    ],
    ids=["ok", "limited", "unavailable", "malformed", "oversized"],
)
def test_ui_and_ai_share_wire_validation_and_provider_failures(monkeypatch, status, raw, expected):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "naverapihub.apigw.ntruss.com"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(status, content=raw)

    original = httpx.Client
    monkeypatch.setattr(
        places.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    config = Settings(
        _env_file=None,
        naver_search_enabled=True,
        naver_search_client_id="synthetic-id",
        naver_search_client_secret="synthetic-secret",
    )

    async def ai():
        stats = RunStats("test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ToolIO(config, client, None, Budget(), stats).perform(
                ("places", "성수동 카페")
            )

    for invoke in [lambda: places.fetch_places(config, "성수동 카페"), lambda: asyncio.run(ai())]:
        if expected:
            with pytest.raises(HTTPException) as error:
                invoke()
            assert (error.value.status_code, error.value.detail) == expected
            assert "PRIVATE" not in str(error.value.detail)
        else:
            assert invoke().items == []
    assert len(calls) == 2 and calls[0].url == calls[1].url
    for name in ["X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY"]:
        assert calls[0].headers[name] == calls[1].headers[name]
