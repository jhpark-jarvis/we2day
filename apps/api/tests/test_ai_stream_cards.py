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
from we2day_api.ai_search_followups import parking_request, pending_promise, refinement
from we2day_api.ai_stream import events
from we2day_api.ai_tools import ToolSession
from we2day_api.config import Settings
from we2day_api.data import require_data
from we2day_api.main import create_app

REAL_COMPLETE = ai_planner.complete


@pytest.mark.parametrize(
    "text", ["흠.. 피자집도 추천해줘", "음 피자집도 좀 찾아줘", "그럼 피자집은 추천해줘"]
)
def test_natural_food_search_retains_the_specific_query_and_retry(monkeypatch, text):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        before = json.loads(json.dumps(c.store.proposal))
        result = await c.send(text)
        assert result.candidates and c.queries[-1] == "중랑구 피자집"
        assert result.context.model_extra["place_search"]["query"] == "피자집"
        for message in ["고마워", "다시", "찾았어!?"]:
            await c.send(message)
        assert c.queries[-1] == "중랑구 피자집" and c.store.proposal == before
        await c.send("카페 찾아줘")
        assert c.queries[-1] == "중랑구 카페"

    asyncio.run(run())


def parking_provider(c):
    def provider(request):
        assert request.url.host == "naverapihub.apigw.ntruss.com"
        c.queries.append(request.url.params["query"])
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "합성 공영주차장",
                        "category": "교통>주차장",
                        "roadAddress": "서울특별시 중랑구 신내동 1",
                    },
                    {
                        "title": "합성식당",
                        "category": "음식점",
                        "roadAddress": "서울특별시 중랑구 신내동 2",
                    },
                    {
                        "title": "먼 공영주차장",
                        "category": "주차장",
                        "roadAddress": "부산광역시 해운대구 1",
                    },
                ]
            },
        )

    return provider


@pytest.mark.parametrize(
    "text",
    [
        "식사 장소 주변에 주차장 알려달라고",
        "선택한 식당 주변 주차장 찾아줘",
        "합성식당 주변 주차장 찾아줘",
    ],
)
def test_parking_is_the_target_and_meal_is_the_anchor(monkeypatch, text):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.provider = parking_provider(c)
        before = json.loads(json.dumps(c.store.proposal))
        result = await c.send(text)
        assert c.queries == ["중랑구 합성식당 주차장"]
        assert [p.title for p in result.candidates] == ["합성 공영주차장"]
        assert result.context.region == "중랑구" and result.context.search_scope.kinds == ["any"]
        assert c.store.proposal == before
        for _ in range(16):
            await c.send("고마워")
        await c.send("다시")
        assert c.queries[-1] == "중랑구 합성식당 주차장"
        result = await choose_card(c, None)
        assert (
            result.plan.activities[:2] == ai_planner.PlanContent.model_validate(before).activities
        )
        assert len(result.plan.activities) == 3 and result.plan.activities[-1].title == "주차장"
        assert result.plan.activities[-1].time is None and result.plan.activities[-1].cost is None
        await c.send("카페 찾아줘")
        assert c.queries[-1] == "중랑구 카페"

    asyncio.run(run())


