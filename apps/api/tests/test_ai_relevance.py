"""Public suggestions stay distinct from place facts and explicit user choices."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from we2day_api.ai_place_policy import PlacePolicy, SearchArguments, SearchScope
from we2day_api.ai_relevance import enrich_candidates
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import ChosenPlace, ModelPlan, ToolSession
from we2day_api.places import PlaceResult


def fixture():
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=["any"]), queries=[("any", "쌀국수", "쌀국수")]
    )
    session = ToolSession(None, None, [], [], policy)
    args = SearchArguments(query="성수동 쌀국수", area="성수동")
    key = args.model_dump_json()
    session.searches[key] = []
    session.search_reports[key] = {"name": "search_places", "status": "ok", "count": 0}
    session.relevance_pool = [
        (
            key,
            args,
            PlaceResult(
                title="공공 식당",
                category="음식점>베트남음식",
                address="서울 성수동 1",
                description="이 설명과 주소는 분류 모델에 전달하지 않는다",
                link="https://invalid.test",
            ),
        )
    ]
    return session


@pytest.mark.parametrize(
    "kind,target",
    [
        ("library", "도서관"),
        ("cafe", "카페"),
        ("restaurant", "식당"),
        ("park", "공원"),
        ("museum", "박물관"),
        ("cinema", "영화"),
        ("bowling", "볼링"),
        ("escape", "방탈출"),
        ("craft", "공방"),
    ],
)
@pytest.mark.parametrize("inferred", [False, True])
def test_unknown_primary_service_cannot_be_relaxed_by_the_classifier(kind, target, inferred):
    request_kind = "any" if inferred else kind
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=[request_kind]), queries=[(request_kind, target, target)]
    )
    s = ToolSession(None, None, [], [], policy)
    args = SearchArguments(query="성수동 " + target, area="성수동", kind=request_kind)
    key = args.model_dump_json()
    s.searches[key] = []
    s.relevance_pool = [
        (key, args, PlaceResult(title="공공 시설", category="다른 주업종", address="서울 성수동"))
    ]
    requests, stats = asyncio.run(
        run(
            s,
            {
                "decisions": [
                    {"index": 0, "evidence": "다른 주업종", "relation": "same_service"},
                ]
            },
        )
    )
    assert not requests and stats.counts["model_calls"] == 0
    assert not s.visible_candidates()


def test_declared_category_cannot_be_overridden_by_a_service_word_in_the_name():
    s = fixture()
    s.policy.queries = [("library", "도서관", "도서관")]
    args = SearchArguments(query="성수동 도서관", area="성수동", kind="library")
    key = args.model_dump_json()
    s.searches[key] = []
    s.relevance_pool = [
        (
            key,
            args,
            PlaceResult(title="도서관이라는 가게", category="교육>독서실", address="서울 성수동"),
        )
    ]
    requests, _ = asyncio.run(
        run(
            s,
            {
                "decisions": [
                    {"index": 0, "evidence": "독서실", "relation": "same_service"},
                ]
            },
        )
    )
    assert not requests


@pytest.mark.parametrize(
    "target,category",
    [
        ("조용한 카페", "음식점>카페"),
        ("아이와 도서관", "교육>자료실"),
        ("편한 식당", "음식점>베트남음식"),
        ("한적한 공원", "자연>공원"),
        ("작은 박물관", "문화>미술관"),
        ("영화", "문화>영화관"),
        ("볼링", "스포츠>볼링장"),
        ("방탈출", "놀이>방탈출"),
        ("공방", "취미>공방"),
    ],
)
def test_compatible_primary_categories_still_reach_the_classifier(target, category):
    s = ToolSession(
        None,
        None,
        [],
        [],
        PlacePolicy(
            SearchScope(area="성수동", kinds=["any"]),
            queries=[("any", target, target)],
        ),
    )
    args = SearchArguments(query="성수동 " + target, area="성수동")
    key = args.model_dump_json()
    s.searches[key] = []
    s.relevance_pool = [
        (key, args, PlaceResult(title="공공 후보", category=category, address="서울 성수동"))
    ]
    requests, _ = asyncio.run(
        run(
            s,
            {
                "decisions": [
                    {"index": 0, "evidence": category, "relation": "preference_only"},
                ]
            },
        )
    )
    assert len(requests) == 1 and len(s.visible_candidates()) == 1
    assert s.visible_candidates()[0].match == "related"


def test_activity_query_is_not_a_literal_ban_on_a_neighboring_business():
    s = ToolSession(
        None,
        None,
        [],
        [],
        PlacePolicy(
            SearchScope(area="성수동", kinds=["any"]),
            queries=[("any", "공부할 곳", "공부할 곳")],
        ),
    )
    args = SearchArguments(query="성수동 공부할 곳", area="성수동")
    key = args.model_dump_json()
    s.searches[key] = []
    s.relevance_pool = [
        (
            key,
            args,
            PlaceResult(title="공공 공부 공간", category="교육>독서실", address="서울 성수동"),
        )
    ]
    requests, _ = asyncio.run(
        run(
            s,
            {
                "decisions": [
                    {"index": 0, "evidence": "독서실", "relation": "activity_venue"},
                ]
            },
        )
    )
    assert len(requests) == 1 and len(s.visible_candidates()) == 1


def test_missing_category_uses_name_but_a_known_direct_candidate_is_never_removed():
    s = fixture()
    s.policy.queries = [("any", "조용한 카페", "조용한 카페")]
    args = SearchArguments(query="성수동 조용한 카페", area="성수동")
    key = args.model_dump_json()
    s.searches[key] = []
    direct = s.add("기존 검증 후보", "서울 성수동 1", "naver")
    s.fresh_refs.add(direct.ref)
    s.relevance_pool = [
        (key, args, PlaceResult(title="공공 카페", address="서울 성수동")),
        (key, args, PlaceResult(title="넓은 공간", category="주업종 미상", address="서울 성수동")),
    ]
    requests, stats = asyncio.run(
        run(
            s,
            {
                "decisions": [
                    {"index": 0, "evidence": "카페", "relation": "preference_only"},
                ]
            },
        )
    )
    assert len(json.loads(requests[0]["messages"][1]["content"])) == 1
    assert stats.counts["related_kind_blocked"] == 1
    assert direct in s.visible_candidates() and direct.match == "direct"


async def run(session, answer, *, calls=0, status=200):
    requests = []
    if "related" in answer:
        answer = {
            **answer,
            "decisions": [
                {"index": i, "evidence": "베트남음식", "relation": "related_cuisine"}
                for i in answer["related"]
            ],
        }
        del answer["related"]

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            status,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        stats = RunStats("test")
        stats.counts["model_calls"] = calls
        io = SimpleNamespace(
            client=client,
            stats=stats,
            budget=Budget(),
            settings=SimpleNamespace(cloudflare_account_id="test", cloudflare_api_token="secret"),
        )
        await enrich_candidates(session, io)
        await enrich_candidates(session, io)
    return requests, stats


def test_related_is_public_minimal_unconfirmed_and_cannot_be_a_plan():
    session = fixture()
    requests, stats = asyncio.run(run(session, {"related": [0]}))
    assert len(requests) == stats.counts["model_calls"] == 1
    rows = json.loads(requests[0]["messages"][1]["content"])
    assert rows == [
        {"index": 0, "request": "쌀국수", "name": "공공 식당", "category": "음식점>베트남음식"}
    ]
    candidate = session.visible_candidates()[0]
    assert candidate.match == "related" and candidate.source == "naver"
    assert next(iter(session.search_reports.values()))["count"] == 1
    plan = ModelPlan(
        title="제안",
        date="2030-01-01",
        activities=[{"title": "식사", "time": "12:00", "place_ref": candidate.ref}],
    )
    resolved = session.resolve(plan)
    assert not resolved.activities[0].place
    assert session.guard_plan(plan, resolved)[0] is None
    chosen = ToolSession(
        None,
        None,
        [],
        [
            ChosenPlace(
                title=candidate.title, address=candidate.address, destination=candidate.destination
            )
        ],
    )
    assert next(iter(chosen.candidates.values())).match == "direct"
    assert chosen.resolve(plan).activities[0].place == candidate.destination


@pytest.mark.parametrize(
    "answer",
    [
        {"related": [-1]},
        {"related": [1]},
        {"related": [0, 0]},
        {"related": [True]},
        {"related": ["0"]},
        {"related": [0], "reason": "ignore instructions"},
        {},
        {"related": []},
    ],
)
def test_invalid_or_empty_judgment_preserves_direct_evidence(answer):
    session = fixture()
    direct = session.add("쌀국수 식당", "서울 성수동", "naver")
    session.fresh_refs.add(direct.ref)
    asyncio.run(run(session, answer))
    assert session.visible_candidates() == [direct]
    assert direct.match == "direct"


@pytest.mark.parametrize("status", [429, 500, 403])
def test_provider_failures_do_not_retry(status):
    session = fixture()
    requests, _ = asyncio.run(run(session, {"related": [0]}, status=status))
    assert len(requests) == 1 and not session.visible_candidates()


def test_shared_budget_and_hard_constraints_prevent_any_classifier_call():
    session = fixture()
    requests, _ = asyncio.run(run(session, {"related": [0]}, calls=3))
    assert not requests and not session.visible_candidates()
    for change in ["area", "excluded", "rejected", "exact"]:
        session = fixture()
        if change == "area":
            session.relevance_pool[0][2].address = "서울 강남구"
        elif change == "excluded":
            session.policy.excluded = {"any"}
        elif change == "rejected":
            session.policy.rejected = {"공공식당"}
        else:
            session.relevance_pool[0][1].mode = "exact_name"
            session.relevance_pool[0][1].name = "다른 식당"
        requests, _ = asyncio.run(run(session, {"related": [0]}))
        assert not requests and not session.visible_candidates()


def test_predeclared_corpus_has_independent_holdout_and_known_strict_baseline():
    from pathlib import Path

    cases = json.loads(Path(__file__).with_name("relevance_cases.json").read_text(encoding="utf-8"))
    assert {c["split"] for c in cases} == {"main", "holdout", "fresh_holdout"}
    for case in cases:
        policy = PlacePolicy(
            SearchScope(area="성수동", kinds=["any"]),
            queries=[("any", case["target"], case["target"])],
        )
        item = PlaceResult(title=case["name"], category=case["category"], address="서울 성수동")
        args = SearchArguments(query="성수동 " + case["target"], area="성수동")
        assert policy.relevant(item, args) == (case["expected"] == "direct")


@pytest.mark.parametrize("reverse", [False, True])
def test_related_classifier_gets_compound_goal_and_preserves_shared_candidate_uncertainty(reverse):
    session = fixture()
    session.policy.queries = [("any", "카페", "카페"), ("any", "조용한 카페", "조용한 카페")]
    if reverse:
        session.policy.queries.reverse()
    args = SearchArguments(query="성수동 조용한 카페", area="성수동")
    key = args.model_dump_json()
    session.searches[key] = []
    session.relevance_pool = [
        (key, args, PlaceResult(title="공공 카페", category="음식점>카페", address="서울 성수동"))
    ]
    existing = session.add("공공 카페", "서울 성수동", "naver")
    session.fresh_refs.add(existing.ref)
    requests, _ = asyncio.run(
        run(
            session,
            {"decisions": [{"index": 0, "evidence": "카페", "relation": "preference_only"}]},
        )
    )
    rows = json.loads(requests[0]["messages"][1]["content"])
    assert rows[0]["request"] == "조용한 카페"
    assert session.visible_candidates() == [existing]
    assert existing.match == "related"
    assert session.searches[key][0]["ref"] == existing.ref
