import asyncio
import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from dialogue_evaluation import MemoryStore, grade, set_path

from we2day_api.ai_dialogue import DialogueState, analyze, merge_context
from we2day_api.ai_planner import ChatInput, _chat
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import ChosenPlace
from we2day_api.plans import PlanContent

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/ai_dialogue_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"])
def test_frozen_korean_request_control(case):
    context = copy.deepcopy(case["initial"].get("context", {}))
    proposal = (
        PlanContent.model_validate(case["initial"]["proposal"])
        if "proposal" in case["initial"]
        else None
    )
    chosen = case.get("chosen", [])
    for step in case["steps"]:
        chosen = step.get("chosen", chosen)
        directive = analyze(
            step["text"],
            context,
            proposal,
            [ChosenPlace.model_validate(p) for p in chosen],
            date(2026, 10, 27),
        )
        expected = step["expect"]
        if "patch" in expected:
            target = proposal.model_dump()
            for path, value in expected["patch"].items():
                set_path(target, path, value)
            assert directive.plan and directive.plan.model_dump() == target
        if expected.get("reply_any"):
            assert any(
                "".join(v.split()) in "".join(directive.reply.split())
                for v in expected["reply_any"]
            )
        if expected.get("no_search"):
            assert "search_places" not in directive.allowed_tools
        if expected.get("needs_search"):
            assert "search_places" in directive.allowed_tools
        for key, value in expected.get("scope", {}).items():
            assert getattr(directive.scope, key) == value
        context = merge_context(context, {}, directive)
        if directive.plan:
            proposal = directive.plan


def test_pending_edit_reloads_and_only_named_activity_changes():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze("시간만 15:00로 바꿔줘", {}, proposal, [], date(2026, 10, 27))
    state = DialogueState.model_validate_json(first.state.model_dump_json())
    second = analyze(
        "두 번째 활동", {"dialogue": state.model_dump()}, proposal, [], date(2026, 10, 27)
    )
    assert second.plan.activities[0] == proposal.activities[0]
    assert second.plan.activities[1].time == "15:00" and second.state.pending is None


def test_rejection_is_current_conversation_and_explicitly_reversible():
    first = analyze("'샘플카페A'는 제외해줘", {}, None, [], date(2026, 10, 27))
    assert first.state.rejected_places == ["샘플카페A"]
    second = analyze(
        "샘플카페A 제외 취소", {"dialogue": first.state.model_dump()}, None, [], date(2026, 10, 27)
    )
    assert not second.state.rejected_places
    assert not analyze("중랑구 카페 검색", {}, None, [], date(2026, 10, 27)).state.rejected_places


def test_explicit_date_clear_does_not_reuse_previous_plan_date():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    first = analyze(
        "날짜는 미정으로 할게", {"date": proposal.date}, proposal, [], date(2026, 10, 27)
    )
    context = merge_context({"date": proposal.date}, {}, first)
    second = analyze("코스에 반영해줘", context, proposal, [], date(2026, 10, 27))
    assert context["date"] is None and second.state.pending.field == "date"
    assert not second.plan and not second.allowed_tools


def test_unknown_future_fields_survive_without_becoming_model_conditions():
    directive = analyze("고마워", {}, None, [], date(2026, 10, 27))
    updated = merge_context(
        {"date": "2030-01-05", "future": {"opaque": True}}, {"date": None, "budget": 5}, directive
    )
    assert updated["date"] == "2030-01-05" and updated["future"] == {"opaque": True}
    assert updated.get("budget") is None


def test_deterministic_edit_uses_no_model_or_provider_reservation():
    async def run():
        case = CORPUS["cases"][0]
        store, rpc_names = MemoryStore(case), []
        original = store.rpc

        async def rpc(name, values=None):
            rpc_names.append(name)
            return await original(name, values)

        store.rpc = rpc
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected model I/O"))
        ) as client:
            result = await _chat(
                ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": case["steps"][0]["text"]}],
                        "conversation_id": "00000000-0000-0000-0000-000000000001",
                        "request_id": "00000000-0000-0000-0000-000000000002",
                    }
                ),
                SimpleNamespace(),
                store,
                client,
                Budget(),
                RunStats("test"),
            )
        assert not grade(
            case, case["steps"][0], result.model_dump(mode="json"), [], case["initial"]["proposal"]
        )
        assert (
            "reserve_ai_planner_request" not in rpc_names
            and store.context["dialogue"]["turn_version"] == 1
        )

    asyncio.run(run())


