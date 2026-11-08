"""Selection faults, budgets and end-to-end recovery without business side effects."""

import asyncio
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from test_ai_capabilities import Flow, native

from we2day_api import ai_capability_router as router
from we2day_api.ai_capabilities import BY_NAME
from we2day_api.ai_planner import ChatInput, Message
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_selection import parse_selection, record_selection
from we2day_api.config import Settings


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"{", "invalid_json"),
        (b"[]", "invalid_shape"),
        (b'{"choices":[]}', "invalid_shape"),
        (b'{"choices":[{"message":{}}]}', "missing_calls"),
        (b'{"choices":[{"finish_reason":"length","message":{}}]}', "truncated"),
        (native(("delete_appointment", {})).content, "unknown_tool"),
        (native(("lookup_selected_places", {})).content, "selection_required"),
        (native(("search_places", {"query": "a" * 51})).content, "invalid_arguments"),
        (
            native(
                (
                    "read_shared_calendar",
                    {"date": "2030-01-01", "PRIVATE_SECRET": "PRIVATE_ADDRESS"},
                )
            ).content,
            "invalid_arguments",
        ),
        (
            native(("continue_planning", {}), ("read_shared_calendar", {})).content,
            "conflicting_calls",
        ),
        (native(*[("read_shared_calendar", {})] * 5).content, "too_many_calls"),
    ],
)
def test_faults_are_distinct_and_do_not_echo_values(raw, reason):
    result = parse_selection(raw, router.MODELS, BY_NAME, selected=False)
    assert result.invalid and result.invalid_reason == reason and not result.calls
    assert "PRIVATE" not in repr(result) and "a" * 51 not in repr(result)


def test_format_repair_executes_reads_only_after_valid_selection(monkeypatch):
    flow = Flow(monkeypatch)
    invalid = native(
        ("read_shared_calendar", {"date": "2026-11-06", "PRIVATE_SECRET": "PRIVATE_ADDRESS"})
    )
    result = asyncio.run(
        flow.send(
            "오늘 약속 보여줘",
            responses=[invalid, native(("read_shared_calendar", {"date": "2026-11-06"}))],
        )
    )
    assert "PRIVATE SAVED TITLE" in result.reply and len(flow.reads) == 2
    assert len(flow.models) == 2 and flow.store.version == 1
    stats = flow.stats[-1]
    assert stats["selection_first_invalid"] == stats["selection_repaired"] == 1
    assert stats["selection_error_invalid_arguments"] == 1
    assert "PRIVATE_SECRET" not in json.dumps(flow.models)
    assert "PRIVATE_ADDRESS" not in json.dumps(flow.models)


@pytest.mark.parametrize("status", [429, 503])
def test_provider_failure_is_not_automatically_retried(monkeypatch, status):
    flow = Flow(monkeypatch)
    with pytest.raises(HTTPException):
        asyncio.run(flow.send("오늘 약속 보여줘", status=httpx.Response(status, json={})))
    assert len(flow.models) == 1 and not flow.reads and flow.store.version == 0


@pytest.mark.parametrize(
    "clock_advance,remaining,initial_calls", [(17, 85, 0), (0, 29, 0), (0, 85, 1)]
)
def test_repair_leaves_stage_total_and_followup_budgets(
    monkeypatch, clock_advance, remaining, initial_calls
):
    ticks = [0.0]
    monkeypatch.setattr(router, "time", SimpleNamespace(monotonic=lambda: ticks[0]))
    requests = []

    def provider(request):
        requests.append(request)
        ticks[0] += clock_advance
        return httpx.Response(200, json={"choices": [{"message": {}}]})

    async def run():
        stats = RunStats("test")
        stats.counts["model_calls"] = initial_calls
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await router.select(
                ChatInput(messages=[Message(role="user", content="오늘 일정")]),
                {},
                None,
                date(2026, 11, 8),
                Settings(_env_file=None),
                client,
                Budget(remaining),
                stats,
            )

    assert asyncio.run(run()).invalid and len(requests) == 1


@pytest.mark.parametrize(
    "text,index",
    [("첫 번째 활동 근처에 약국을 찾아줘", 0), ("마지막 활동 주변에 빵집을 찾아줘", 1)],
)
def test_search_tool_resolves_activity_reference_without_second_interpreter(
    monkeypatch, text, index
):
    plan = {
        "title": "합성",
        "date": "2030-01-01",
        "activities": [
            {"title": "첫 활동", "place": "성수 식당 (성수동 1)"},
            {"title": "마지막 활동", "place": "성수 카페 (성수동 2)"},
        ],
    }
    flow = Flow(monkeypatch, context={"region": "성수동"}, proposal=plan)
    term = "약국" if index == 0 else "빵집"
    asyncio.run(
        flow.send(
            text,
            (
                "search_places",
                {"query": term, "mode": "nearby", "anchor_ref": f"activity_{index + 1}"},
            ),
        )
    )
    assert any(plan["activities"][index]["place"].split(" (")[0] in q[1] for q in flow.queries)
    assert flow.stats[-1]["model_calls"] == 1 and flow.store.proposal == plan


