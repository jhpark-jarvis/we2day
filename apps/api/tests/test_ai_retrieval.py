"""Goal grounding and provider retrieval are independent, bounded contracts."""

import asyncio
import json
from datetime import date

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from we2day_api.ai_capability_router import PlaceSelectionArguments, apply_selection
from we2day_api.ai_control import Action, apply_action, prepare
from we2day_api.ai_planner import ChatInput
from we2day_api.ai_retrieval import plan_retrieval
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_search_spec import (
    CategoryHint,
    SearchSpec,
    SearchTarget,
    saved_spec,
    search_queries,
)
from we2day_api.ai_selection import Selection
from we2day_api.config import Settings

GOALS = [
    ("library", "읽을 만한 공간", "도서관"),
    ("restaurant", "먹을 만한 곳", "식당"),
    ("cafe", "마실 만한 곳", "카페"),
    ("park", "잠깐 걸을 곳", "공원"),
    ("museum", "작품을 감상할 곳", "박물관"),
    ("cinema", "영상을 관람할 곳", "영화"),
    ("bowling", "공을 굴리는 운동", "볼링"),
    ("escape", "수수께끼를 풀 공간", "방탈출"),
    ("craft", "손으로 만들 체험", "공방"),
]


@pytest.mark.parametrize("kind,goal,keyword", GOALS)
def test_each_category_uses_a_server_keyword_and_retains_the_original_goal(kind, goal, keyword):
    spec = SearchSpec(targets=[SearchTarget(kind=kind, query=goal, category_retrieval=True)])
    assert search_queries(spec, None) == [(kind, keyword, goal)]
    persisted = spec.model_dump()
    assert persisted["targets"][0]["query"] == goal
    restored = saved_spec({"place_search": persisted})
    assert restored and search_queries(restored, None) == [(kind, keyword, goal)]


@pytest.mark.parametrize("kind,goal,keyword", GOALS)
def test_native_hints_are_grounded_and_do_not_reuse_old_exact_name(kind, goal, keyword):
    body = ChatInput(messages=[{"role": "user", "content": f"성수동 {goal} 추천해줘"}])
    decision = prepare(
        body,
        {
            "region": "성수동",
            "search_scope": {
                "area": "성수동",
                "exact_name": "이전 선택 장소",
            },
        },
        None,
        date(2030, 1, 1),
    )
    selection = Selection(
        calls=[
            (
                "search_places",
                PlaceSelectionArguments(
                    query=goal,
                    targets=[goal],
                    area="성수동",
                    category_hints=[CategoryHint(query=goal, kind=kind)],
                ).model_dump(),
            )
        ]
    )
    apply_selection(selection, decision, body.messages[-1].content)
    spec = saved_spec({"place_search": decision.directive.slots.get("place_search")})
    assert spec and search_queries(spec, None) == [(kind, keyword, goal)]
    assert not decision.directive.scope.exact_name
    assert decision.directive.scope.area == "성수동"


@pytest.mark.parametrize("query", ["쌀국수", "커피", "샘플도서관", "약국"])
def test_literal_names_menus_and_unlisted_facilities_keep_their_old_wire_shape(query):
    spec = SearchSpec(targets=[SearchTarget(query=query)])
    assert search_queries(spec, None) == [("any", query, query)]
    assert "category_retrieval" not in spec.model_dump()["targets"][0]


@pytest.mark.parametrize(
    "goal,hint,kind",
    [
        ("카페", "카페", "library"),  # Contradicts an explicit kind.
        ("커피", "없는 목표", "cafe"),  # Not a current grounded goal.
        ("카페", "카페", "cafe"),  # Quoted exact keyword is literal.
    ],
)
def test_category_interpretation_cannot_replace_explicit_constraints(goal, hint, kind):
    text = f"성수동 ‘{goal}’ 검색해줘"
    decision = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    apply_action(
        decision,
        text,
        Action(
            operation="search",
            area="성수동",
            targets=[goal],
            category_hints=[{"query": hint, "kind": kind}],
        ),
    )
    assert not decision.directive.allowed_tools
    assert decision.directive.state.pending