def test_evaluation_rubric_detects_unintended_edits_and_ignored_rejection():
    case = CORPUS["cases"][0]
    wrong = PlanContent.model_validate(case["initial"]["proposal"]).model_dump()
    wrong["title"] = "조용한 하루"
    wrong["activities"][0]["note"] = "unexpected rewrite"
    assert "unintended_edit_or_missing_patch" in grade(
        case, case["steps"][0], {"plan": wrong}, [], case["initial"]["proposal"]
    )
    assert "rejected_or_outside_candidate" in grade(
        {},
        {"expect": {"candidate_not": ["샘플카페A"]}},
        {"candidates": [{"title": "샘플카페A"}]},
        [],
        None,
    )


@pytest.mark.parametrize("number", ["0", "9", "12", "-1", "열"])
def test_invalid_explicit_activity_number_never_falls_back_to_another_activity(number):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(
        f"{number}번째 카페 활동 시간만 15:00로 바꿔줘", {}, proposal, [], date(2026, 10, 27)
    )
    assert result.plan is None and result.state.pending.field == "activity_time"


@pytest.mark.parametrize(
    "text,amount", [("예산만 5만으로 바꿔줘", 50000), ("예산만 2.5만원으로 수정해줘", 25000)]
)
def test_currency_units_are_preserved(text, amount):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(text, {}, proposal, [], date(2026, 10, 27))
    assert result.plan.budget == amount


@pytest.mark.parametrize("text", ["예산만 100달러로 바꿔줘", "예산만 각자 3만원으로 해줘"])
def test_ambiguous_budget_is_a_question(text):
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze(text, {}, proposal, [], date(2026, 10, 27))
    assert result.plan is None and result.state.pending.field == "budget"


def test_addition_remains_a_plan_request_and_can_be_cancelled():
    proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
    result = analyze("기존 활동 유지하고 카페 하나 추가해줘", {}, proposal, [], date(2026, 10, 27))
    assert result.intent == "plan" and "search_places" in result.allowed_tools
    assert result.state.append_pending
    cancelled = analyze(
        "취소해줘", {"dialogue": result.state.model_dump()}, proposal, [], date(2026, 10, 27)
    )
    assert cancelled.plan is None and not cancelled.state.append_pending and cancelled.reply


def test_append_restores_every_existing_activity_field_and_plan_metadata():
    from we2day_api.ai_planner import complete
    from we2day_api.ai_tools import ToolSession

    async def run():
        proposal = PlanContent.model_validate(CORPUS["cases"][0]["initial"]["proposal"])
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.previous_plan, session.append_only, session.direct_final = proposal, True, True
        old = [session.seed(a) for a in proposal.activities]
        new = session.add("샘플카페B", "서울 중랑구 동일로4", "naver")
        answer = {
            "reply": "추가",
            "plan": {
                "title": "unwanted rewrite",
                "date": "2030-01-05",
                "activities": [
                    {
                        "title": "변조된 기존 활동",
                        "time": "01:00",
                        "cost": 9999,
                        "note": "changed",
                        "place_ref": old[0].ref,
                    },
                    {"title": "새 카페", "place_ref": new.ref},
                ],
            },
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(answer)}}]}
                )
            )
        ) as client:
            result = await complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "카페 추가"}],
                session,
                client=client,
            )
        assert result.plan.activities[:2] == proposal.activities
        assert (
            result.plan.title == proposal.title and result.plan.preparation == proposal.preparation
        )
        assert len(result.plan.activities) == 3 and "샘플카페B" in result.plan.activities[-1].place

    asyncio.run(run())


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).parent / "fixtures/ai_dialogue_regressions.json").read_text(
            encoding="utf-8"
        )
    )["cases"],
    ids=lambda c: c["id"],
)
def test_supplemental_control_regressions(case):
    context = copy.deepcopy(case["initial"].get("context", {}))
    proposal = (
        PlanContent.model_validate(case["initial"]["proposal"])
        if "proposal" in case["initial"]
        else None
    )
    chosen = [ChosenPlace.model_validate(p) for p in case.get("chosen", [])]
    for step in case["steps"]:
        directive = analyze(step["text"], context, proposal, chosen, date(2026, 10, 27))
        expect = step["expect"]
        if expect.get("preserve_prefix"):
            assert directive.intent == "plan" and directive.state.append_pending
            assert "search_places" in directive.allowed_tools
        if expect.get("reply_any"):
            assert any(v in directive.reply for v in expect["reply_any"])
        if "retain_only" in expect:
            target = proposal.model_dump()
            target["activities"] = [target["activities"][i] for i in expect["retain_only"]]
            assert directive.plan and directive.plan.model_dump() == target
        context = merge_context(context, {}, directive)
        if directive.plan:
            proposal = directive.plan


