"""Overlapping words must not turn one requested search into another."""

import asyncio
from types import SimpleNamespace

import pytest

from we2day_api.ai_place_answers import read_candidate_request
from we2day_api.ai_place_policy import PlacePolicy, SearchArguments, SearchScope
from we2day_api.ai_tools import ToolSession
from we2day_api.places import PlaceResult, SearchResults


@pytest.mark.parametrize(
    "kind,short,long,category",
    [
        ("any", "카페", "조용한 카페", "음식점>카페"),
        ("library", "도서관", "어린이 도서관", "교육>도서관"),
        ("restaurant", "식당", "채식 식당", "음식점>식당"),
        ("any", "공연", "야외 공연", "문화>공연장"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_compound_goal_keeps_its_own_requirements(kind, short, long, category, reverse):
    queries = [(kind, short, short), (kind, long, long)]
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=[kind]), queries=queries[::-1] if reverse else queries
    )
    item = PlaceResult(title="공공 장소", category=category, address="서울 성수동")
    args, error = policy.prepare({"query": long, "kind": kind})
    assert error is None
    assert not policy.relevant(item, args)
    short_args, error = policy.prepare({"query": short, "kind": kind})
    assert error is None and policy.relevant(item, short_args)


def test_a_successful_compound_query_does_not_complete_an_empty_short_query():
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=["cafe"]),
        queries=[("cafe", "카페", "카페"), ("cafe", "조용한 카페", "조용한 카페")],
    )
    session = ToolSession(None, None, [], [], policy)
    session.operation = "search"
    directive = SimpleNamespace(reply="", intent="search", place_followup="", slots={}, notices=[])

    class IO:
        async def perform(self, action):
            assert action[0] == "places"
            return SearchResults(
                items=[PlaceResult(title="조용한 카페", category="카페", address="서울 성수동")]
                if "조용한" in action[1]
                else []
            )

    asyncio.run(read_candidate_request(directive, session, IO()))
    assert session.resolution == "partial"
    assert "일부 활동" in directive.reply
    assert "일부" in directive.reply.splitlines()[0]


def test_unrecognized_query_cannot_use_a_known_broad_kind_as_evidence():
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=["cafe"]), queries=[("cafe", "조용한 카페", "조용한 카페")]
    )
    args = SearchArguments(query="성수동 전혀 다른 질의", kind="cafe", area="성수동")
    assert not policy.relevant(
        PlaceResult(title="커피", category="카페", address="서울 성수동"), args
    )


@pytest.mark.parametrize("prefix", ["", "공공 기준점 ", "공공로 "])
def test_binding_handles_area_anchor_and_fallback_without_substring_matches(prefix):
    queries = [("any", prefix + "카페", "카페"), ("any", prefix + "조용한 카페", "조용한 카페")]
    policy = PlacePolicy(SearchScope(area="성수동", kinds=["any"]), queries=queries)
    for kind, query, target in queries:
        args, error = policy.prepare({"query": query, "kind": kind})
        assert error is None and policy.query_target(args) == (kind, target)
    policy.scope.area = "연남동"
    args, error = policy.prepare({"query": prefix + "조용한 카페", "kind": "any"})
    assert error is None and args.query.startswith("연남동 ")
    assert policy.query_target(args) == ("any", "조용한 카페")


def test_truncated_or_conflicting_queries_fail_closed_without_list_order():
    area = "가" * 98
    policy = PlacePolicy(
        SearchScope(area=area, kinds=["any"]),
        queries=[("any", "카페", "카페"), ("any", "카누", "카누")],
    )
    args, error = policy.prepare({"query": "카페", "kind": "any"})
    assert error is None and len(args.query) == 100
    assert policy.query_target(args) is None
    policy.queries = [("any", "카페", "한 목표"), ("any", "카페", "다른 목표")]
    assert policy.query_target(args) is None