def test_an_ambiguous_course_anchor_requires_a_choice_not_a_fake_area(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.provider = parking_provider(c)
        result = await c.send("이후 일정에 주변 주차장도 찾아줘")
        assert not c.queries and result.plan is None
        assert "어느 장소" in result.reply and result.context.region == "중랑구"
        result = await c.send("다시")
        assert not c.queries and "어느 장소" in result.reply
        result = await c.send("식사 장소")
        assert c.queries == ["중랑구 합성식당 주차장"] and result.candidates

    asyncio.run(run())


@pytest.mark.parametrize("answer,anchor", [("2번", "합성식당"), ("합성카페", "합성카페")])
def test_parking_anchor_clarification_accepts_number_or_actual_name(monkeypatch, answer, anchor):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.provider = parking_provider(c)
        await c.send("이후 일정에 주변 주차장도 찾아줘")
        result = await c.send(answer)
        assert c.queries == [f"중랑구 {anchor} 주차장"] and result.candidates

    asyncio.run(run())


def test_new_search_replaces_a_pending_parking_anchor_question(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        await c.send("이후 일정에 주변 주차장도 찾아줘")
        await c.send("카페 찾아줘")
        assert c.queries == ["중랑구 카페"] and c.store.context.get("place_search") is None

    asyncio.run(run())


def test_parking_empty_name_search_uses_only_the_stored_road_and_labels_the_scope(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.store.proposal["activities"][1]["place"] = "합성식당 (서울특별시 중랑구 망우로 322)"
        normal = parking_provider(c)

        def provider(request):
            if "합성식당" in request.url.params["query"]:
                c.queries.append(request.url.params["query"])
                return httpx.Response(200, json={"items": []})
            return normal(request)

        c.provider = provider
        result = await c.send("2번 활동 주변 주차장 찾아줘")
        assert c.queries == ["중랑구 합성식당 주차장", "중랑구 망우로 주차장"]
        assert result.candidates and "도로·동네 범위" in result.reply
        assert "실제 거리·주차 가능 여부" in result.reply
        assert result.context.model_extra["place_search"]["query"] == "합성식당 주차장"

    asyncio.run(run())


def test_parking_provider_failure_does_not_broaden_or_claim_an_empty_result(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.store.proposal["activities"][1]["place"] = "합성식당 (서울 중랑구 망우로 322)"

        def provider(request):
            c.queries.append(request.url.params["query"])
            return httpx.Response(503)

        c.provider = provider
        result = await c.send("식사 장소 주변 주차장 찾아줘")
        assert len(c.queries) == 1 and "완료하지 못했어요" in result.reply
        assert "찾지 못했어요" not in result.reply

    asyncio.run(run())


def test_one_course_anchor_and_corrupt_legacy_area_use_its_existing_address(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.provider = parking_provider(c)
        c.store.proposal["activities"] = [c.store.proposal["activities"][1]]
        c.store.proposal["activities"][0]["place"] = "합성식당 (서울특별시 중랑구 신내동 1)"
        c.store.context["region"] = "식사 장소"
        c.store.context["search_scope"]["area"] = "식사 장소"
        result = await c.send("이후 일정에 주변 주차장도 찾아줘")
        assert c.queries == ["중랑구 신내동 합성식당 주차장"] and result.candidates
        assert result.context.region == "중랑구 신내동"

    asyncio.run(run())


def test_retry_repairs_an_already_saved_bad_parking_turn(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=True)
        c.provider = parking_provider(c)
        c.store.context["search_scope"].update(area="식사 장소", kinds=["restaurant"])
        c.store.context["region"] = "식사 장소"
        c.store.proposal["activities"][1]["place"] = "합성식당 (서울 중랑구 신내동 1)"
        c.history = [
            {"role": "user", "content": "식사 장소 주변에 주차장 알려달라고"},
            {"role": "assistant", "content": "조건에 맞는 장소를 확인하지 못했어요."},
        ]
        result = await c.send("다시")
        assert c.queries == ["중랑구 신내동 합성식당 주차장"] and result.candidates

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "주차장은 검색하지 마",
        "주차장 기능은 뭐야?",
        '제목은 "주차장"으로',
        "주차장 말고 카페 찾아줘",
    ],
)
def test_parking_mentions_are_not_automatically_searches(text):
    assert parking_request(text) is None


async def choose_card(
    c,
    kind,
    text="선택한 장소: 합성 선택점. 정한 조건에 맞춰 코스에 반영해줘.",
    destination="합성 선택점 (서울 중랑구)",
):
    from uuid import uuid4

    if kind:
        scope = {"area": "중랑구", "kinds": [kind], "search_only": True}
        c.store.context.update(
            search_scope=scope,
            control={
                "version": 1,
                "basis": c.store.version,
                "last_action": {"operation": "search", "scope": scope},
            },
        )
    c.history.append({"role": "user", "content": text})
    body = ai_planner.ChatInput.model_validate(
        {
            "messages": c.history[-11:],
            "conversation_id": c.id,
            "request_id": str(uuid4()),
            "version": c.store.version,
            "chosen_places": [
                {"title": "합성 선택점", "address": "서울 중랑구", "destination": destination}
            ],
        }
    )
    stats = RunStats("test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(c.provider)) as client:
        result = await ai_planner._chat(
            body,
            SimpleNamespace(
                naver_search_enabled=True,
                naver_search_client_id="synthetic",
                naver_search_client_secret="synthetic",
            ),
            c.store,
            client,
            Budget(),
            stats,
        )
    assert stats.counts["model_calls"] == 0
    c.history.append({"role": "assistant", "content": result.reply})
    return result


@pytest.mark.parametrize("kind,index", [("cafe", 0), ("restaurant", 1)])
def test_card_selection_changes_only_the_destination_without_a_model(monkeypatch, kind, index):
    async def run():
        import copy

        c = Conversation(monkeypatch, proposal=True)
        expected = copy.deepcopy(c.store.proposal)
        result = await choose_card(c, kind)
        expected["activities"][index]["place"] = "합성 선택점 (서울 중랑구)"
        assert result.plan.model_dump() == expected
        assert result.reply == "선택한 장소를 코스 초안에 반영했어요."

    asyncio.run(run())


def test_card_selection_asks_for_an_ambiguous_activity_then_preserves_other_fields(monkeypatch):
    async def run():
        import copy

        c = Conversation(monkeypatch, proposal=True)
        c.store.proposal["activities"][1]["title"] = "카페"
        expected = copy.deepcopy(c.store.proposal)
        result = await choose_card(c, "cafe")
        assert result.plan is None and c.store.proposal == expected
        assert result.context.dialogue.pending.field == "target"
        result = await choose_card(c, None, text="2번 활동")
        expected["activities"][1]["place"] = "합성 선택점 (서울 중랑구)"
        assert result.plan.model_dump() == expected

    asyncio.run(run())


def test_missing_requested_activity_is_added_without_inventing_time_cost_or_metadata(monkeypatch):
    async def run():
        import copy

        c = Conversation(monkeypatch, proposal=True)
        c.store.proposal["activities"] = c.store.proposal["activities"][:1]
        expected = copy.deepcopy(c.store.proposal)
        result = await choose_card(c, "restaurant")
        assert result.plan.activities[0].model_dump() == expected["activities"][0]
        assert len(result.plan.activities) == 2 and result.plan.activities[1].title == "식사"
        assert result.plan.activities[1].time is None and result.plan.activities[1].cost is None
        assert (
            result.plan.title == expected["title"]
            and result.plan.preparation == expected["preparation"]
        )

    asyncio.run(run())


def test_first_card_and_shared_link_use_only_the_explicit_choice(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        result = await choose_card(c, "restaurant", destination="https://naver.me/EXAMPLE")
        assert len(result.plan.activities) == 1
        assert result.plan.activities[0].place == "합성 선택점"
        assert result.plan.activities[0].map_url == "https://naver.me/EXAMPLE"
        assert result.plan.activities[0].time is None and result.plan.activities[0].cost is None

    asyncio.run(run())


def test_explicit_append_and_full_course_keep_the_original_content(monkeypatch):
    async def run():
        import copy

        c = Conversation(monkeypatch, proposal=True)
        expected = copy.deepcopy(c.store.proposal)
        c.store.context["dialogue"]["append_pending"] = True
        result = await choose_card(c, "cafe")
        assert (
            result.plan.activities[:2] == ai_planner.PlanContent.model_validate(expected).activities
        )
        assert len(result.plan.activities) == 3 and result.plan.title == expected["title"]
        assert result.plan.activities[2].time is None and result.plan.activities[2].cost is None
        c.store.proposal["activities"] = [
            copy.deepcopy(expected["activities"][0]) for _ in range(8)
        ]
        c.store.context["dialogue"]["append_pending"] = True
        original = copy.deepcopy(c.store.proposal)
        result = await choose_card(c, "cafe")
        assert result.plan is None and c.store.proposal == original
        assert "최대 8개" in result.reply

    asyncio.run(run())


def test_a_mixed_search_can_be_disambiguated_by_activity_kind(monkeypatch):
    async def run():
        import copy

        c = Conversation(monkeypatch, proposal=True)
        expected = copy.deepcopy(c.store.proposal)
        result = await choose_card(c, None)
        assert result.plan is None and c.store.proposal == expected
        result = await choose_card(c, None, text="식사")
        expected["activities"][1]["place"] = "합성 선택점 (서울 중랑구)"
        assert result.plan.model_dump() == expected

    asyncio.run(run())


def test_plan_completion_describes_only_the_verified_draft_change():
    async def run():
        session = ToolSession(
            SimpleNamespace(),
            None,
            [],
            [
                SimpleNamespace(
                    title="합성 식당", address="서울 중랑구", destination="합성 식당 (서울 중랑구)"
                )
            ],
        )
        session.direct_final = True
        session.operation = "select"
        candidate = session.chosen_candidate

        def provider(_):
            value = {
                "reply": "국물 요리가 포함된 식사이며 오늘 영업 중이에요.",
                "plan": {
                    "title": "합성 코스",
                    "date": "2030-01-05",
                    "activities": [{"title": "식사", "place_ref": candidate.ref}],
                },
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(value)}}]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            result = await REAL_COMPLETE(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "선택한 장소 반영"}],
                session,
                client=client,
                budget=Budget(),
                stats=RunStats("test"),
            )
        assert result.plan and result.plan.activities[0].place == candidate.destination
        assert result.reply == "선택한 장소를 코스 초안에 반영했어요."

    asyncio.run(run())


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