def test_selected_saved_place_needs_no_guessed_region_or_unrelated_search():
    from uuid import uuid4

    async def run():
        selected_id = str(uuid4())
        case = {
            "initial": {
                "context": {"date": "2030-01-05", "future_control": "opaque-private-synthetic"}
            }
        }
        store, calls, reads = MemoryStore(case), [], []

        async def read(method, table, params):
            reads.append((method, table, params))
            return [
                {
                    "id": selected_id,
                    "label": "샘플선택장소",
                    "destination": "샘플선택장소 (서울 중랑구 신내로1)",
                }
            ]

        store.call = read

        def handler(request):
            inputs = json.loads(request.content)
            assert "opaque-private-synthetic" not in json.dumps(inputs)
            calls.append(inputs)
            if len(calls) == 1:
                assert [t["function"]["name"] for t in inputs["tools"]] == [
                    "lookup_selected_places"
                ]
                message = {
                    "tool_calls": [
                        {"function": {"name": "lookup_selected_places", "arguments": "{}"}}
                    ]
                }
            else:
                message = {
                    "content": json.dumps(
                        {
                            "reply": "선택 장소 코스",
                            "plan": {
                                "title": "합성",
                                "date": "2030-01-05",
                                "activities": [{"title": "선택 장소", "place_ref": "p1"}],
                            },
                        }
                    )
                }
            return httpx.Response(200, json={"choices": [{"message": message}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await _chat(
                ChatInput.model_validate(
                    {
                        "messages": [
                            {"role": "user", "content": "선택한 저장 장소로 코스를 만들어줘"}
                        ],
                        "selected_places": [{"source": "favorite", "id": selected_id}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                    }
                ),
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                store,
                client,
                Budget(),
                RunStats("test"),
            )
        assert result.plan.activities[0].place == "샘플선택장소 (서울 중랑구 신내로1)"
        assert len(calls) == 2 and reads[0][1] == "favorite_places"
        assert reads[0][2]["id"] == f"in.({selected_id})"

    asyncio.run(run())


@pytest.mark.parametrize(
    "text", ["그럼 양주 덕계 근처로 알아봐줘", "양주 덕계 근처로 알아봐 줄래?"]
)
def test_place_followup_explicit_area_replaces_previous_alias(text):
    context = {
        "date": "2030-01-05",
        "region": "샘플 집",
        "activities": ["카페", "식사"],
        "search_scope": {"area": "샘플 집", "kinds": ["cafe", "restaurant"]},
    }
    result = analyze(text, context, None, [], date(2026, 10, 27))
    assert result.intent == "search" and "search_places" in result.allowed_tools
    assert result.scope.area == result.slots["region"] == "양주 덕계"
    merged = merge_context(context, {}, result)
    assert merged["date"] == context["date"] and merged["activities"] == context["activities"]


@pytest.mark.parametrize(
    "text", ["추천된거야?", "추천된 거야?", "어디야?", "어딘데?", "어느 장소야?"]
)
def test_place_confirmation_and_location_questions_keep_existing_scope(text):
    context = {
        "region": "양주 덕계",
        "activities": ["카페", "식사"],
        "search_scope": {"area": "양주 덕계", "kinds": ["cafe", "restaurant"]},
    }
    result = analyze(text, context, None, [], date(2026, 10, 27))
    assert getattr(result, "place_followup", "") in {"status", "details"}
    assert result.scope.area == "양주 덕계" and result.scope.kinds == ["cafe", "restaurant"]
    assert not result.plan and not result.slots.get("activities")


@pytest.mark.parametrize(
    "text", ["검색하지 마", "찾지 말고 고마워", "추천 기능이 뭐야?", "어디야?"]
)
def test_place_words_without_request_or_context_do_not_trigger_search(text):
    result = analyze(text, {}, None, [], date(2026, 10, 27))
    assert "search_places" not in result.allowed_tools


@pytest.mark.parametrize("mode", ["normal", "empty", "failed", "partial", "legacy"])
def test_recent_five_turn_place_flow_is_grounded_without_business_writes(monkeypatch, mode):
    from uuid import uuid4

    from fastapi import HTTPException

    from we2day_api import ai_planner
    from we2day_api.places import SearchResults

    async def run():
        store = MemoryStore({"initial": {}})
        reads = []

        class Reads:
            def __init__(self, *args):
                pass

            async def perform(self, action):
                reads.append(action)
                assert action[0] == "places", "Unselected saved records must never be read"
                if mode == "failed" or mode == "partial" and "카페" in action[1]:
                    raise HTTPException(503, "place_search_unavailable")
                cafe = "카페" in action[1]
                return SearchResults.model_validate(
                    {
                        "items": []
                        if mode == "empty"
                        else [
                            {
                                "title": "샘플덕계카페" if cafe else "샘플덕계식당",
                                "category": "카페,디저트" if cafe else "음식점>한식",
                                "roadAddress": "경기도 양주시 덕계동 1",
                            },
                            {
                                "title": "다른지역카페" if cafe else "다른지역식당",
                                "category": "카페,디저트" if cafe else "음식점>한식",
                                "roadAddress": "경기도 남양주시 덕계동 1",
                            },
                        ]
                    }
                )

        monkeypatch.setattr(ai_planner, "ToolIO", Reads)
        brief = {
            "date": "2030-01-05",
            "start_time": "19:00",
            "region": "샘플 집",
            "activities": ["카페", "식사"],
            "requirements": "추울 것 같음",
        }
        utterances = [
            "입력한 조건으로 코스를 만들어줘.",
            "샘플 집 근처에서 볼거야 저장된 장소에 있어",
            "추천된거야?",
            "그럼 양주 덕계 근처로 알아봐줘",
            "어디야?",
        ]
        history, outputs = [], []
        conversation_id = str(uuid4())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("No model call needed for a bounded candidate read")
            )
        ) as client:
            for index, text in enumerate(utterances):
                history.append({"role": "user", "content": text})
                body = ChatInput.model_validate(
                    {
                        "messages": history[-11:],
                        "version": store.version,
                        "conversation_id": conversation_id,
                        "request_id": str(uuid4()),
                        **({"brief": brief} if index == 0 else {}),
                    }
                )
                stats = RunStats("test")
                result = await _chat(body, SimpleNamespace(), store, client, Budget(), stats)
                outputs.append(result)
                history.append({"role": "assistant", "content": result.reply})
                assert result.plan is None and stats.counts["model_calls"] == 0
                assert store.context["date"] == brief["date"]
                assert store.context["activities"] == brief["activities"]
                assert store.context["intake"]["data"]["start_time"] == "19:00"
                if index < 3:
                    assert not reads and not result.candidates and "체크" in result.reply
                else:
                    assert len(reads) == 2 * (index - 2)
                    assert store.context["region"] == "양주 덕계"
                    assert store.context["search_scope"]["area"] == "양주 덕계"
                    assert all("남양주" not in p.address for p in result.candidates)
                    if mode in {"normal", "legacy"}:
                        assert {p.title for p in result.candidates} == {
                            "샘플덕계카페",
                            "샘플덕계식당",
                        }
                        assert "샘플덕계카페" in result.reply and "샘플덕계식당" in result.reply
                        assert "양주시 덕계동" in result.reply
                    elif mode == "partial":
                        assert {p.title for p in result.candidates} == {"샘플덕계식당"}
                        assert "일부" in result.reply and "완료하지 못" in result.reply
                    else:
                        assert not result.candidates and "찾았" not in result.reply
                        assert (
                            "완료하지 못" if mode == "failed" else "확인하지 못"
                        ) in result.reply
                if mode == "legacy" and index == 3:
                    # The previous API lost this explicit area while treating it as chat.
                    store.context["region"] = "샘플 집"
                    store.context["search_scope"]["area"] = "샘플 집"
        assert store.proposal is None and len(outputs) == 5

    asyncio.run(run())


def test_selected_house_share_url_is_not_treated_as_a_geocoded_address(monkeypatch):
    from uuid import uuid4

    from we2day_api import ai_planner

    async def run():
        store = MemoryStore(
            {
                "initial": {
                    "context": {
                        "region": "샘플 집",
                        "activities": ["카페"],
                        "search_scope": {"area": "샘플 집", "kinds": ["cafe"]},
                    }
                }
            }
        )
        selected_id = str(uuid4())
        reads = []

        class Reads:
            def __init__(self, *args):
                pass

            async def perform(self, action):
                reads.append(action)
                assert action[0] == "data" and action[1] == "favorite_places"
                assert action[2]["id"] == f"in.({selected_id})"
                return [
                    {
                        "id": selected_id,
                        "label": "샘플 집",
                        "destination": "https://naver.me/Example12",
                    }
                ]

        monkeypatch.setattr(ai_planner, "ToolIO", Reads)
        body = ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": "근처 카페 알아봐줘"}],
                "conversation_id": str(uuid4()),
                "request_id": str(uuid4()),
                "selected_places": [{"id": selected_id, "source": "favorite"}],
            }
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No model"))
        ) as client:
            result = await _chat(body, SimpleNamespace(), store, client, Budget(), RunStats("test"))
        assert len(reads) == 1 and "동네 주소" in result.reply and result.plan is None

    asyncio.run(run())


