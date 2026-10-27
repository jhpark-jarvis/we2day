import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from we2day_api.ai_runtime import Budget, RunStats, bounded_response, with_disconnect
from we2day_api.ai_tool_runtime import execute_batch
from we2day_api.ai_tools import ToolSession
from we2day_api.places import SearchResults
from we2day_api.upstream import BorrowedAsyncTransport


def test_slow_drip_is_closed_at_whole_deadline():
    class Drip(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "

        async def aclose(self):
            self.closed = True

    async def run():
        drip = Drip()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=drip))
        ) as client:
            with pytest.raises(TimeoutError):
                await bounded_response(
                    client,
                    "GET",
                    "https://synthetic.invalid",
                    Budget(0.06),
                    limit=65536,
                    seconds=28,
                )
        assert drip.closed

    asyncio.run(run())


def test_disconnect_cancels_work_without_followup_and_watcher_always_finishes():
    async def run():
        events = []

        async def operation():
            try:
                await asyncio.sleep(1)
                events.append("unexpected-write")
            finally:
                events.append("closed")

        request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=True))
        with pytest.raises(HTTPException) as error:
            await with_disconnect(operation(), request, Budget(0.5))
        assert error.value.status_code == 499 and events == ["closed"]

        # Starlette's disconnect probe may suppress cancellation inside its cancel scope.
        async def probe():
            try:
                await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                pass
            return False

        value = await asyncio.wait_for(
            with_disconnect(
                asyncio.sleep(0.001, result="ok"), SimpleNamespace(is_disconnected=probe), Budget()
            ),
            timeout=0.5,
        )
        assert value == "ok"

    asyncio.run(run())


def test_parallel_reads_are_bounded_deduplicated_and_commit_refs_in_order():
    async def run():
        active, peak, calls = 0, 0, []

        class IO:
            slots = asyncio.Semaphore(2)

            async def perform(self, action):
                nonlocal active, peak
                async with self.slots:
                    active += 1
                    peak = max(peak, active)
                    query = action[1]
                    calls.append(query)
                    await asyncio.sleep(0.03 if query == "첫" else 0.001)
                    active -= 1
                    return SearchResults(items=[{"title": query, "address": "가상로"}])

        session = ToolSession(SimpleNamespace(), None, [], [])
        tools = [
            {"function": {"name": "search_places", "arguments": json.dumps({"query": q})}}
            for q in ["첫", "둘", "셋", "넷"]
        ]
        output = await execute_batch(session, tools, IO())
        assert peak == 2 and [x["items"][0]["ref"] for x in output] == ["p1", "p2", "p3", "p4"]
        duplicate = {"function": {"name": "search_places", "arguments": ' { "query" : " 첫 " } '}}
        cached = await execute_batch(session, [tools[0], duplicate], IO())
        assert cached[0] == cached[1] and len(calls) == 4

    asyncio.run(run())


def test_borrowed_pool_never_shares_headers_or_cookies_between_clients():
    async def run():
        seen = []

        def handler(request):
            seen.append(dict(request.headers))
            return httpx.Response(200, headers={"Set-Cookie": "private=value"}, json={})

        pool = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=BorrowedAsyncTransport(pool), headers={"Authorization": "Bearer synthetic"}
        ) as caller:
            await caller.get("https://synthetic.invalid")
        async with httpx.AsyncClient(transport=BorrowedAsyncTransport(pool)) as other:
            await other.get("https://synthetic.invalid")
        assert "authorization" not in seen[1] and "cookie" not in seen[1]
        await pool.aclose()

    asyncio.run(run())


def test_metric_allowlist_never_logs_provider_payload_or_contents(caplog):
    stats = RunStats("test-v1")
    stats.usage({"usage": {"prompt_tokens": 3, "completion_tokens": "private", "other": "secret"}})
    with stats.span("model"):
        pass
    with caplog.at_level("INFO", logger="uvicorn.error"):
        stats.emit("ok")
    assert "private" not in caplog.text and "secret" not in caplog.text
    assert '"prompt_tokens": 3' in caplog.text
    with pytest.raises(ValueError):
        with stats.span("user-secret-label"):
            pass


