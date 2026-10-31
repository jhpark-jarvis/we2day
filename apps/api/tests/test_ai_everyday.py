"""Ordinary user intent contracts, independent of the provider's prose."""

import asyncio
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from everyday_evaluation import assess
from test_ai_long_dialogue import Conversation

from we2day_api.ai_control import prepare
from we2day_api.ai_conversation_hints import guidance
from we2day_api.ai_place_policy import PlacePolicy, SearchScope, explicit_area
from we2day_api.ai_planner import ChatInput, Message
from we2day_api.ai_search_spec import semantic_request
from we2day_api.ai_tools import ToolSession
from we2day_api.places import SearchResults

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/ai_everyday_cases.json").read_text(encoding="utf-8")
)
DETERMINISTIC = {
    "U04",
    "U06",
    "U07",
    "U08",
    "U09",
    "U11",
    "U12",
    "U13",
    "U14",
    "U15",
    "U19",
    "H03",
    "H04",
}


@pytest.mark.parametrize(
    "case", [c for c in CORPUS["cases"] if c["id"] in DETERMINISTIC], ids=lambda c: c["id"]
)
def test_ordinary_conditions_are_applied_before_claiming_completion(monkeypatch, case):
    async def run():
        c = Conversation(monkeypatch)
        if not case["initial"].get("proposal"):
            c.store.context, c.store.proposal = {}, None
        before = c.store.proposal
        step = case["steps"][0]
        result = await c.send(step["text"])
        c.store.queries = c.queries
        c.store.events = ["places"] * len(c.queries)
        assert assess(case, step, result.model_dump(mode="json"), c.store, before) == []
        assert "reserve_ai_planner_request" not in c.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "text,budget",
    [
        ("2030-01-05에 성수동에서 5만원으로 카페 코스 짜줘", 50000),
        ("2030-01-05에 성수동에서 5만으로 카페 코스 짜줘", 50000),
        ("2030-01-05 성수동에서 도서관 코스, 총 0원 이내로 만들어줘", 0),
    ],
)
def test_total_amount_without_a_budget_label_is_user_supplied(text, budget):
    decision = prepare(
        ChatInput(messages=[Message(role="user", content=text)]), {}, None, date(2026, 10, 31)
    )
    assert decision.directive.slots["budget"] == budget


@pytest.mark.parametrize("area", ["대신동", "대신면", "중랑구"])
def test_discourse_markers_inside_a_place_name_do_not_split_the_area(area):
    text = area + " 근처 카페 찾아줘"
    assert explicit_area(text) == area
    d = prepare(
        ChatInput(messages=[Message(role="user", content=text)]), {}, None, date(2026, 10, 31)
    )
    assert not semantic_request(text, d.directive, None, {})


@pytest.mark.parametrize(
    "text", ["제목은 '영업 중이야?'로 바꿔줘", "이 코스는 어디서 시작해?", "지금 예산이 얼마야?"]
)
def test_capability_hints_do_not_swallow_a_condition_or_itinerary_question(text):
    assert not guidance(text)


def test_overlapping_provider_results_cannot_relabel_a_cafe_as_a_meal(monkeypatch):
    from we2day_api import ai_tools

    rows = SearchResults.model_validate(
        {
            "items": [
                {
                    "title": "예시카페",
                    "category": "음식점>카페",
                    "roadAddress": "서울 중랑구 신내동 1",
                },
                {
                    "title": "예시식당",
                    "category": "음식점>한식",
                    "roadAddress": "서울 중랑구 신내동 2",
                },
            ]
        }
    )
    monkeypatch.setattr(ai_tools, "fetch_places", lambda *args: rows)
    session = ToolSession(
        SimpleNamespace(),
        None,
        [],
        [],
        PlacePolicy(SearchScope(area="중랑구", kinds=["cafe", "restaurant"])),
    )
    for kind, query in [("cafe", "카페"), ("restaurant", "식당")]:
        result = session.execute("search_places", {"kind": kind, "query": query, "area": "중랑구"})
        assert len(result["items"]) == 1
    actual = {p.title: session.candidate_kinds[p.ref] for p in session.visible_candidates()}
    assert actual == {"예시카페": "cafe", "예시식당": "restaurant"}
