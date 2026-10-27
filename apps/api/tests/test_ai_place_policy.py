"""Adversarial provider results and explicit user constraints, independent of model obedience."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from we2day_api.ai_place_policy import PlacePolicy, SearchArguments, SearchScope, requested_scope
from we2day_api.ai_planner import ANSWER_FORMAT, answer_format, explicit_date
from we2day_api.ai_tools import ModelAnswer, ModelPlan, ToolSession
from we2day_api.places import PlaceResult, SearchResults
from we2day_api.plans import PlanContent


@pytest.mark.parametrize(
    "text",
    [
        "서울숲 산책 검색해줘",
        "검색어는 서울숲 한 단어로 다시 검색",
        "'서울숲'을 찾아줘",
        "서울숲에서 산책하고 싶어. 정확히 서울숲 후보만 검색해줘.",
    ],
)
def test_exact_name_removes_activity_words(text):
    policy = PlacePolicy(requested_scope(text), text)
    args, error = policy.prepare({"query": "서울숲 산책", "kind": "park"})
    assert error is None and args.query == args.name == "서울숲" and args.mode == "exact_name"
    assert policy.relevant(PlaceResult(title="<b>서울숲</b>", category="자연,공원>도시공원"), args)
    for title, category in [
        ("서울숲 카페", "카페"),
        ("언더스탠드에비뉴", "복합문화공간"),
        ("서울숲", "음식점"),
    ]:
        assert not policy.relevant(PlaceResult(title=title, category=category), args)


@pytest.mark.parametrize(
    "text",
    [
        "중랑구 도서관 후보만 찾아줘. 카페는 나중에",
        "중랑구 도서관만 검색. 샌드위치는 검색하지 마",
        "우선 도서관만, 카페는 나중에",
    ],
)
def test_current_scope_blocks_unrequested_provider_reads(text):
    scope = requested_scope(text)
    assert scope.kinds == ["library"] and scope.search_only
    policy = PlacePolicy(scope, text)
    assert policy.prepare({"query": "중랑구 카페", "kind": "cafe"})[1] == "outside_requested_scope"
    args, error = policy.prepare({"query": "중랑구 도서관", "kind": "library"})
    assert error is None
    if scope.area:
        assert policy.relevant(
            PlaceResult(
                title="중랑도서관", category="교육>도서관", roadAddress="서울특별시 중랑구 망우로1"
            ),
            args,
        )
        assert not policy.relevant(
            PlaceResult(title="중랑도서관", category="도서관", address="서울 강남구"), args
        )
    assert not policy.relevant(
        PlaceResult(title="도서관 카페", category="음식점>카페", address="서울 중랑구"), args
    )


def test_scope_round_trip_change_and_no_plan_negation():
    scope = requested_scope("중랑구 도서관 후보만 검색")
    restored = SearchScope.model_validate_json(scope.model_dump_json())
    assert requested_scope("다른 후보 보여줘", restored).kinds == ["library"]
    changed = requested_scope("이제 주변 카페도 찾아줘", restored)
    assert changed.kinds == ["cafe"] and changed.area == "중랑구" and not changed.exact_name
    assert requested_scope("코스는 아직 만들지 마", changed).search_only
    assert not requested_scope("이제 코스를 만들어줘", changed).search_only
    assert requested_scope("도서관 말고 카페만 찾아줘", restored).kinds == ["cafe"]
    from we2day_api.ai_tools import ChosenPlace

    chosen = requested_scope("선택한 장소: 서울숲", restored, [ChosenPlace(title="서울숲")])
    assert chosen.exact_name == "서울숲" and not chosen.search_only
    assert PlacePolicy(chosen).accepts("서울숲")


def test_unsupported_invented_name_or_area_is_not_a_search_input():
    policy = PlacePolicy(user_text="서울에서 공원 찾아줘")
    assert policy.prepare({"query": "가짜 공원", "mode": "exact_name", "name": "가짜 공원"})[1]
    assert policy.prepare({"query": "서울 공원", "area": "부산광역시"})[1]
    with pytest.raises(ValidationError):
        SearchArguments.model_validate({"query": "서울", "url": "https://private.invalid"})
    current = PlacePolicy(SearchScope(area="성수동"), "중랑구에서 찾다가 성수동으로 변경")
    args, error = current.prepare({"query": "중랑구 카페", "area": "중랑구"})
    assert error is None and args.area == current.scope.area == "성수동"
    nearby = PlacePolicy(user_text="선택한 장소 주변 카페")
    args, error = nearby.prepare(
        {"query": "망우동 카페", "area": "망우동"}, ["서울 중랑구 망우동 1"]
    )
    assert error is None and args.area == "망우동"


def test_generic_kind_is_not_an_exact_venue_and_area_is_in_query():
    policy = PlacePolicy(requested_scope("중랑구 도서관 후보만 검색"))
    args, error = policy.prepare({"query": "도서관", "mode": "exact_name", "name": "도서관"})
    assert error is None and args.mode == "category" and args.name == ""
    assert args.query == "중랑구 도서관"
    assert policy.relevant(
        PlaceResult(title="중랑구립정보도서관", category="군구립도서관", address="서울 중랑구"),
        args,
    )


def run(scope):
    return ToolSession(SimpleNamespace(), None, [], [], PlacePolicy(scope))


def model(activities):
    return ModelPlan(title="합성", date="2030-01-01", activities=activities)


def test_scope_checked_before_network_and_results_not_persisted(monkeypatch):
    from we2day_api import ai_tools

    seen = []

    def fetch(settings, query):
        seen.append(query)
        return SearchResults(
            items=[
                {"title": "중랑도서관", "category": "도서관", "address": "서울 중랑구"},
                {"title": "중랑구 도서관 카페", "category": "카페", "address": "서울 중랑구"},
            ]
        )

    monkeypatch.setattr(ai_tools, "fetch_places", fetch)
    session = run(requested_scope("중랑구 도서관 후보만 검색"))
    assert session.execute("search_places", {"query": "중랑구 카페", "kind": "cafe"})["error"]
    assert not seen
    result = session.execute("search_places", {"query": "중랑구 도서관", "kind": "library"})
    assert len(result["items"]) == 1 and len(session.visible_candidates()) == 1
    assert "category" not in result["items"][0] and len(seen) == 1
    proposal = model([{"title": "도서관", "place_ref": "p1"}])
    assert session.guard_plan(proposal, session.resolve(proposal))[0] is None


def test_new_outside_activity_rejected_existing_activity_and_edits_preserved():
    session = run(SearchScope(kinds=["library"]))
    ref = session.add("중랑도서관", "서울 중랑구", "naver").ref
    session.candidate_kinds[ref] = "library"
    bad = model([{"title": "도서관에서 카페", "place_ref": ref}])
    assert session.guard_plan(bad, session.resolve(bad))[0] is None
    session.previous_plan = PlanContent(
        title="기존", date="2030-01-01", activities=[{"title": "카페", "place": "직접 선택한 카페"}]
    )
    old = session.seed(session.previous_plan.activities[0])
    updated = model(
        [
            {"title": "카페", "place_ref": old.ref, "time": "14:00"},
            {"title": "도서관", "place_ref": ref},
        ]
    )
    assert session.guard_plan(updated, session.resolve(updated))[0] is not None
    session.policy.scope.single_activity = True
    assert session.guard_plan(updated, session.resolve(updated))[0] is None


def test_exact_place_without_verified_candidate_cannot_become_a_new_plan():
    session = run(requested_scope("서울숲 산책 코스를 만들어줘"))
    proposal = model([{"title": "서울숲 산책", "place_ref": "invented"}])
    assert session.guard_plan(proposal, session.resolve(proposal))[0] is None


def test_schema_is_recursive_strict_nullable_and_excludes_server_scope():
    schema = ANSWER_FORMAT["json_schema"]["schema"]
    assert ANSWER_FORMAT["type"] == "json_schema"
    assert "title" in schema["$defs"]["ModelPlan"]["properties"]
    assert "search_scope" not in str(schema)

    def check(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(schema)
    valid = ModelAnswer(reply="확인", plan=model([{"title": "도서관", "time": None, "cost": None}]))
    assert valid.plan.activities[0].cost is None
    with pytest.raises(ValidationError):
        ModelAnswer.model_validate({"reply": "확인", "context": {"search_scope": {}}})
    with pytest.raises(ValidationError):
        ModelAnswer.model_validate(
            {"reply": "확인", "plan": {"title": "합성", "date": "2030-02-30"}}
        )


def test_explicit_dates_and_required_plan_schema_are_bound_to_user_input():
    assert explicit_date("합성 2030-01-01 검색만") == "2030-01-01"
    assert explicit_date("2030년 1월 1일") == "2030-01-01"
    assert explicit_date("2030-02-30") is None
    assert explicit_date("2030-01-01 또는 2030-01-02") is None
    assert explicit_date("내일") is None
    schema = answer_format("2030-01-01")["json_schema"]["schema"]
    assert schema["properties"]["plan"] == {"$ref": "#/$defs/ModelPlan"}
    assert schema["$defs"]["ModelPlan"]["properties"]["date"]["const"] == "2030-01-01"


@pytest.mark.parametrize(
    "area,address,expected",
    [
        ("양주 덕계", "경기도 양주시 덕계동 1", True),
        ("양주 덕계", "경기도 남양주시 덕계동 1", False),
        ("양주 덕계", "경기도 양주시 옥정동 1", False),
        ("성수", "서울특별시 성동구 성수동1가 1", True),
    ],
)
def test_user_area_shorthand_matches_whole_administrative_tokens(area, address, expected):
    scope = SearchScope(area=area, kinds=["cafe"])
    args = SearchArguments(query=f"{area} 카페", area=area, kind="cafe")
    item = PlaceResult(title="샘플카페", category="카페,디저트", address=address)
    assert PlacePolicy(scope).relevant(item, args) is expected