@pytest.mark.parametrize("reply", ["카페와 식사 장소를 찾았어요.", "주변 장소를 검색했어요."])
def test_chat_cannot_claim_a_search_without_current_provider_evidence(reply):
    from we2day_api.ai_planner import complete
    from we2day_api.ai_tools import ToolSession

    async def run():
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.operation, session.direct_final, session.allowed_tools = "chat", True, set()
        answer = {"reply": reply, "plan": None, "context": {}}
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(answer)}}]}
                )
            )
        ) as client:
            result = await complete(
                SimpleNamespace(
                    cloudflare_account_id="synthetic", cloudflare_api_token="synthetic"
                ),
                [],
                session,
                client=client,
                budget=Budget(),
                stats=RunStats("test"),
            )
        assert (
            "아직 실제 장소" in result.reply
            and "찾았" not in result.reply
            and "검색했" not in result.reply
        )

    asyncio.run(run())


@pytest.mark.parametrize("text", ["추천된거야?", "어디야?"])
def test_place_followup_preserves_existing_proposal_and_needs_no_search(text):
    from we2day_api import ai_planner

    async def run():
        proposal = copy.deepcopy(CORPUS["cases"][0]["initial"]["proposal"])
        store = MemoryStore({"initial": {"context": {"region": "중랑구"}, "proposal": proposal}})
        before = copy.deepcopy(store.proposal)
        body = ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": text}],
                "conversation_id": "00000000-0000-4000-8000-000000000061",
                "request_id": "00000000-0000-4000-8000-000000000062",
            }
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No external I/O"))
        ) as client:
            result = await ai_planner._chat(
                body, SimpleNamespace(), store, client, Budget(), RunStats("test")
            )
        assert store.proposal == before and result.plan is None and "코스 제안" in result.reply
        assert all(a["place"] in result.reply for a in before["activities"] if a["place"])

    asyncio.run(run())


