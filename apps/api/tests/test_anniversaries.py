from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from we2day_api.anniversaries import AnniversaryInput, project
from we2day_api.main import create_app


def original(kind="relationship", value="2026-01-01", **kwargs):
    return {"kind": kind, "date": value, "month": None, "day": None, "annual": True, **kwargs}


@pytest.mark.parametrize(
    "today,expected",
    [
        ("2025-12-31", None),
        ("2026-01-01", 1),
        ("2026-01-02", 2),
        ("2026-04-09", 99),
        ("2026-04-10", 100),
        ("2027-01-01", 366),
    ],
)
def test_inclusive_relationship_days(today, expected):
    result = project(original(), date.fromisoformat(today))
    assert result["together_days"] == expected
    assert result["days_until"] >= 0


@pytest.mark.parametrize(
    "today,expected",
    [
        ("2028-02-28", "2028-02-29"),
        ("2028-02-29", "2028-02-29"),
        ("2028-03-01", "2029-02-28"),
        ("2029-02-28", "2029-02-28"),
        ("2029-03-01", "2030-02-28"),
        ("2099-03-01", "2100-02-28"),
        ("2100-12-31", "2101-02-28"),
    ],
)
def test_leap_original_survives_common_years(today, expected):
    row = original("custom", "2000-02-29")
    result = project(row, date.fromisoformat(today))
    assert result["next_date"].isoformat() == expected
    assert row["date"] == "2000-02-29"


def test_birthdays_once_and_future_original():
    result = project(original("birthday", None, month=2, day=29), date(2029, 2, 28))
    assert result["days_until"] == 0 and result["date"] is None
    assert (
        project(original("custom", "2026-01-01", annual=False), date(2026, 1, 2))["days_until"]
        == -1
    )
    assert project(original(value="2030-01-01"), date(2026, 10, 19))["next_date"] == date(
        2030, 1, 1
    )


def test_seoul_midnight(monkeypatch):
    from we2day_api import anniversaries

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 31, 15, tzinfo=ZoneInfo("UTC")).astimezone(tz)

    monkeypatch.setattr(anniversaries, "datetime", Clock)
    assert anniversaries.seoul_today() == date(2027, 1, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"date": "2027-02-29"},
        {"annual": False},
        {"kind": "birthday", "date": None, "month": 4, "day": 31},
        {"kind": "birthday", "date": None, "month": 2},
        {"month": 3},
        {"couple_id": str(uuid4())},
    ],
)
def test_invalid_originals(change):
    with pytest.raises(ValueError):
        AnniversaryInput(**{"title": "함께한 날", **original(), **change})


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/anniversaries"),
        ("post", "/anniversaries"),
        ("patch", f"/anniversaries/{uuid4()}"),
    ],
)
def test_anonymous_denied(method, path):
    with TestClient(create_app()) as client:
        assert getattr(client, method)(path).status_code == 401