def test_category_retrieval_has_no_arbitrary_or_any_category():
    with pytest.raises(ValidationError):
        SearchTarget.model_validate({"query": "새 목표", "kind": "any", "category_retrieval": True})
    with pytest.raises(ValidationError):
        CategoryHint.model_validate({"query": "새 목표", "kind": "unknown"})


@pytest.mark.parametrize("hint", [False, True])
@pytest.mark.parametrize("kind,goal,keyword", GOALS)
def test_missing_native_hint_is_resolved_as_a_bounded_semantic_class(kind, goal, keyword, hint):
    text = f"성수동 {goal} 찾아줘"
    control = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    args = PlaceSelectionArguments(
        query=goal,
        targets=[goal],
        area="성수동",
        category_hints=[{"query": goal, "kind": "any"}] if hint else [],
    )
    apply_selection(Selection(calls=[("search_places", args.model_dump())]), control, text)
    stats = RunStats("test")

    def provider(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema" and body["max_tokens"] == 384
        assert json.loads(body["messages"][1]["content"]) == [{"index": 0, "goal": goal}]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"decisions": [{"index": 0, "kind": kind}]})
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            await plan_retrieval(control, Settings(_env_file=None), client, Budget(), stats)

    asyncio.run(run())
    spec = saved_spec({"place_search": control.directive.slots["place_search"]})
    assert search_queries(spec, None) == [(kind, keyword, goal)]
    assert stats.counts["model_calls"] == 1


@pytest.mark.parametrize("code", [3036, 3040])
def test_retrieval_quota_is_not_reinterpreted_as_missing_user_information(code):
    text = "성수동 먹을 만한 곳 찾아줘"
    control = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    apply_action(control, text, Action(operation="search", area="성수동", targets=["먹을 만한 곳"]))
    before = control.directive.slots["place_search"]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, json={"errors": [{"code": code}]})
            )
        ) as client:
            await plan_retrieval(
                control, Settings(_env_file=None), client, Budget(), RunStats("test")
            )

    with pytest.raises(HTTPException) as error:
        asyncio.run(run())
    assert error.value.detail == ("ai_provider_limited" if code == 3036 else "ai_provider_busy")
    assert control.directive.slots["place_search"] == before


def test_explicit_native_exact_name_keeps_the_hard_name_constraint():
    text = "성수동 ‘샘플도서관’ 정확한 이름으로 검색해줘"
    control = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    selection = Selection(
        calls=[
            (
                "search_places",
                PlaceSelectionArguments(
                    query="샘플도서관",
                    targets=["샘플도서관"],
                    name="샘플도서관",
                    mode="exact_name",
                    area="성수동",
                ).model_dump(),
            )
        ]
    )
    apply_selection(selection, control, text)
    assert control.directive.scope.exact_name == "샘플도서관"


def test_single_syllable_goal_is_only_grounded_with_a_concrete_category():
    text = "성수동 밥 추천해줘"
    control = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    apply_action(
        control,
        text,
        Action(
            operation="search",
            area="성수동",
            targets=["밥"],
            category_hints=[{"query": "밥", "kind": "restaurant"}],
        ),
    )
    spec = saved_spec({"place_search": control.directive.slots["place_search"]})
    assert search_queries(spec, None) == [("restaurant", "식당", "밥")]


def test_neutral_hint_does_not_hide_an_existing_native_concrete_kind():
    text = "성수동 읽을 만한 공간 찾아줘"
    control = prepare(
        ChatInput(messages=[{"role": "user", "content": text}]), {}, None, date(2030, 1, 1)
    )
    args = PlaceSelectionArguments(
        query="읽을 만한 공간",
        targets=["읽을 만한 공간"],
        area="성수동",
        kind="library",
        category_hints=[{"query": "읽을 만한 공간", "kind": "any"}],
    )
    apply_selection(Selection(calls=[("search_places", args.model_dump())]), control, text)
    spec = saved_spec({"place_search": control.directive.slots["place_search"]})
    assert search_queries(spec, None) == [("library", "도서관", "읽을 만한 공간")]
