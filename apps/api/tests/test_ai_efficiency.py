import asyncio
import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore, grade

from we2day_api import ai_planner
from we2day_api.ai_context import model_context, model_proposal
from we2day_api.ai_dialogue import DialogueState, Directive
from we2day_api.ai_edits import cancel_request
from we2day_api.ai_place_policy import SearchScope
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_tools import StoredContext, ToolSession
from we2day_api.plans import PlanContent

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/ai_efficiency_cases.json").read_text(encoding="utf-8")
)


def test_model_view_preserves_authoritative_clears_and_only_current_allowed_facts():
    context = StoredContext(
        date=None,
        budget=0,
        region="",
        transport="도보",
        activities=[],
        requirements="걷기 적게",
        private_owner="never-send",
    )
    scope = SearchScope(kinds=["library"], area="중랑구", search_only=True)
    state = DialogueState(
        intent="search",
        turn_version=999,
        rejected_places=["제외 도서관"],
        excluded_kinds=["cafe"],
        cleared_date=True,
    )
    directive = Directive(state, scope, intent="search")
    session = ToolSession(SimpleNamespace(), None, [], [])
    candidate = session.add("샘플도서관", "합성 도로1", "selected", "https://naver.me/Example12")
    original = context.model_dump()
    view = model_context(context, scope, directive, session, 1, date(2026, 10, 27))
    value = json.loads(view.split(": ", 1)[1])
    assert value["conditions"] == {
        "date": None,
        "budget": 0,
        "region": "",
        "transport": "도보",
        "activities": [],
        "requirements": "걷기 적게",
    }
    assert value["operation"] == "search" and value["scope"] == scope.model_dump(
        exclude_defaults=True
    )
    assert value["dialogue"]["rejected_places"] == ["제외 도서관"]
    assert value["dialogue"]["excluded_kinds"] == ["cafe"] and value["dialogue"]["cleared_date"]
    assert value["selected"] == 1 and value["places"][0]["ref"] == candidate.ref
    assert "never-send" not in view and "turn_version" not in view and "destination" not in view
    assert (
        candidate.destination == "https://naver.me/Example12"
        and candidate.model_dump()["destination"]
    )
    assert context.model_dump() == original


def test_compact_proposal_restores_every_field_including_zero_times_and_map_link():
    proposal = PlanContent(
        title="합성",
        date="2030-01-05",
        budget=0,
        transport="도보",
        activities=[
            {
                "title": "만남",
                "time": "00:00",
                "cost": 0,
                "note": "직접 정한 메모",
                "place": "직접 정한 장소",
                "map_url": "https://naver.me/Example12",
            },
            {"title": "미정 활동"},
        ],
        preparation=["물"],
    )
    original = proposal.model_dump()
    view = model_proposal(proposal)
    restored = PlanContent.model_validate_json(view.split(": ", 1)[1])
    assert restored == proposal and proposal.model_dump() == original
    assert len(view.encode()) < len(("현재 제안: " + proposal.model_dump_json()).encode())


def test_schema_template_has_no_request_values_and_is_compiled_once(monkeypatch):
    # The module's base ANSWER_FORMAT already warmed the static template.
    def unexpected(*args, **kwargs):
        pytest.fail("Static Pydantic metadata recompiled on request")

    monkeypatch.setattr(ai_planner.ModelAnswer, "model_json_schema", unexpected)
    first = ai_planner.answer_format("2030-01-05", 2)
    second = ai_planner.answer_format("2031-04-01", 1)
    base = ai_planner.answer_format()
    first["json_schema"]["schema"]["$defs"]["ModelPlan"]["properties"]["date"]["const"] = "tamper"
    assert (
        second["json_schema"]["schema"]["$defs"]["ModelPlan"]["properties"]["date"]["const"]
        == "2031-04-01"
    )
    assert "const" not in base["json_schema"]["schema"]["$defs"]["ModelPlan"]["properties"]["date"]
    assert base == ai_planner.ANSWER_FORMAT


@pytest.mark.parametrize(
    "text",
    ["아니야, 취소해줘.", "아니요 취소할게요", "취소", "취소해줘", "그대로 둬", "변경하지 마"],
)
def test_explicit_cancel_variants(text):
    assert cancel_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "취소하지 마",
        "제목을 '취소해줘'로 바꿔줘",
        "첫 활동 취소하고 카페 추가",
        "취소해줘라는 말을 설명해줘",
    ],
)
def test_quoted_negated_or_compound_text_is_not_a_blanket_cancel(text):
    assert not cancel_request(text)


@pytest.mark.parametrize(
    "case",
    [c for c in CORPUS["cases"] if all(s["expect"].get("no_search") for s in c["steps"])],
    ids=lambda c: c["id"],
)
def test_new_local_edit_cases_require_no_inference_or_business_table_access(case, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Model input assembled for a local server response")

    monkeypatch.setattr(ai_planner, "model_messages", unexpected)

    async def run():
        store = MemoryStore(case)
        cid = str(uuid4())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Unneeded inference"))
        ) as client:
            for step in case["steps"]:
                before = copy.deepcopy(store.proposal)
                stats = RunStats("synthetic")
                result = await ai_planner._chat(
                    ai_planner.ChatInput.model_validate(
                        {
                            "messages": step.get("history", [])
                            + [{"role": "user", "content": step["text"]}],
                            "conversation_id": cid,
                            "request_id": str(uuid4()),
                            "version": store.version,
                        }
                    ),
                    SimpleNamespace(),
                    store,
                    client,
                    Budget(),
                    stats,
                )
                assert stats.counts["model_calls"] == 0
                assert grade(case, step, result.model_dump(mode="json"), store.events, before) == []
                store.context = json.loads(json.dumps(store.context))

    asyncio.run(run())


def test_long_history_keeps_current_conditions_and_does_not_send_private_state(monkeypatch):
    async def run():
        case = next(c for c in CORPUS["cases"] if c["id"] == "K18")
        store = MemoryStore(case)
        store.context["private_owner"] = "never-send"

        async def complete(settings, messages, session, **kwargs):
            assert messages[0]["content"] == ai_planner.SYSTEM
            current = json.loads(messages[1]["content"].split(": ", 1)[1])
            assert current["conditions"]["date"] == "2030-01-05"
            assert current["conditions"]["budget"] == 80000
            assert current["conditions"]["requirements"] == "걷기 적게"
            assert current["scope"]["kinds"] == ["library"]
            assert "이전 합성 대화" in str(messages) and "never-send" not in str(messages)
            return ai_planner.ChatResult(reply="후보를 확인해요.")

        monkeypatch.setattr(ai_planner, "complete", complete)
        step = case["steps"][0]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("Network"))
        ) as client:
            await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": step["history"] + [{"role": "user", "content": step["text"]}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                    }
                ),
                SimpleNamespace(),
                store,
                client,
                Budget(),
                RunStats("synthetic"),
            )

    asyncio.run(run())
