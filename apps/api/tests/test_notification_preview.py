from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from test_calendar_api import upstream  # noqa: F401

from we2day_api.notification_preview import preview_times

SEOUL = ZoneInfo("Asia/Seoul")


def occasion(**changes):
    return {
        "id": str(UUID(int=10)),
        "kind": "custom",
        "title": "직접 정한 기념일",
        "date": "2026-11-01",
        "month": None,
        "day": None,
        "annual": True,
        "version": 1,
        **changes,
    }


def test_window_includes_lead_for_occasion_beyond_end_and_excludes_elapsed_times():
    row = occasion()
    original = deepcopy(row)
    result = preview_times([row], datetime(2026, 10, 24, 9, tzinfo=SEOUL), 7)
    assert [(r["scheduled_at"].date().isoformat(), r["lead_days"]) for r in result["items"]] == [
        ("2026-10-25", 7),
        ("2026-10-31", 1),
    ]
    assert row == original
    boundary = occasion(date="2026-10-24", annual=False)
    assert len(preview_times([boundary], datetime(2026, 10, 24, tzinfo=UTC), 7)["items"]) == 1
    assert not preview_times([boundary], datetime(2026, 10, 24, 0, 0, 1, tzinfo=UTC), 7)["items"]


def test_year_rollover_leap_original_future_and_stable_order():
    birthday = occasion(kind="birthday", date=None, month=2, day=29)
    rows = preview_times([birthday], datetime(2027, 2, 21, 8, tzinfo=SEOUL), 7)["items"]
    assert [r["lead_days"] for r in rows] == [7, 1, 0]
    assert {r["occurrence_date"] for r in rows} == {"2027-02-28"}
    assert birthday["day"] == 29
    leap = preview_times([birthday], datetime(2028, 2, 22, 8, tzinfo=SEOUL), 7)["items"]
    assert {r["occurrence_date"] for r in leap} == {"2028-02-29"}
    january = occasion(date="2020-01-01")
    future = occasion(id=str(UUID(int=11)), date="2028-01-01")
    past = occasion(id=str(UUID(int=12)), date="2026-01-01", annual=False)
    result = preview_times([future, past, january], datetime(2026, 12, 25, 8, tzinfo=SEOUL), 7)
    assert [r["lead_days"] for r in result["items"]] == [7, 1, 0]
    assert {r["occurrence_date"] for r in result["items"]} == {"2027-01-01"}
    assert (
        result["items"]
        == preview_times([january, future, past], datetime(2026, 12, 25, 8, tzinfo=SEOUL), 7)[
            "items"
        ]
    )


def test_preview_rejects_unbounded_output_and_naive_clocks():
    with pytest.raises(ValueError):
        preview_times([], datetime(2026, 1, 1), 7)
    with pytest.raises(ValueError):
        preview_times([], datetime(2026, 1, 1, tzinfo=SEOUL), 365)
    with pytest.raises(HTTPException) as error:
        preview_times([occasion()] * 667, datetime(2026, 10, 24, 8, tzinfo=SEOUL), 30)
    assert error.value.status_code == 413


def test_preview_api_caller_scope_projection_no_writes_or_device_reads(upstream, monkeypatch):  # noqa: F811
    client, calls, replies = upstream
    monkeypatch.setattr(
        "we2day_api.notification_preview.seoul_now",
        lambda: datetime(2026, 10, 25, 8, tzinfo=SEOUL),
    )
    replies.extend([(200, {"id": "space"}), (200, [occasion()]), (200, []), (200, {"id": "space"})])
    response = client.get("/reminders/anniversary-preview?days=7")
    assert response.status_code == 200
    data = response.json()
    assert data["preview_only"] is True and data["timezone"] == "Asia/Seoul"
    assert len(data["items"]) == 3
    assert all(r["scheduled_at"].endswith("09:00:00+09:00") for r in data["items"])
    assert "version" not in response.text and "couple_id" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert [c.url.path for c in calls] == [
        "/rest/v1/rpc/get_my_couple",
        "/rest/v1/anniversaries",
        "/rest/v1/anniversaries",
        "/rest/v1/rpc/get_my_couple",
    ]
    assert calls[1].method == "GET"
    assert client.get("/reminders/anniversary-preview?days=365").status_code == 422
    client.headers.pop("Authorization")
    assert client.get("/reminders/anniversary-preview").status_code == 401


def test_preview_discards_partial_data_on_space_change_or_read_failure(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.append((200, None))
    assert client.get("/reminders/anniversary-preview").status_code == 409
    assert len(calls) == 1
    replies.extend([(200, {"id": "space"}), (503, {"message": "private-provider-error"})])
    response = client.get("/reminders/anniversary-preview")
    assert response.status_code == 503 and "private-provider-error" not in response.text
    replies.extend([(200, {"id": "space"}), (200, [occasion()]), (200, []), (200, {"id": "other"})])
    response = client.get("/reminders/anniversary-preview")
    assert response.status_code == 409 and "items" not in response.json()
