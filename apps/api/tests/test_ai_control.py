"""Conversation control acceptance: transitions and actual I/O, never user data."""

import asyncio
import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore

from we2day_api import ai_planner
from we2day_api.ai_control import interpret, prepare, state_at
from we2day_api.ai_dialogue import analyze, merge_context
from we2day_api.ai_intake import PlanningBrief, start_brief
from we2day_api.ai_place_policy import PlacePolicy, SearchScope
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tool_runtime import execute_batch
from we2day_api.ai_tools import ModelPlan, ToolSession

BRIEF = dict(
    date="2030-01-05",
    start_time="13:00",
    end_time="19:00",
    region="중랑구",
    activities=["카페", "식사"],
)


def context():
    return merge_context({}, {}, start_brief(PlanningBrief(**BRIEF), {}))


async def turn(monkeypatch, text, *, initial=None, selected=False, brief=None, history=()):
    store = MemoryStore(
        {"initial": {"context": copy.deepcopy(initial if initial is not None else context())}}
    )
    identifier, events = str(uuid4()), []

    async def read(method, table, params):
        events.append(("selected", table))
        assert params["id"] == f"in.({identifier})"
        return [{"id": identifier, "label": "샘플 집", "destination": "서울특별시 중랑구 신내동 1"}]

    async def completion(settings, messages, session, **kwargs):
        events.append(("model", session.operation))
        return ai_planner.ChatResult(reply="합성 대화 응답")

    def provider(request):
        assert request.url.host == "naverapihub.apigw.ntruss.com"
        events.append(("search", request.url.params["query"]))
        query = request.url.params["query"]
        kind = "카페" if "카페" in query else "음식점"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": f"샘플{kind}",
                        "category": kind,
                        "roadAddress": "서울특별시 "
                        + ("성동구 성수동" if "성수동" in query else "중랑구 신내동")
                        + " 1",
                    }
                ]
            },
        )

    store.call = read
    monkeypatch.setattr(ai_planner, "complete", completion)
    payload = dict(
        messages=[*history, {"role": "user", "content": text}],
        conversation_id=str(uuid4()),
        request_id=str(uuid4()),
        version=0,
    )
    if selected:
        payload["selected_places"] = [{"source": "favorite", "id": identifier}]
    if brief:
        payload["brief"] = brief
    settings = SimpleNamespace(
        naver_search_enabled=True,
        naver_search_client_id="synthetic",
        naver_search_client_secret="synthetic",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        answer = await ai_planner._chat(
            ai_planner.ChatInput.model_validate(payload),
            settings,
            store,
            client,
            Budget(),
            RunStats("test"),
        )
    return answer, events


@pytest.mark.parametrize("text", ["근처 식사랑 카페", "근처 카페하고 밥집", "카페 알아봐"])
def test_contextual_search_reaches_real_tool(monkeypatch, text):
    answer, events = asyncio.run(turn(monkeypatch, text, selected=True))
    assert any(e[0] == "search" for e in events)
    assert any(t["name"] == "search_places" for t in answer.tools)
    assert answer.context.region == "중랑구"


def test_mixed_time_and_search_are_both_processed(monkeypatch):
    answer, events = asyncio.run(
        turn(monkeypatch, "종료 시간은 20:00로 바꾸고 성수동 근처 카페를 찾아줘")
    )
    assert answer.context.intake.data.end_time == "20:00"
    assert answer.context.region == "성수동"
    assert any(e[0] == "search" for e in events)


@pytest.mark.parametrize(
    "resume,text,intent", [("search", "코스 만들어줘", "plan"), ("plan", "고마워", "chat")]
)
def test_explicit_request_and_smalltalk_win_over_pending(resume, text, intent):
    before = context()
    before["dialogue"]["pending"] = {"field": "region", "value": "", "resume": resume}
    result = analyze(text, before, None, [], date(2026, 10, 28))
    assert result.intent == intent
    if intent == "chat":
        assert not result.allowed_tools
        assert result.state.pending and result.state.pending.resume == resume


def test_selected_correction_resolves_requested_record(monkeypatch):
    before = context()
    before["region"] = before["search_scope"]["area"] = "샘플 집"
    answer, events = asyncio.run(
        turn(monkeypatch, "저장 장소에 체크했잖아.", initial=before, selected=True)
    )
    assert any(e[0] == "selected" for e in events)
    assert any(e[0] == "search" for e in events)
    assert "확인되지 않았" not in answer.reply


def test_legacy_area_repaired_for_ordinary_recommendation(monkeypatch):
    before = context()
    before["region"] = before["search_scope"]["area"] = "샘플 집"
    history = [
        {"role": "user", "content": "그럼 성수동 근처로 알아봐줘"},
        {"role": "assistant", "content": "합성 과거 답변"},
    ]
    answer, events = asyncio.run(
        turn(monkeypatch, "식사랑 카페 추천", initial=before, history=history)
    )
    assert answer.context.region == "성수동"
    assert any(e[0] == "search" for e in events)


def test_selected_only_intake_reads_before_requesting_region(monkeypatch):
    answer, events = asyncio.run(
        turn(
            monkeypatch,
            "조건",
            initial={},
            selected=True,
            brief={**BRIEF, "region": "", "activities": ["카페"]},
        )
    )
    assert any(e[0] == "selected" for e in events)
    assert not any(e[0] == "search" for e in events)
    assert not (
        answer.context.dialogue.pending and answer.context.dialogue.pending.field == "region"
    )


def test_network_failure_remains_failure_on_request_local_reuse():
    async def run():
        session = ToolSession(
            SimpleNamespace(), None, [], [], PlacePolicy(SearchScope(area="중랑구", kinds=["cafe"]))
        )
        session.allowed_tools = {"search_places"}

        class IO:
            async def perform(self, action):
                raise httpx.ConnectError("synthetic")

        call = {
            "function": {
                "name": "search_places",
                "arguments": json.dumps({"query": "중랑구 카페", "area": "중랑구", "kind": "cafe"}),
            }
        }
        first = (await execute_batch(session, [call], IO()))[0]
        second = (await execute_batch(session, [call], IO()))[0]
        assert first.get("error") == second.get("error") == "tool_unavailable"
        assert len(session.reports) == 1

    asyncio.run(run())


HOLDOUT = json.loads(
    (Path(__file__).parent / "fixtures/ai_control_holdout.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", HOLDOUT, ids=lambda row: row["text"])
def test_frozen_paraphrase_holdout(case):
    body = ai_planner.ChatInput.model_validate(
        {"messages": [{"role": "user", "content": case["text"]}]}
    )
    decision = prepare(body, context(), None, date(2026, 10, 28))
    result = decision.directive
    assert ("search_places" in result.allowed_tools) == case["search"]
    if "kinds" in case:
        assert set(result.scope.kinds) == set(case["kinds"])
    if "area" in case:
        assert result.scope.area == case["area"]


def test_new_control_is_versioned_and_contains_no_selection_ids(monkeypatch):
    answer, _ = asyncio.run(turn(monkeypatch, "카페 알아봐", selected=True))
    data = answer.context.model_dump()["control"]
    assert state_at({"control": data}, 1) and not state_at({"control": data}, 2)
    assert not state_at({"control": {**data, "version": 99}}, 1)
    assert not state_at({"control": {**data, "last_action": {"operation": "delete_all"}}}, 1)
    assert data["selected_count"] == 1 and data["outcome"] == "ready"
    assert "서울" not in json.dumps(data, ensure_ascii=False)
    assert "destination" not in json.dumps(data)


def test_retry_resumes_task_and_explicit_region_change_retargets_it(monkeypatch):
    answer, _ = asyncio.run(turn(monkeypatch, "카페 알아봐"))
    initial = answer.context.model_dump()
    initial["control"]["basis"] = 0
    decision = prepare(
        ai_planner.ChatInput(messages=[ai_planner.Message(role="user", content="다시")]),
        initial,
        None,
        date(2026, 10, 28),
    )
    assert decision.reason == "retry" and decision.directive.intent == "search"
    assert decision.directive.scope.kinds == ["cafe"]


@pytest.mark.parametrize(
    "action",
    [
        {"operation": "search", "area": "없는주소", "kinds": ["cafe"], "question": ""},
        {"operation": "search", "area": "중랑구", "kinds": ["cinema"], "question": ""},
        {
            "operation": "search",
            "area": "중랑구",
            "kinds": ["cafe"],
            "question": "",
            "permissions": ["all"],
        },
    ],
)
def test_interpreter_cannot_invent_slots_or_permissions(action):
    async def run():
        decision = prepare(
            ai_planner.ChatInput(
                messages=[ai_planner.Message(role="user", content="그 근방에서 갈만한 곳")]
            ),
            context(),
            None,
            date(2026, 10, 28),
        )

        def model(request):
            value = json.loads(request.content)
            assert "tools" not in value and value["response_format"]["type"] == "json_schema"
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(action)}}]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
            stats = RunStats("test")
            await interpret(
                decision,
                "그 근방에서 갈만한 곳",
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                client,
                Budget(),
                stats,
            )
        assert decision.directive.intent == "clarify"
        assert not decision.directive.allowed_tools and stats.counts["model_calls"] == 1

    asyncio.run(run())


