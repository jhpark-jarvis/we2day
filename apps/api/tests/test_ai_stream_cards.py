import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_ai_long_dialogue import Conversation

from we2day_api import ai_planner
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_search_followups import pending_promise, refinement
from we2day_api.ai_stream import events
from we2day_api.ai_tools import ToolSession
from we2day_api.config import Settings
from we2day_api.data import require_data
from we2day_api.main import create_app

REAL_COMPLETE = ai_planner.complete


@pytest.mark.parametrize("never_finishes", [False, True])
def test_token_truncation_has_only_one_bounded_repair(never_finishes):
    async def run():
        calls = []

        def provider(request):
            calls.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length"
                            if len(calls) == 1 or never_finishes
                            else "stop",
                            "message": {"content": json.dumps({"reply": "합성 완료"})},
                        }
                    ]
                },
            )

        session = ToolSession(SimpleNamespace(), None, [], [])
        session.direct_final = True
        stats = RunStats("test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            operation = REAL_COMPLETE(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성 질문"}],
                session,
                client=client,
                budget=Budget(),
                stats=stats,
            )
            if never_finishes:
                with pytest.raises(HTTPException):
                    await operation
            else:
                assert (await operation).reply == "합성 완료"
        assert len(calls) == 2 and stats.counts["schema_repairs"] == 1

    asyncio.run(run())


