"""Bounded multi-turn invariants independent of the model's helpfulness."""

import asyncio
import copy
import json
import random
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore

from we2day_api import ai_planner
from we2day_api.ai_dialogue import merge_context
from we2day_api.ai_intake import PlanningBrief, start_brief
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import ModelPlan, PlanningContext, ToolSession
from we2day_api.plans import PlanContent

BRIEF = dict(
    date="2030-01-05",
    region="중랑구",
    activities=["카페", "식사"],
    start_time="13:00",
    end_time="19:00",
    budget=50000,
    transport="자동차",
    requirements="실내 위주",
)
PLAN = dict(
    title="합성 코스",
    date="2030-01-05",
    budget=50000,
    transport="자동차",
    activities=[
        {"title": "카페", "time": "14:00", "place": "합성카페", "note": "원래 메모", "cost": 0},
        {"title": "식사", "time": "17:00", "place": "합성식당", "note": "다른 메모", "cost": 20000},
    ],
    preparation=["물"],
)


PLAN = PlanContent.model_validate(PLAN).model_dump()


class Conversation:
    def __init__(self, monkeypatch, *, proposal=True, allow_model=False):
        context = merge_context({}, {}, start_brief(PlanningBrief(**BRIEF), {}))
        self.store = MemoryStore(
            {"initial": {"context": context, "proposal": copy.deepcopy(PLAN) if proposal else None}}
        )
        self.id = str(uuid4())
        self.history, self.queries, self.calls = [], [], []
        self.semantic_action = None
        original = self.store.rpc

        async def rpc(name, values=None):
            self.calls.append(name)
            # A healthy canonical state must not fetch the full old conversation.
            assert name != "read_ai_conversations"
            return await original(name, values)

        async def completion(*args, **kwargs):
            assert allow_model, "An explicit condition operation must need no model"
            return ai_planner.ChatResult(
                reply="합성 일반 답변",
                context=PlanningContext(
                    requirements="오래된 조건", activities=["오래된 활동"]
                ).model_dump(),
            )

        def provider(request):
            assert request.url.host == "naverapihub.apigw.ntruss.com"
            query = request.url.params["query"]
            self.queries.append(query)
            kind = "카페" if "카페" in query else "음식점"
            address = (
                "서울특별시 성동구 성수동1가 1"
                if "성수동" in query
                else "서울특별시 중랑구 신내동 1"
            )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "title": "합성" + kind,
                            "category": kind,
                            "description": query,
                            "roadAddress": address,
                        }
                    ]
                },
            )

        self.store.rpc = rpc
        self.provider = provider
        monkeypatch.setattr(ai_planner, "complete", completion)

    def transport(self, request):
        if request.url.host == "api.cloudflare.com":
            from semantic_fixture import semantic_response

            return semantic_response(
                request, self.semantic_action(request) if self.semantic_action else None
            )
        return self.provider(request)

    async def send(self, text):
        self.history.append({"role": "user", "content": text})
        body = ai_planner.ChatInput.model_validate(
            {
                "messages": self.history[-11:],
                "conversation_id": self.id,
                "request_id": str(uuid4()),
                "version": self.store.version,
            }
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.transport)) as client:
            result = await ai_planner._chat(
                body,
                SimpleNamespace(
                    cloudflare_account_id="a" * 32,
                    cloudflare_api_token="synthetic",
                    naver_search_enabled=True,
                    naver_search_client_id="synthetic",
                    naver_search_client_secret="synthetic",
                ),
                self.store,
                client,
                Budget(),
                RunStats("test"),
            )
        self.history.append({"role": "assistant", "content": result.reply})
        assert len(json.dumps(self.store.context, ensure_ascii=False).encode()) < 32768
        assert result.context.control["basis"] == self.store.version
        return result


