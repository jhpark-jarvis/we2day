"""Cross-product executor invariants; scripted interpretations are not model accuracy."""

import asyncio
import copy
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from test_ai_long_dialogue import PLAN, Conversation

from we2day_api.ai_control import interpret, prepare
from we2day_api.ai_planner import ChatInput, Message
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_search_spec import SearchSpec, SearchTarget, anchor_key, current_anchor
from we2day_api.plans import PlanContent

TARGETS = ["약국", "편의점", "수유실", "화장실", "피자집", "도서관"]
REFERENCES = ["식사 장소", "2번 활동", "합성식당"]


def action(targets, **extra):
    return {"operation": "search", "area": "중랑구", "targets": targets, **extra}


def source(c, targets, *, missing=(), failed=()):
    """Independent provider fixtures include unrelated same-area results."""

    def provider(request):
        query = request.url.params["query"]
        c.queries.append(query)
        target = next(t for t in targets if t in query)
        if target in failed:
            return httpx.Response(503)
        good = (
            []
            if target in missing
            else [
                {
                    "title": "합성" + target,
                    "category": target,
                    "roadAddress": "서울특별시 중랑구 신내동 1",
                }
            ]
        )
        return httpx.Response(
            200,
            json={
                "items": good
                + [
                    {
                        "title": "관련 없는 장소",
                        "category": "음식점",
                        "roadAddress": "서울특별시 중랑구 신내동 2",
                    },
                    {
                        "title": "다른 지역 " + target,
                        "category": target,
                        "roadAddress": "부산광역시 해운대구 1",
                    },
                ]
            },
        )

    return provider


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("reference", REFERENCES)
def test_targets_and_current_anchors_are_orthogonal(monkeypatch, target, reference):
    async def run():
        c = Conversation(monkeypatch)
        # Even a wrong model reference cannot overrule an unambiguous user reference.
        c.semantic_action = lambda _: action([target], anchor_ref="activity_1")
        c.provider = source(c, [target])
        before = copy.deepcopy(c.store.proposal)
        result = await c.send(f"{reference} 주변 {target} 알려주세요")
        assert c.queries == [f"중랑구 합성식당 {target}"]
        assert [p.title for p in result.candidates] == ["합성" + target]
        assert result.context.control["outcome"] == "ready"
        assert c.store.proposal == before
        await c.send("고마워")
        await c.send("다시")
        assert c.queries[-1] == f"중랑구 합성식당 {target}"

    asyncio.run(run())


@pytest.mark.parametrize("target", TARGETS)
def test_new_semantic_search_replaces_pending_title_without_renaming(monkeypatch, target):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("제목 바꿔줘")
        c.semantic_action = lambda _: action([target])
        c.provider = source(c, [target])
        result = await c.send(f"음.. {target} 추천해 주실래요?")
        assert result.candidates and c.queries == [f"중랑구 {target}"]
        assert result.context.dialogue.pending is None
        assert c.store.proposal == PLAN

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "약국 검색 취소해줘",
        "편의점 검색은 하지 마",
        "도서관 찾지 마",
        "검색 중단해줘",
    ],
)
def test_cancel_clears_action_and_retry_never_restarts_it(monkeypatch, text):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: action(["수유실"])
        c.provider = source(c, ["수유실"])
        await c.send("수유실 찾아줘")
        result = await c.send(text)
        assert len(c.queries) == 1 and not result.candidates
        assert result.context.control.get("last_action") is None
        assert c.store.context.get("place_search") is None
        result = await c.send("다시")
        assert len(c.queries) == 1 and not result.candidates
        assert c.store.proposal == PLAN

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        action(["수영장"]),
        action(["약국"], area="부산"),
        action(["https://example.org"]),
        action(["약국"], anchor_ref="activity_8"),
        action(["약국"], permissions=["write_all"]),
    ],
)
def test_invalid_model_outputs_cannot_grant_a_tool_or_mutate_a_course(monkeypatch, bad):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: bad
        result = await c.send("약국 찾아줘")
        assert not c.queries and not result.candidates
        assert result.context.dialogue.pending is not None
        assert c.store.proposal == PLAN

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "그 장소 주변 약국 찾아줘",
        "0번 주변 약국 찾아줘",
        "9번 근처 약국 찾아줘",
        "1번과 2번 주변 약국 찾아줘",
        "이후 일정에 주변 약국도 찾아줘",
    ],
)
def test_ambiguous_or_invalid_anchor_cannot_be_guessed(monkeypatch, text):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: action(["약국"], anchor_ref="activity_1")
        c.provider = source(c, ["약국"])
        result = await c.send(text)
        assert not c.queries and "어느 장소" in result.reply
        assert c.store.context["place_search"]["anchor_pending"]
        result = await c.send("2번")
        assert c.queries == ["중랑구 합성식당 약국"] and result.candidates

    asyncio.run(run())