def test_cancelled_search_releases_its_lease_without_finishing_a_turn(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        started = asyncio.Event()

        async def provider(request):
            started.set()
            await asyncio.Event().wait()

        c.provider = provider
        task = asyncio.create_task(c.send("카페 찾아줘"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "release_ai_planner_turn" in c.calls
        assert "finish_ai_planner_turn" not in c.calls and c.store.version == 0

    asyncio.run(run())


def test_stream_hides_unknown_failures_and_bounds_progress_queue():
    async def run():
        async def failure(progress):
            for i in range(1000):
                progress("search" if i % 2 else "model")
            raise HTTPException(500, {"private": "synthetic secret"})

        output = [item async for item in events(failure)]
        assert len(output) <= 34 and "synthetic secret" not in "".join(output)
        assert output[-1] == 'event: error\ndata: {"code":"ai_unavailable","status":500}\n\n'

    asyncio.run(run())


@pytest.mark.parametrize(
    "text,keyword",
    [
        ("국물 요리없나??", "국물 요리"),
        ("라멘 먹고 싶어", "라멘"),
        ("샌드위치 없을까?", "샌드위치"),
        ("조용한 카페 있을까?", "조용한 카페"),
    ],
)
def test_specific_place_request_and_status_keep_the_actual_search(monkeypatch, text, keyword):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        result = await c.send(text)
        assert result.candidates
        assert any(keyword in query for query in c.queries)
        assert "기다려" not in result.reply
        first = c.queries[-1]
        for message in ["찾았어!?", "고마워", "다시"]:
            result = await c.send(message)
            if message != "고마워":
                assert result.candidates
                assert c.queries[-1] == first
        await c.send("카페 찾아줘")
        assert keyword not in c.queries[-1]

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        '제목은 "국물 요리 없나"로 바꿔줘',
        "국물 요리 검색 기능은 뭐야?",
        "예산은 없나?",
        "날씨는 어떨까?",
        "음식점은 검색하지 마",
        "카페는 없애줘",
        "사진은 없나?",
    ],
)
def test_a_refinement_is_not_a_setting_quotation_or_prohibition(text):
    assert refinement(text) is None


@pytest.mark.parametrize("text", ["카페 찾아줘", "성수동 근처 카페 찾아줘", "중랑구 도서관 찾아줘"])
def test_plain_categories_and_areas_do_not_become_lexical_filters(text):
    assert refinement(text) is None


def test_food_at_a_cafe_does_not_grant_restaurant_results(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        result = await c.send("샌드위치 파는 카페 있을까?")
        assert c.queries == ["중랑구 샌드위치 파는 카페"] and result.candidates
        assert result.context.search_scope.kinds == ["cafe"]
        result = await c.send("성수동 근처 카페 찾아줘")
        assert (
            c.queries[-1] == "성수동 카페"
            and result.context.model_extra.get("place_search") is None
        )

    asyncio.run(run())


def test_legacy_promise_status_retry_recovers_the_last_user_filter(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        scope = {"area": "중랑구", "kinds": ["cafe", "restaurant"], "search_only": True}
        c.store.context.update(
            search_scope=scope,
            control={
                "version": 1,
                "basis": 0,
                "last_action": {"operation": "search", "scope": scope},
                "outcome": "not_requested",
            },
        )
        c.history = [
            {"role": "user", "content": "국물 요리 없나?"},
            {"role": "assistant", "content": "찾을게요. 기다려주세요."},
            {"role": "user", "content": "찾았어!?"},
            {"role": "assistant", "content": "지역을 알려주세요."},
        ]
        result = await c.send("다시")
        assert result.candidates and c.queries == ["중랑구 국물 요리"]

    asyncio.run(run())


def test_status_follows_latest_search_instead_of_an_older_course(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        await c.send("카페 찾아줘")
        result = await c.send("찾았어?")
        assert result.candidates and len(c.queries) == 2 and result.plan is None
        await c.send("취소해줘")
        count = len(c.queries)
        result = await c.send("찾았어?")
        assert not result.candidates and len(c.queries) == count
        assert "진행 중인 검색은 없어요" in result.reply

    asyncio.run(run())


def test_refinement_survives_long_tail_and_an_explicit_new_search_clears_it(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        await c.send("제목 바꿔줘")
        result = await c.send("국물 요리 없나?")
        assert result.context.dialogue.pending is None
        assert c.store.proposal["title"] == "합성 코스"
        for _ in range(16):
            await c.send("고마워")
        result = await c.send("찾았어!?")
        assert result.candidates and c.queries[-1] == "중랑구 국물 요리"
        await c.send("취소해줘")
        assert c.store.context.get("place_search") is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "reply",
    [
        "국물 요리 장소를 찾을게요. 조금만 기다려주세요.",
        "검색해볼게요.",
        "코스를 정리해드릴게요.",
        "찾을게요.",
        "지금 검색하고 있어요.",
    ],
)
def test_a_model_cannot_finish_with_a_background_promise(reply):
    async def run():
        def provider(_):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps({"reply": reply})}}]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            result = await REAL_COMPLETE(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성 질문"}],
                client=client,
                budget=Budget(),
                stats=RunStats("test"),
            )
        assert not pending_promise(result.reply)
        assert "검색을 실행하지 않았어요" in result.reply

    asyncio.run(run())


def test_stream_progress_arrives_before_completion_with_heartbeat_and_cancel():
    async def run():
        release, started, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def work(progress):
            try:
                progress("search")
                started.set()
                await release.wait()
                return ai_planner.SavedChatResult(reply="합성 완료", version=1)
            finally:
                stopped.set()

        stream = events(work, heartbeat=0.01)
        assert '"accepted"' in await anext(stream)
        assert '"search"' in await anext(stream)
        assert started.is_set() and not stopped.is_set()
        assert "heartbeat" in await anext(stream)
        release.set()
        result = await anext(stream)
        assert "event: result" in result and "합성 완료" in result
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert stopped.is_set()
        release.clear()
        stopped.clear()
        stream = events(work)
        await anext(stream)
        await anext(stream)
        await stream.aclose()
        assert stopped.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_endpoint_stream_has_one_terminal_and_keeps_json_compatibility(monkeypatch, failure):
    app = create_app(
        Settings(_env_file=None, cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic")
    )
    app.dependency_overrides[require_data] = lambda: object()

    async def work(body, settings, store, client, budget, stats):
        stats.stage("search")
        stats.stage("validate")
        if failure:
            raise HTTPException(503, "ai_timeout")
        return ai_planner.SavedChatResult(reply="합성 완료", version=1)

    monkeypatch.setattr(ai_planner, "_chat", work)
    with TestClient(app) as client:
        response = client.post(
            "/ai/planner",
            headers={"Accept": "text/event-stream"},
            json={"messages": [{"role": "user", "content": "합성 검색"}]},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.text.count("event: error" if failure else "event: result") == 1
        assert response.text.index('"search"') < response.text.index(
            "event: error" if failure else "event: result"
        )
        assert "ai_timeout" in response.text if failure else "합성 완료" in response.text
        response = client.post(
            "/ai/planner", json={"messages": [{"role": "user", "content": "합성 검색"}]}
        )
        assert response.status_code == (503 if failure else 200)
        if not failure:
            assert response.json()["reply"] == "합성 완료"