def test_real_async_tool_pipeline_separates_provider_and_caller_credentials():
    from datetime import date
    from uuid import uuid4

    from we2day_api.ai_planner import complete
    from we2day_api.ai_runtime import AIStore
    from we2day_api.ai_tool_runtime import ToolIO
    from we2day_api.ai_tools import SelectedPlace
    from we2day_api.data import DataAPI

    async def run():
        chosen_id = str(uuid4())
        requests, model_calls = [], []
        settings = SimpleNamespace(
            cloudflare_account_id="a" * 32,
            cloudflare_api_token="cf-secret",
            naver_search_enabled=True,
            naver_search_client_id="naver-id",
            naver_search_client_secret="naver-secret",
        )
        today = date.today().isoformat()

        def handler(request):
            requests.append(request)
            host = request.url.host
            if host == "api.cloudflare.com":
                assert request.headers["authorization"] == "Bearer cf-secret"
                assert (
                    "apikey" not in request.headers and "x-ncp-apigw-api-key" not in request.headers
                )
                model_calls.append(json.loads(request.content))
                if len(model_calls) == 1:
                    calls = [
                        {"function": {"name": name, "arguments": args}}
                        for name, args in [
                            ("search_places", json.dumps({"query": "가상동 카페"})),
                            ("lookup_selected_places", "{}"),
                            ("get_weather", json.dumps({"city": "서울", "date": today})),
                        ]
                    ]
                    return httpx.Response(
                        200, json={"choices": [{"message": {"tool_calls": calls}}]}
                    )
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "reply": "완료",
                                            "plan": {
                                                "title": "합성",
                                                "date": today,
                                                "activities": [
                                                    {"title": "카페", "place_ref": "p1"}
                                                ],
                                            },
                                        }
                                    )
                                }
                            }
                        ]
                    },
                )
            if host == "synthetic.supabase.invalid":
                assert request.headers["authorization"] == "Bearer caller-jwt"
                assert request.headers["apikey"] == "publishable"
                assert request.url.params["id"] == f"in.({chosen_id})"
                return httpx.Response(
                    200, json=[{"id": chosen_id, "label": "선택 장소", "destination": "가상로2"}]
                )
            assert "authorization" not in request.headers and "apikey" not in request.headers
            if host == "naverapihub.apigw.ntruss.com":
                assert request.headers["x-ncp-apigw-api-key"] == "naver-secret"
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"title": "검색 장소", "address": "가상로1", "category": "카페,디저트"}
                        ]
                    },
                )
            assert "x-ncp-apigw-api-key" not in request.headers
            if host == "geocoding-api.open-meteo.com":
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "name": "서울",
                                "country_code": "KR",
                                "latitude": 37.5,
                                "longitude": 127.0,
                            }
                        ]
                    },
                )
            assert host == "api.open-meteo.com"
            return httpx.Response(
                200,
                json={
                    "daily": {
                        "time": [today],
                        "temperature_2m_min": [10],
                        "temperature_2m_max": [20],
                        "precipitation_probability_max": [0],
                    }
                },
            )

        pool = httpx.MockTransport(handler)
        budget, stats = Budget(), RunStats("test-v1")
        with httpx.Client(
            base_url="https://synthetic.supabase.invalid/rest/v1/",
            headers={"Authorization": "Bearer caller-jwt", "apikey": "publishable"},
        ) as sync:
            async with (
                httpx.AsyncClient(transport=pool) as external,
                httpx.AsyncClient(transport=BorrowedAsyncTransport(pool)) as database,
            ):
                store = AIStore(DataAPI(sync), database, budget, stats)
                session = ToolSession(
                    settings, store, [SelectedPlace(source="favorite", id=chosen_id)], []
                )
                result = await complete(
                    settings,
                    [{"role": "user", "content": "합성 요청"}],
                    session,
                    client=external,
                    budget=budget,
                    stats=stats,
                    io=ToolIO(settings, external, store, budget, stats),
                )
                assert result.plan.activities[0].place == "검색 장소 (가상로1)"
                assert len(result.weather) == 1 and stats.counts["model_calls"] == 2
                assert len(requests) == 6

    asyncio.run(run())