@pytest.mark.parametrize(
    "missing,failed,outcome",
    [
        ((), (), "ready"),
        (("편의점",), (), "partial"),
        ((), ("편의점",), "partial"),
        (("약국", "편의점"), (), "empty"),
    ],
)
def test_multiple_free_targets_have_query_level_coverage(monkeypatch, missing, failed, outcome):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: action(["약국", "편의점", "약국"])
        c.provider = source(c, ["약국", "편의점"], missing=missing, failed=failed)
        result = await c.send("식사 장소 주변 약국과 편의점 찾아줘")
        assert set(c.queries) == {"중랑구 합성식당 약국", "중랑구 합성식당 편의점"}
        assert len(c.queries) == 2
        assert result.context.control["outcome"] == outcome
        assert c.store.proposal == PLAN
        if outcome == "partial":
            assert "일부 활동" in result.reply

    asyncio.run(run())


def test_anchor_identity_survives_reorder_but_not_replacement():
    plan = PlanContent.model_validate(PLAN)
    original = plan.activities[1].model_copy(deep=True)
    spec = SearchSpec(
        targets=[SearchTarget(query="어떤시설")], anchor_index=1, anchor_key=anchor_key(original)
    )
    plan.activities.reverse()
    assert current_anchor(spec, plan) == original
    plan.activities[0].place = "새로운 장소"
    assert current_anchor(spec, plan) is None
    plan.activities = [original, original]
    assert current_anchor(spec, plan) is None


def test_relation_anchor_words_cannot_be_targets_even_when_model_includes_them(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: action(["식사", "카페"])
        result = await c.send("식사 장소 주변 카페 찾아줘")
        assert result.candidates and c.queries == ["중랑구 합성식당 카페"]
        assert result.context.search_scope.kinds == ["cafe"]

    asyncio.run(run())


def test_provider_category_does_not_make_an_irrelevant_specific_target_relevant(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        c.semantic_action = lambda _: action(["피자집"])
        c.provider = source(c, ["피자집"], missing=["피자집"])
        result = await c.send("피자집 추천해 주세요")
        assert c.queries == ["중랑구 피자집"] and not result.candidates
        assert result.context.control["outcome"] == "empty"

    asyncio.run(run())


def test_recorded_minimal_interpreter_payload_has_no_inherited_genres_or_private_details():
    async def run():
        plan = PlanContent.model_validate(PLAN)
        plan.activities[1].place += " (서울특별시 중랑구 신내동 1)"
        plan.activities[1].note = "이 메모는 해석기에 전송하지 않음"
        body = ChatInput(messages=[Message(role="user", content="식사 장소 주변 약국 찾아줘")])
        decision = prepare(
            body, {"region": "중랑구", "activities": ["카페", "식사"]}, plan, date(2030, 1, 5)
        )

        def model(request):
            payload = json.loads(request.content)
            data = json.loads(payload["messages"][-1]["content"])
            assert "kinds" not in data and "신내동" not in json.dumps(data, ensure_ascii=False)
            assert "메모" not in json.dumps(data, ensure_ascii=False)
            assert [a["ref"] for a in data["activities"]] == ["activity_1", "activity_2"]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(action(["약국"], anchor_ref="activity_2"))
                            }
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
            await interpret(
                decision,
                body.messages[-1].content,
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                client,
                Budget(),
                RunStats("test"),
            )
        assert decision.directive.slots["place_search"]["query"] == "약국"

    asyncio.run(run())