@pytest.mark.parametrize("proposal", [False, True])
@pytest.mark.parametrize(
    "text,key,value",
    [
        ("지역은 성수동으로 바꿔줘", "region", "성수동"),
        ("예산은 미정으로 바꿔줘", "budget", None),
        ("예산은 0원으로 바꿔줘", "budget", 0),
        ("이동수단은 미정으로 바꿔줘", "transport", ""),
        ("추가 조건은 야외 위주로 바꿔줘", "requirements", "야외 위주"),
        ("추가 조건은 없음으로 바꿔줘", "requirements", ""),
        ("날짜는 미정으로 바꿔줘", "date", None),
    ],
)
def test_condition_replacement_and_clear_with_or_without_proposal(
    monkeypatch, proposal, text, key, value
):
    async def run():
        c = Conversation(monkeypatch, proposal=proposal)
        result = await c.send(text)
        assert getattr(result.context, key) == value
        assert getattr(result.context.intake.data, key) == value
        if proposal and key in {"budget", "transport"}:
            assert c.store.proposal[key] == value
        if proposal:
            assert c.store.proposal["activities"] == PLAN["activities"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "pending", ["제목 바꿔줘", "예산 바꿔줘", "활동 순서 바꿔줘", "종료 시간 바꿔줘"]
)
def test_new_search_supersedes_every_pending_edit(monkeypatch, pending):
    async def run():
        c = Conversation(monkeypatch)
        await c.send(pending)
        result = await c.send("성수동 근처 카페 찾아줘")
        assert result.candidates and all("성수동" in q for q in c.queries)
        assert c.store.proposal == PLAN
        assert not result.context.dialogue.pending
        assert result.context.activity_edit is None
        assert result.context.intake.pending is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "pending,answer",
    [("예산 바꿔줘", "3만원"), ("첫 번째 활동을 미뤄줘", "30분"), ("종료 시간 바꿔줘", "20:00")],
)
def test_help_and_social_turns_preserve_current_question_basis(monkeypatch, pending, answer):
    async def run():
        c = Conversation(monkeypatch)
        await c.send(pending)
        for text in ["어떤 기능 있어?", "고마워요"] * 8:
            result = await c.send(text)
            assert result.context.dialogue.intent == "chat"
        result = await c.send(answer)
        if answer == "3만원":
            assert c.store.proposal["budget"] == 30000
        elif answer == "30분":
            assert c.store.proposal["activities"][0]["time"] == "14:30"
        else:
            assert result.context.intake.data.end_time == "20:00"

    asyncio.run(run())