def test_selected_house_address_only_uses_its_public_administrative_area(monkeypatch):
    from uuid import uuid4

    from we2day_api import ai_planner
    from we2day_api.places import SearchResults

    async def run():
        store = MemoryStore(
            {
                "initial": {
                    "context": {
                        "region": "샘플 집",
                        "activities": ["카페"],
                        "search_scope": {"area": "샘플 집", "kinds": ["cafe"]},
                    }
                }
            }
        )
        selected_id = str(uuid4())
        reads = []

        class Reads:
            def __init__(self, *args):
                pass

            async def perform(self, action):
                reads.append(action)
                if action[0] == "data":
                    assert action[2]["id"] == f"in.({selected_id})"
                    return [
                        {
                            "id": selected_id,
                            "label": "샘플 집",
                            "destination": "경기도 양주시 덕계동 비공개로 999",
                        }
                    ]
                assert action[0] == "places" and action[1] == "양주시 덕계동 카페"
                return SearchResults.model_validate(
                    {
                        "items": [
                            {
                                "title": "샘플카페",
                                "category": "카페",
                                "address": "경기도 양주시 덕계동 1",
                            }
                        ]
                    }
                )

        monkeypatch.setattr(ai_planner, "ToolIO", Reads)
        body = ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": "근처 카페 알아봐줘"}],
                "conversation_id": str(uuid4()),
                "request_id": str(uuid4()),
                "selected_places": [{"id": selected_id, "source": "favorite"}],
            }
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No model"))
        ) as client:
            result = await _chat(body, SimpleNamespace(), store, client, Budget(), RunStats("test"))
        assert len(reads) == 2 and "샘플카페" in result.reply
        assert result.context.region == "양주시 덕계동" and result.plan is None
        assert "비공개로" not in result.reply

    asyncio.run(run())


