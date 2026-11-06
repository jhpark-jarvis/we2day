"""Saved-date questions require actual caller-scoped reads, never model guesses."""

import asyncio
from datetime import date
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore

from we2day_api import ai_planner
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_saved_schedule import ScheduleRead, read_schedule, render, request_read
from we2day_api.config import Settings


@pytest.mark.parametrize("text", ["오늘 일정 브리핑해줘.", "11월 6일에 저장된 일정이 없다고?"])
def test_reported_questions_read_saved_data_without_model(monkeypatch, text):
    class Clock:
        @classmethod
        def now(cls, zone):
            from datetime import datetime

            return datetime(2026, 11, 6, tzinfo=zone)

    monkeypatch.setattr(ai_planner, "datetime", Clock)
    store = MemoryStore({"initial": {}})
    reads = []

    async def read(method, table, params):
        reads.append((method, table, params))
        if table == "appointments":
            return [
                {
                    "id": "shared",
                    "kind": "shared",
                    "title": "저녁 약속",
                    "date": "2026-11-06",
                    "time": "19:00:00",
                    "place": "샘플 식당",
                }
            ]
        assert table == "date_plans"
        return []

    store.call = read

    def forbidden(request):
        pytest.fail("Saved schedule data must not be sent to a model")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            return await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": text}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                        "version": 0,
                    }
                ),
                Settings(_env_file=None),
                store,
                client,
                Budget(),
                RunStats("test"),
            )

    result = asyncio.run(run())
    assert "저녁 약속" in result.reply and "19:00" in result.reply
    assert "없습니다" not in result.reply and result.plan is None
    assert len(reads) == 2 and all(r[0] == "GET" for r in reads)
    assert reads[0][2]["kind"] == "eq.shared"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("오늘 일정", "2026-11-06"),
        ("내일 약속 보여줘", "2026-11-07"),
        ("어제 저장된 코스 알려줘", "2026-11-05"),
        ("모레 일정 뭐 있어?", "2026-11-08"),
        ("11월 6일 저장한 플랜 보여줘", "2026-11-06"),
        ("2027년 1월 2일 약속 확인해줘", "2027-01-02"),
        ("2026-12-31 일정 요약", "2026-12-31"),
        ("다음 주 월요일 일정", "2026-11-09"),
    ],
)
def test_explicit_date_reads(text, expected):
    assert request_read(text, {}, 0, date(2026, 11, 6)).date == expected


@pytest.mark.parametrize(
    "text",
    [
        "일정 보여줘",
        "오늘 아니면 내일 일정 알려줘",
        "11월 31일 일정",
        "이번 주말 일정",
        "2026-02-29 약속",
        "11월 6일부터 8일까지 일정",
        "11월 6일 또는 7일 일정",
    ],
)
def test_ambiguous_or_invalid_date_does_not_read(text):
    result = request_read(text, {}, 0, date(2026, 11, 6))
    assert result and result.question and not result.date


@pytest.mark.parametrize(
    "text",
    [
        "오늘 성수동 데이트 코스 추천해줘",
        "오늘 일정 수정해줘",
        "약속 추가해줘",
        "플랜 저장해",
        "현재 코스 보여줘",
        "안녕",
        "성수동 카페 찾아줘",
    ],
)
def test_other_tasks_do_not_read_saved_schedules(text):
    assert request_read(text, {}, 0, date(2026, 11, 6)) is None


def test_followup_date_and_retry_require_current_basis():
    context = {"schedule_read": {"date": "2026-11-06", "basis": 3}}
    assert request_read("그럼 내일은?", context, 3, date(2026, 11, 6)).date == "2026-11-07"
    assert request_read("다시", context, 3, date(2026, 11, 6)).date == "2026-11-06"
    assert request_read("그럼 내일은?", context, 4, date(2026, 11, 6)) is None
    pending = {"schedule_read": {"date": "", "basis": 3}}
    assert request_read("11월 6일", pending, 3, date(2026, 11, 6)).date == "2026-11-06"
    assert request_read("그럼 내일 성수동 카페 찾아줘", context, 3, date(2026, 11, 6)) is None


def test_published_course_and_draft_are_separate_and_personal_excluded():
    appointments = [
        {"id": "a", "kind": "shared", "date": "2026-11-06", "time": "19:00:00", "title": "약속"},
        {"id": "p", "kind": "personal", "date": "2026-11-06", "title": "PRIVATE"},
    ]
    plans = [
        {
            "appointment_id": "a",
            "published_date": "2026-11-06",
            "published_title": "확정",
            "draft_date": "2026-11-06",
            "draft_title": "고치는 중",
            "activities": [
                {"title": "저녁 식사", "time": "19:00", "place": "식당", "note": "NO NOTE"},
            ],
        },
        {"draft_date": "2026-11-06", "draft_title": "다른 초안"},
    ]
    reply, count = render("2026-11-06", appointments, plans)
    assert "저녁 식사" in reply and "미확정 초안: 고치는 중" in reply
    assert "미확정 초안: 다른 초안" in reply and count == 3
    assert reply.count("• 약속") == 0  # the appointment includes its explicit time
    assert "PRIVATE" not in reply and "NO NOTE" not in reply


