from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_calendar_api import ROW, upstream  # noqa: F401

from we2day_api.anniversaries import project
from we2day_api.calendar_export import escape_text, fold_line, read_rows, render_calendar

STAMP = datetime(2026, 10, 19, tzinfo=UTC)


def test_ical_escape_utf8_folding_and_no_injected_component():
    title = "함께🌷" * 80 + ",;\\\r\nBEGIN:VEVENT\r\nATTENDEE:mailto:other@example.invalid"
    content = render_calendar(
        [
            {
                **ROW,
                "title": title,
                "date": "2026-10-19",
                "time": "00:30:00",
                "place": "서울",
                "note": "개인 메모",
            }
        ],
        [],
        STAMP,
    )
    lines = content.split(b"\r\n")
    assert all(len(line) <= 75 for line in lines)
    assert all(line.decode("utf-8") is not None for line in lines)
    unfolded = content.replace(b"\r\n ", b"").decode()
    assert unfolded.count("\r\nBEGIN:VEVENT\r\n") == 1
    assert "DTSTART:20261018T153000Z" in unfolded
    assert "DESCRIPTION:" not in unfolded and "DTEND:" not in unfolded
    assert "VALARM" not in unfolded and "ATTENDEE:" not in unfolded.split("SUMMARY:")[0]
    assert escape_text("A\rB\nC;D,E\\F") == r"A\nB\nC\;D\,E\\F"
    assert fold_line("a" * 75) == b"a" * 75


def test_ical_all_day_leap_original_and_explicit_notes():
    birthday = {
        "id": str(UUID(int=9)),
        "kind": "birthday",
        "title": "생일",
        "date": None,
        "month": 2,
        "day": 29,
        "annual": True,
        "version": 1,
    }
    occurrence = project(birthday, date(2027, 2, 1))
    content = render_calendar(
        [{**ROW, "time": None, "date": "2027-02-28", "note": "메모\n둘째 줄"}],
        [occurrence],
        STAMP,
        True,
    ).decode()
    assert "DTSTART;VALUE=DATE:20270228" in content
    assert "DTEND;VALUE=DATE:20270301" in content
    assert "DESCRIPTION:메모\\n둘째 줄" in content
    assert birthday["day"] == 29 and "RRULE" not in content


def test_export_api_fixed_month_notes_default_and_membership(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.extend(
        [(200, {"id": "space"}), (200, [ROW]), (200, []), (200, []), (200, {"id": "space"})]
    )
    result = client.get("/calendar/export?month=2026-10")
    assert result.status_code == 200 and result.headers["content-type"].startswith("text/calendar")
    assert "no-store" in result.headers["cache-control"]
    assert "we2day-calendar-2026-10.ics" in result.headers["content-disposition"]
    assert "note" not in calls[1].url.params["select"]
    assert calls[2].url.params["id"] == f"gt.{ROW['id']}"
    assert client.get("/calendar/export?month=2026-13").status_code == 422


def test_reader_does_not_assume_provider_page_size_or_repeat_forever():
    class Store:
        def __init__(self):
            self.pages = [[{"id": str(UUID(int=1))}], [{"id": str(UUID(int=2))}], []]

        def call(self, *args, **kwargs):
            return self.pages.pop(0)

    assert len(read_rows(Store(), "appointments", "id")) == 2
    bad = Store()
    bad.pages = [[{"id": str(UUID(int=1))}]] * 2
    with pytest.raises(HTTPException) as error:
        read_rows(bad, "appointments", "id")
    assert error.value.status_code == 503