def test_interpreter_and_answer_share_three_call_budget():
    async def run():
        stats = RunStats("test")
        stats.counts["model_calls"] = 1
        calls = []
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.allowed_tools = set()

        def model(request):
            calls.append(json.loads(request.content))
            answer = "bad JSON" if len(calls) == 1 else json.dumps({"reply": "정상 응답"})
            return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
            result = await ai_planner.complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성"}],
                session,
                client=client,
                stats=stats,
            )
        assert result.reply == "정상 응답" and stats.counts["model_calls"] == 3
        assert len(calls) == 2

    asyncio.run(run())


def test_unread_place_failure_claim_is_not_repeated():
    async def run():
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.operation, session.allowed_tools = "chat", set()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {"reply": "저장한 장소가 정확히 확인되지 않았어요."}
                                    )
                                }
                            }
                        ]
                    },
                )
            )
        ) as client:
            result = await ai_planner.complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성"}],
                session,
                client=client,
            )
        assert "확인되지" not in result.reply and "아직 실제" in result.reply

    asyncio.run(run())


def test_selected_include_and_anchor_roles_are_server_enforced():
    session = ToolSession(SimpleNamespace(), None, [], [])
    session.operation = "plan"
    included = session.add("합성 카페", "서울 중랑구", "selected")
    anchor = session.add("합성 기준점", "서울 중랑구", "selected")
    session.selected_usage = {included.ref: "include", anchor.ref: "anchor"}
    missing = ModelPlan(title="합성", date="2030-01-05", activities=[])
    assert session.guard_plan(missing, session.resolve(missing))[0] is None
    wrong = ModelPlan(
        title="합성",
        date="2030-01-05",
        activities=[
            {"title": "카페", "place_ref": included.ref},
            {"title": "기준점", "place_ref": anchor.ref},
        ],
    )
    assert session.guard_plan(wrong, session.resolve(wrong))[0] is None
    valid = ModelPlan(
        title="합성", date="2030-01-05", activities=[{"title": "카페", "place_ref": included.ref}]
    )
    assert session.guard_plan(valid, session.resolve(valid))[0]


