from datetime import date
from uuid import UUID

from test_calendar_api import ROW, upstream  # noqa: F401


def test_reminders_month_boundary_leap_and_one_time_past(upstream, monkeypatch):  # noqa: F811
    monkeypatch.setattr("we2day_api.reminders.seoul_today", lambda: date(2027, 1, 31))
    client, calls, replies = upstream
    original = {
        "kind": "custom",
        "title": "기념일",
        "date": "2027-01-30",
        "month": None,
        "day": None,
        "annual": False,
        "version": 1,
    }
    birthday = {
        **original,
        "id": str(UUID(int=9)),
        "kind": "birthday",
        "date": None,
        "month": 2,
        "day": 29,
        "annual": True,
    }
    past = {**original, "id": str(UUID(int=8))}
    replies.extend(
        [
            (200, {"id": "space"}),
            (200, [{**ROW, "date": "2027-03-02"}]),
            (200, []),
            (200, [past, birthday]),
            (200, []),
            (200, {"id": "space"}),
        ]
    )
    result = client.get("/reminders?days=30")
    assert result.status_code == 200
    assert result.json()["until"] == "2027-03-02"
    assert [row["date"] for row in result.json()["items"]] == ["2027-02-28", "2027-03-02"]
    assert calls[1].url.params["and"] == "(date.gte.2027-01-31,date.lte.2027-03-02)"
    assert client.get("/reminders?days=10").status_code == 422


def test_reminders_do_not_return_partial_results_or_unconnected_data(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.append((200, None))
    assert client.get("/reminders").status_code == 409
    assert len(calls) == 1