def test_cleared_date_cannot_be_resurrected_by_retry_or_old_proposal(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        c.store.context["control"] = {
            "version": 1,
            "basis": 0,
            "last_action": {"operation": "plan", "scope": {"area": "중랑구", "kinds": ["cafe"]}},
        }
        await c.send("날짜는 미정으로 바꿔줘")
        for text in ["감사합니다"] * 12 + ["다시", "코스 만들어줘"]:
            result = await c.send(text)
            assert result.context.date is None and result.context.dialogue.cleared_date
            assert not result.plan
        assert not c.queries
        assert c.store.proposal == PLAN

    asyncio.run(run())


def test_cleared_requirements_not_refilled_from_model_context(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, allow_model=True)
        await c.send("추가 조건은 없음으로 바꿔줘")
        result = await c.send("데이트 준비에 대해 이야기하자")
        assert result.context.requirements == ""
        assert result.context.activities == BRIEF["activities"]

    asyncio.run(run())


@pytest.mark.parametrize("seed", [7, 19, 41])
def test_long_repeated_conditions_and_searches_keep_latest_state(monkeypatch, seed):
    async def run():
        c = Conversation(monkeypatch)
        expected = {
            k: copy.deepcopy(BRIEF[k])
            for k in ["date", "region", "budget", "transport", "requirements"]
        }
        rng = random.Random(seed)
        choices = [
            ("region", "중랑구"),
            ("budget", None),
            ("transport", None),
            ("requirements", None),
            ("date", None),
            ("social", None),
            ("search", None),
        ]
        for i in range(140):
            key, _ = rng.choice(choices)
            if key == "region":
                value = rng.choice(["중랑구", "성수동"])
                text = f"지역은 {value}으로 바꿔줘"
            elif key == "budget":
                value = rng.choice([None, 0, 10000, 30000])
                text = f"예산은 {'미정' if value is None else str(value) + '원'}으로 바꿔줘"
            elif key == "transport":
                value = rng.choice(["", "자동차", "대중교통", "도보"])
                text = f"이동수단은 {value or '미정'}으로 바꿔줘"
            elif key == "requirements":
                value = rng.choice(["", "실내 위주", "야외 위주"])
                text = f"추가 조건은 {value or '없음'}로 바꿔줘"
            elif key == "date":
                value = f"2030-02-{rng.randrange(1, 28):02}"
                text = f"날짜는 {value}로 바꿔줘"
            else:
                value = None
                text = "감사합니다" if key == "social" else "근처 카페 찾아줘"
            if key in expected:
                expected[key] = value
            result = await c.send(text)
            for field, want in expected.items():
                assert getattr(result.context, field) == want, (i, text, field, want)
                assert getattr(result.context.intake.data, field) == want
            assert c.store.proposal["activities"] == PLAN["activities"]
            assert c.store.proposal["preparation"] == PLAN["preparation"]
            for field in ["date", "budget", "transport"]:
                assert c.store.proposal[field] == expected[field]
            if key == "search":
                assert c.queries[-1].startswith(expected["region"])
        assert len(c.history) > 11 and not any(x == "read_ai_conversations" for x in c.calls)

    asyncio.run(run())


def test_model_plan_metadata_cannot_restore_old_budget_and_transport():
    session = ToolSession(SimpleNamespace(), None, [], [])
    session.operation = "plan"
    session.plan_updates = {"budget": None, "transport": ""}
    model = ModelPlan.model_validate(PLAN)
    guarded, _ = session.guard_plan(model, PlanContent.model_validate(PLAN))
    assert guarded.budget is None and guarded.transport == ""


def test_region_clear_then_retry_does_not_search_an_old_history_region(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("중랑구 근처 카페 찾아줘")
        before = len(c.queries)
        await c.send("지역은 미정으로 바꿔줘")
        result = await c.send("다시")
        assert result.context.region == "" and len(c.queries) == before
        assert result.context.dialogue.pending.field == "region"

    asyncio.run(run())


@pytest.mark.parametrize("pending", ["제목 바꿔줘", "활동 순서 바꿔줘", "종료 시간 바꿔줘"])
def test_cancel_and_retry_cannot_resume_cancelled_changes(monkeypatch, pending):
    async def run():
        c = Conversation(monkeypatch)
        await c.send(pending)
        await c.send("취소해줘")
        result = await c.send("다시")
        assert result.context.dialogue.pending.field == "target"
        assert not c.queries and c.store.proposal == PLAN
        assert not result.context.activity_edit and not result.context.intake.pending

    asyncio.run(run())


def test_new_condition_abandons_window_question_and_unrelated_clock_is_not_an_answer(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, allow_model=True)
        await c.send("종료 시간 바꿔줘")
        await c.send("예산은 3만원으로 바꿔줘")
        result = await c.send("20:00")
        assert result.context.intake.data.end_time == "19:00"
        assert result.context.budget == 30000 and not result.context.intake.pending

    asyncio.run(run())


def test_compound_conditions_update_all_fields_without_touching_activities(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        result = await c.send("날짜는 2030-02-03으로 바꾸고 예산은 3만원, 지역은 성수동으로 바꿔줘")
        assert (result.context.date, result.context.budget, result.context.region) == (
            "2030-02-03",
            30000,
            "성수동",
        )
        assert c.store.proposal["activities"] == PLAN["activities"]
        assert c.store.proposal["date"] == "2030-02-03" and c.store.proposal["budget"] == 30000

    asyncio.run(run())


def test_pending_multiple_fields_survive_help_and_cancel_without_partial_commit(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("날짜는 2030-02-03으로 바꾸고 예산은 2달러로 바꿔줘")
        assert c.store.proposal == PLAN and c.store.context["date"] == PLAN["date"]
        await c.send("어떤 기능 있어?")
        result = await c.send("3만원")
        assert result.plan.date == "2030-02-03" and result.plan.budget == 30000
        await c.send("예산은 미정으로 바꾸고 날짜는 2030-02-40으로 바꿔줘")
        assert c.store.proposal["budget"] == 30000
        await c.send("취소해줘")
        assert c.store.proposal["budget"] == 30000

    asyncio.run(run())


def test_old_proposal_locations_are_not_returned_as_fresh_candidates(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        result = await c.send("감사합니다")
        assert not result.candidates and not result.tools
        assert c.store.proposal == PLAN

    asyncio.run(run())


def test_replaced_requirements_remove_their_old_negative_filters(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        c.store.context["requirements"] = "카페 제외"
        c.store.context["dialogue"]["excluded_kinds"] = ["cafe"]
        await c.send("추가 조건은 없음으로 바꿔줘")
        result = await c.send("근처 카페 찾아줘")
        assert result.candidates and "cafe" not in result.context.dialogue.excluded_kinds

    asyncio.run(run())


def test_excluded_scope_does_not_reappear_or_broaden_on_retry(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("근처 카페 찾아줘")
        await c.send("카페 제외해")
        before = len(c.queries)
        result = await c.send("다시")
        assert len(c.queries) == before and not result.candidates
        assert result.context.dialogue.pending.field == "target"

    asyncio.run(run())


def test_question_about_current_budget_does_not_become_title_or_change_conditions(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("제목 바꿔줘")
        result = await c.send("예산은 3만원이면 충분할까?")
        assert result.context.budget == 50000 and c.store.proposal == PLAN
        assert result.context.dialogue.pending.field == "title"
        assert "50,000" in result.reply
        await c.send("제목은 '함께 산책'으로 바꿔줘")
        assert c.store.proposal["title"] == "함께 산책"

    asyncio.run(run())


def test_new_plan_uses_current_activities_not_a_one_off_search_scope(monkeypatch):
    from datetime import date

    from we2day_api.ai_control import prepare

    async def run():
        c = Conversation(monkeypatch)
        await c.send("근처 카페 찾아줘")
        for _ in range(14):
            await c.send("고마워요")
        body = ai_planner.ChatInput.model_validate(
            {
                "messages": [{"role": "user", "content": "현재 조건으로 코스 만들어줘"}],
                "version": c.store.version,
            }
        )
        decision = prepare(
            body, c.store.context, PlanContent.model_validate(c.store.proposal), date(2026, 10, 29)
        )
        assert set(decision.directive.scope.kinds) == {"cafe", "restaurant"}
        assert c.store.context["activities"] == ["카페", "식사"]

    asyncio.run(run())


def test_quoted_title_is_data_not_budget_date_or_transport_instructions(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        title = "예산 0원 날짜 2031-01-01 이동수단 도보"
        result = await c.send(f"제목은 '{title}'로 바꿔줘")
        assert result.plan.title == title
        assert (result.plan.budget, result.plan.date, result.plan.transport) == (
            50000,
            "2030-01-05",
            "자동차",
        )
        assert result.context.budget == 50000 and result.context.date == "2030-01-05"

    asyncio.run(run())


@pytest.mark.parametrize("title", ["카페 추천 코스", "합성카페 제외", "코스 만들기 검색"])
def test_quoted_title_cannot_start_search_generation_or_rejection(monkeypatch, title):
    async def run():
        c = Conversation(monkeypatch)
        result = await c.send(f"제목은 '{title}'로 바꿔줘")
        assert result.plan.title == title and not c.queries
        assert not result.context.dialogue.rejected_places
        assert not result.context.dialogue.excluded_kinds

    asyncio.run(run())


def test_quoted_requirement_updates_data_and_its_filters_not_the_current_operation(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("추가 조건은 '합성카페 제외'로 바꿔줘")
        assert "합성카페" in c.store.context["dialogue"]["rejected_places"]
        result = await c.send("추가 조건은 '코스 만들기 검색'으로 바꿔줘")
        assert result.context.requirements == "코스 만들기 검색"
        assert "합성카페" not in result.context.dialogue.rejected_places
        assert not c.queries

    asyncio.run(run())


def test_regenerated_plan_retains_current_activity_count_order_and_grounding(monkeypatch):
    async def run():
        c = Conversation(monkeypatch, proposal=False)
        await c.send("근처 카페 찾아줘")
        for _ in range(16):
            await c.send("고마워요")

        async def completion(settings, messages, session, **kwargs):
            assert session.activity_limit == 2
            assert session.requested_activities == ["카페", "식사"]
            assert session.direct_final
            assert set(session.candidate_kinds.values()) == {"cafe", "restaurant"}
            return ai_planner.ChatResult(reply="합성 완성", plan=PlanContent.model_validate(PLAN))

        monkeypatch.setattr(ai_planner, "complete", completion)
        result = await c.send("현재 조건으로 코스 만들어줘")
        assert result.plan and len(result.plan.activities) == 2

    asyncio.run(run())


def test_named_answer_to_pending_budget_commits_the_staged_date(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        await c.send("날짜는 2030-02-03으로 바꾸고 예산은 2달러로 바꿔줘")
        result = await c.send("예산은 3만원으로 바꿔줘")
        assert result.plan.date == "2030-02-03" and result.plan.budget == 30000

    asyncio.run(run())


def test_date_clear_with_invalid_budget_does_not_silently_apply_only_the_clear(monkeypatch):
    async def run():
        c = Conversation(monkeypatch)
        result = await c.send("날짜는 미정으로 바꾸고 예산은 2달러로 바꿔줘")
        assert result.context.date == "2030-01-05" and not result.context.dialogue.cleared_date
        assert c.store.proposal == PLAN and not result.plan
        assert "아직 변경하지 않았어요" in result.reply

    asyncio.run(run())


def test_model_evidence_includes_verified_kind_without_guessing_selected_place_type():
    from datetime import date

    from we2day_api.ai_context import model_context
    from we2day_api.ai_dialogue import analyze
    from we2day_api.ai_tools import StoredContext

    session = ToolSession(SimpleNamespace(), None, [], [])
    cafe = session.add("합성카페", "공공 주소", "naver")
    home = session.add("합성 기준점", "합성 주소", "selected")
    session.candidate_kinds[cafe.ref] = "cafe"
    d = analyze("고마워요", {}, None, [], date(2026, 10, 29))
    data = json.loads(
        model_context(StoredContext(), d.scope, d, session, 0, date(2026, 10, 29)).split(": ", 1)[1]
    )
    assert data["places"][0]["kind"] == "cafe"
    assert data["places"][1]["kind"] == "any" and home.ref


@pytest.mark.parametrize("always_wrong", [False, True])
def test_semantic_repair_is_once_final_only_and_cannot_expand_tool_budget(always_wrong):
    async def run():
        session = ToolSession(SimpleNamespace(), None, [], [])
        session.operation = "plan"
        session.require_plan = session.direct_final = True
        session.plan_date = "2030-01-05"
        session.activity_limit = 2
        session.requested_activities = ["카페", "식사"]
        cafe = session.add("합성카페", "공공 주소", "naver")
        meal = session.add("합성식당", "공공 주소", "naver")
        session.candidate_kinds.update({cafe.ref: "cafe", meal.ref: "restaurant"})
        session.fresh_refs.update([cafe.ref, meal.ref])
        calls = []

        def response(request):
            payload = json.loads(request.content)
            calls.append(payload)
            assert "tools" not in payload
            refs = [meal.ref, cafe.ref] if always_wrong or len(calls) == 1 else [cafe.ref, meal.ref]
            activities = [
                {"title": title, "place_ref": ref}
                for title, ref in zip(["카페", "식사"], refs, strict=True)
            ]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reply": "합성 코스",
                                        "plan": {
                                            "title": "합성",
                                            "date": "2030-01-05",
                                            "activities": activities,
                                        },
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        stats = RunStats("test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            answer = await ai_planner.complete(
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                [{"role": "user", "content": "합성 코스"}],
                session,
                client=client,
                stats=stats,
            )
        assert len(calls) == 2 and stats.counts["schema_repairs"] == 1
        assert bool(answer.plan) is not always_wrong
        assert "validation_errors" in calls[-1]["messages"][-2]["content"]
        assert not session.calls

    asyncio.run(run())