def test_role_changes_affect_receipt_but_legacy_reference_does_not():
    import hashlib

    base = {
        "messages": [{"role": "user", "content": "합성"}],
        "selected_places": [{"source": "favorite", "id": str(uuid4())}],
    }
    hashes = []
    for usage in (None, "reference", "anchor", "include"):
        data = copy.deepcopy(base)
        if usage:
            data["selected_places"][0]["usage"] = usage
        hashes.append(
            hashlib.sha256(
                ai_planner.ChatInput.model_validate(data).model_dump_json().encode()
            ).hexdigest()
        )
    assert hashes[0] == hashes[1] and len(set(hashes)) == 3


@pytest.mark.parametrize("text", ["안녕하세요", "감사합니다", "알겠습니다", "네", "고마워요"])
def test_social_turn_preserves_pending_and_staged_fields(text):
    before = context()
    before["dialogue"]["pending"] = {"field": "target", "value": "", "resume": "plan"}
    before["pending_fields"] = {"values": {"budget": 5000}, "turn_version": 0}
    result = analyze(text, before, None, [], date(2026, 10, 28))
    after = merge_context(before, {}, result)
    assert result.intent == "chat" and not result.allowed_tools and not result.plan
    assert after["pending_fields"] == before["pending_fields"]
    assert result.state.pending.resume == "plan"