def test_large_result_is_bounded_and_explicitly_partial():
    rows = [
        {
            "id": str(i),
            "kind": "shared",
            "date": "2026-11-06",
            "title": "가" * 100,
            "place": "나" * 200,
        }
        for i in range(11)
    ]
    reply, _ = render("2026-11-06", rows, [])
    assert len(reply) <= 4000 and "일부 일정" in reply


@pytest.mark.parametrize("failure", [False, True])
def test_empty_and_failed_reads_cannot_be_confused(failure):
    class Store:
        async def call(self, *args, **kwargs):
            if failure:
                from fastapi import HTTPException

                raise HTTPException(503, "SECRET upstream error")
            return []

    reply, tools = asyncio.run(
        read_schedule(ScheduleRead(date="2026-11-06"), Store(), RunStats("test"))
    )
    assert ("불러오지 못했어요" in reply) == failure
    assert ("없어요" in reply) != failure
    assert "SECRET" not in reply and tools[0]["status"] == ("failed" if failure else "empty")


def test_personal_request_does_not_access_database():
    request = request_read("오늘 개인 일정 보여줘", {}, 0, date(2026, 11, 6))
    reply, tools = asyncio.run(read_schedule(request, object(), RunStats("test")))
    assert "개인 일정은 달력" in reply and not tools


def test_server_briefing_not_exported_on_later_model_turn():
    from we2day_api.ai_context import model_messages
    from we2day_api.ai_dialogue import DialogueState, Directive
    from we2day_api.ai_place_policy import SearchScope
    from we2day_api.ai_tools import StoredContext, ToolSession

    body = ai_planner.ChatInput.model_validate(
        {
            "messages": [
                {"role": "user", "content": "오늘 일정 브리핑해줘"},
                {"role": "assistant", "content": "2026-11-06 공동 일정\n• PRIVATE SAVED PLACE"},
                {"role": "user", "content": "데이트 코스 짜는 법 알려줘"},
            ]
        }
    )
    scope = SearchScope()
    directive = Directive(DialogueState(), scope)
    messages = model_messages(
        "system",
        body,
        StoredContext(),
        scope,
        directive,
        ToolSession(Settings(_env_file=None), object(), [], []),
        None,
        date(2026, 11, 6),
        body.messages[-1].content,
    )
    assert "PRIVATE SAVED PLACE" not in str(messages)
    assert messages[-1]["content"] == "데이트 코스 짜는 법 알려줘"


def test_schedule_read_does_not_overwrite_editing_date_and_proposal():
    proposal = {"title": "편집 중 코스", "date": "2027-02-03", "activities": []}
    store = MemoryStore({"initial": {"context": {"date": "2027-02-03"}, "proposal": proposal}})

    async def read(*args, **kwargs):
        return []

    store.call = read

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("No model"))
        ) as client:
            return await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": "2026-11-06 일정 보여줘"}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                        "version": 0,
                    }
                ),
                Settings(_env_file=None),
                store,
                client,
                Budget(),
                RunStats("test"),
            )

    result = asyncio.run(run())
    assert result.context.date == "2027-02-03" and result.plan is None
    assert store.proposal == proposal
    assert result.context.schedule_read == {"basis": 1, "date": "2026-11-06"}


def test_cancelled_read_releases_lease_without_persisting():
    store = MemoryStore({"initial": {}})
    released = []
    rpc = store.rpc

    async def tracked(name, values=None):
        if name == "release_ai_planner_turn":
            released.append(name)
        return await rpc(name, values)

    async def read(*args, **kwargs):
        raise asyncio.CancelledError

    store.rpc, store.call = tracked, read

    async def run():
        async with httpx.AsyncClient() as client:
            with pytest.raises(asyncio.CancelledError):
                await ai_planner._chat(
                    ai_planner.ChatInput.model_validate(
                        {
                            "messages": [{"role": "user", "content": "2026-11-06 일정 보여줘"}],
                            "conversation_id": str(uuid4()),
                            "request_id": str(uuid4()),
                            "version": 0,
                        }
                    ),
                    Settings(_env_file=None),
                    store,
                    client,
                    Budget(),
                    RunStats("test"),
                )

    asyncio.run(run())
    assert released == ["release_ai_planner_turn"] and store.version == 0


def test_replay_does_not_repeat_schedule_read():
    store = MemoryStore({"initial": {}})

    async def replay(*args, **kwargs):
        return {"replay": {"version": 1, "result": {"reply": "기존 공동 일정 요약"}}}

    store.rpc = replay

    async def run():
        async with httpx.AsyncClient() as client:
            return await ai_planner._chat(
                ai_planner.ChatInput.model_validate(
                    {
                        "messages": [{"role": "user", "content": "2026-11-06 일정 보여줘"}],
                        "conversation_id": str(uuid4()),
                        "request_id": str(uuid4()),
                        "version": 0,
                    }
                ),
                Settings(_env_file=None),
                store,
                client,
                Budget(),
                RunStats("test"),
            )

    assert asyncio.run(run()).reply == "기존 공동 일정 요약"