@pytest.mark.parametrize(
    "previous,expected",
    [
        (
            [("user", "그럼 양주 덕계 근처로 알아봐줘"), ("assistant", "다른 곳을 찾았어요")],
            "양주 덕계",
        ),
        ([("assistant", "그럼 양주 덕계 근처로 알아봐줘")], "샘플 집"),
        (
            [("user", "그럼 양주 덕계 근처로 알아봐줘"), ("user", "다시 샘플 집 근처로 할게")],
            "샘플 집",
        ),
    ],
)
def test_followup_can_repair_old_alias_state_only_from_latest_explicit_user_area(
    previous, expected
):
    from we2day_api.ai_place_answers import recover_followup_area
    from we2day_api.ai_planner import Message as ChatMessage

    context = {
        "region": "샘플 집",
        "search_scope": {"area": "샘플 집", "kinds": ["cafe", "restaurant"]},
    }
    directive = analyze("어디야?", context, None, [], date(2026, 10, 27))
    recover_followup_area(
        directive, [ChatMessage(role=role, content=text) for role, text in previous]
    )
    assert directive.scope.area == expected
    assert directive.slots.get("region", "샘플 집") == expected


def test_place_completion_guard_does_not_rewrite_weather_tool_answers():
    from we2day_api.ai_planner import complete
    from we2day_api.ai_tools import ToolSession

    async def run():
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.operation, session.direct_final, session.allowed_tools = "weather", True, set()
        reply = "도시 날씨를 검색했어요. 도시 예보를 확인해 주세요."
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {"reply": reply, "plan": None, "context": {}}
                                    )
                                }
                            }
                        ]
                    },
                )
            )
        ) as client:
            result = await complete(
                SimpleNamespace(
                    cloudflare_account_id="synthetic", cloudflare_api_token="synthetic"
                ),
                [],
                session,
                client=client,
                budget=Budget(),
                stats=RunStats("test"),
            )
        assert result.reply == reply

    asyncio.run(run())