@pytest.mark.parametrize("fallback", [[], ["양주 덕계"]])
def test_city_only_address_is_not_silently_used_as_nearby(fallback):
    from we2day_api.ai_place_answers import read_candidate_request
    from we2day_api.ai_tools import SelectedPlace
    from we2day_api.places import SearchResults

    async def run():
        body = ai_planner.ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": "근처 카페 찾아줘"}],
                "selected_places": [{"source": "favorite", "id": str(uuid4()), "usage": "anchor"}],
            }
        )
        initial = context()
        initial["region"] = initial["search_scope"]["area"] = "샘플 집"
        directive = prepare(body, initial, None, date(2026, 10, 28)).directive
        session = ToolSession(
            SimpleNamespace(),
            None,
            [SelectedPlace.model_validate(body.selected_places[0].model_dump())],
            [],
            PlacePolicy(directive.scope),
        )
        session.allowed_tools = directive.allowed_tools
        session.operation = "search"
        session.anchor_search = True
        session.area_fallbacks = fallback
        events = []

        class IO:
            async def perform(self, action):
                events.append(action[0])
                if action[0] == "data":
                    return [
                        {
                            "id": str(body.selected_places[0].id),
                            "label": "샘플 집",
                            "destination": "경기도 양주시 평화로 1",
                        }
                    ]
                assert fallback and action[1] == "양주 덕계 카페"
                return SearchResults(items=[])

        await read_candidate_request(directive, session, IO())
        if fallback:
            assert directive.scope.area == "양주 덕계" and directive.notices
            assert events == ["data", "places"]
        else:
            assert directive.intent == "clarify" and session.resolution == "unresolved"
            assert events == ["data"]

    asyncio.run(run())


def test_initial_optional_preparation_padding_cannot_invalidate_required_plan():
    async def run():
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.operation = "plan"
        session.initial_activities = ["카페"]
        session.activity_limit = 1
        session.plan_date = "2030-01-05"
        session.require_plan = session.direct_final = True
        place = session.add("합성카페", "서울 중랑구", "naver")
        session.candidate_kinds[place.ref] = "cafe"

        def model(request):
            schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
            assert schema["$defs"]["ModelPlan"]["properties"]["preparation"]["maxItems"] == 0
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reply": "합성",
                                        "plan": {
                                            "title": "합성",
                                            "date": "2030-01-05",
                                            "activities": [
                                                {"title": "카페", "place_ref": place.ref}
                                            ],
                                            "preparation": ["],", "requirements", "   "],
                                        },
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        stats = RunStats("test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
            answer = await ai_planner.complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성"}],
                session,
                client=client,
                stats=stats,
            )
        assert answer.plan and answer.plan.preparation == []
        assert answer.plan.activities[0].place == place.destination
        assert stats.counts["model_calls"] == 1 and stats.counts["optional_normalizations"] == 1

    asyncio.run(run())