def test_repair_progress_is_real_and_final_failure_releases_lease(monkeypatch):
    flow = Flow(monkeypatch, proposal={"title": "합성", "date": "2030-01-01", "activities": []})
    before = json.dumps(flow.store.proposal)
    events = []
    original = flow.store.rpc

    async def rpc(name, values=None):
        events.append(name)
        return await original(name, values)

    flow.store.rpc = rpc
    bad = native(("continue_planning", {}), ("read_shared_calendar", {}))
    with pytest.raises(HTTPException):
        asyncio.run(flow.send("오늘 약속 보여줘", responses=[bad, bad]))
    assert "release_ai_planner_turn" in events and "finish_ai_planner_turn" not in events
    assert not flow.reads and json.dumps(flow.store.proposal) == before


def test_long_read_search_edit_flow_keeps_viewed_date_separate_from_current_course(monkeypatch):
    plan = {
        "title": "합성 코스",
        "date": "2030-01-01",
        "activities": [{"title": "산책", "place": "성수 공원"}],
    }
    flow = Flow(monkeypatch, context={"date": "2030-01-01", "region": "성수동"}, proposal=plan)

    async def run():
        for i in range(12):
            await flow.send(
                "오늘 공동 약속 보여줘", ("read_shared_calendar", {"date": "2026-11-06"})
            )
            await flow.send(
                "성수동 카페 후보만 검색해줘",
                ("search_places", {"query": "카페", "area": "성수동", "kind": "cafe"}),
            )
            result = await flow.send(f"현재 코스 예산만 {10000 + i * 1000}원으로 바꿔줘")
            assert result.plan.date == "2030-01-01" and result.plan.budget == 10000 + i * 1000
            assert result.plan.activities[0].place == "성수 공원"

    asyncio.run(run())
    assert flow.store.version == 36 and len(flow.models) == 24 and len(flow.reads) == 24
    assert all("PRIVATE" not in json.dumps(model) for model in flow.models)


def test_one_native_call_covers_independent_targets_and_deduplicates(monkeypatch):
    flow = Flow(monkeypatch)
    asyncio.run(
        flow.send(
            "성수동 식당과 카페 후보를 찾아줘",
            (
                "search_places",
                {"query": "식당", "targets": ["식당", "카페", "식당"], "area": "성수동"},
            ),
        )
    )
    assert {q[1] for q in flow.queries} == {"성수동 식당", "성수동 카페"}
    assert flow.stats[-1]["model_calls"] == 1
    assert router.MODELS["search_places"].model_json_schema()["required"] == ["query", "targets"]


def test_fixed_diagnostics_never_log_rejected_arguments_or_extra_field_names(caplog):
    import logging

    from we2day_api.prompt_bundle import PROMPT

    raw = native(
        (
            "search_places",
            {"query": "카페", "kind": "PRIVATE_KIND", "PRIVATE_KEY": "PRIVATE_ADDRESS"},
        )
    ).content
    selected = parse_selection(raw, router.MODELS, BY_NAME, selected=False)
    stats = RunStats(PROMPT.version)
    record_selection(stats, selected, attempt=0, names=router.MODELS)
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        stats.emit(502)
    assert "PRIVATE" not in caplog.text
    assert "selection_error_invalid_arguments" in caplog.text
    assert "selection_field_kind" in caplog.text


def test_selection_repair_shares_the_original_stage_deadline(monkeypatch):
    ticks = [0.0]
    seconds = []
    monkeypatch.setattr(router, "time", SimpleNamespace(monotonic=lambda: ticks[0]))
    original = router.bounded_response

    async def bounded(*args, **kwargs):
        seconds.append(kwargs["seconds"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(router, "bounded_response", bounded)

    def provider(request):
        ticks[0] += 4
        return (
            httpx.Response(200, json={"choices": [{"message": {}}]})
            if len(seconds) == 1
            else native(("read_shared_calendar", {}))
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await router.select(
                ChatInput(messages=[Message(role="user", content="오늘 일정")]),
                {},
                None,
                date(2026, 11, 8),
                Settings(_env_file=None),
                client,
                Budget(),
                RunStats("test"),
            )

    assert not asyncio.run(run()).invalid
    assert seconds == [18, 14]
