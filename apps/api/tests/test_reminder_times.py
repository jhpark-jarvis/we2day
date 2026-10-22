from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from test_notification_preview import occasion

from we2day_api.reminder_times import SEOUL, ScheduleLimitError, reminder_times


def clock(day, hour=9):
    return datetime.fromisoformat(f"{day}T{hour:02}:00:00+09:00")


def test_adjacent_windows_never_duplicate_a_boundary_instant():
    rows = [occasion(date="2026-11-01")]
    original = deepcopy(rows)
    boundary = clock("2026-10-25")
    before = reminder_times(rows, boundary - timedelta(seconds=1), boundary, max_items=2000)
    after = reminder_times(rows, boundary, boundary + timedelta(seconds=1), max_items=2000)
    assert before == []
    assert len(after) == 1
    assert after[0].lead_days == 7 and after[0].scheduled_at == boundary
    assert rows == original


def test_utc_window_and_longer_window_use_the_same_gregorian_rules():
    birthday = occasion(kind="birthday", date=None, month=2, day=29)
    rows = reminder_times(
        [birthday], datetime(2027, 2, 21, tzinfo=UTC), clock("2027-03-01"), max_items=2000
    )
    assert [item.lead_days for item in rows] == [7, 1, 0]
    assert {item.occurrence_date for item in rows} == {date(2027, 2, 28)}
    assert all(item.scheduled_at.tzinfo == SEOUL for item in rows)
    leap = reminder_times([birthday], clock("2028-02-22", 0), clock("2028-03-01"), max_items=2000)
    assert {item.occurrence_date for item in leap} == {date(2028, 2, 29)}
    annual = occasion(date="2020-01-01")
    two_years = reminder_times(
        [annual], clock("2026-12-25", 0), clock("2027-12-26", 0), max_items=2000
    )
    assert [(item.occurrence_date, item.lead_days) for item in two_years] == [
        (date(2027, 1, 1), 7),
        (date(2027, 1, 1), 1),
        (date(2027, 1, 1), 0),
        (date(2028, 1, 1), 7),
    ]


def test_one_off_future_source_order_and_empty_windows():
    past = occasion(date="2026-01-01", annual=False)
    future = occasion(id=str(UUID(int=12)), date="2028-01-01")
    recurring = occasion(id=str(UUID(int=11)), date="2020-01-01")
    start, end = clock("2026-12-25", 0), clock("2027-01-02", 0)
    items = reminder_times([past, future, recurring], start, end, max_items=2000)
    assert len(items) == 3 and {item.anniversary_id for item in items} == {UUID(int=11)}
    assert items == reminder_times([recurring, future, past], start, end, max_items=2000)
    assert reminder_times([recurring], start, start, max_items=2000) == []


def test_delivery_identity_separates_version_occurrence_lead_recipient_and_device():
    item = reminder_times([occasion()], clock("2026-10-25"), clock("2026-10-26"), max_items=2000)[0]
    owner, device = UUID(int=30), "a" * 64
    identity = item.delivery_key(owner, device)
    assert len(identity) == 64 and item.delivery_key(owner, device) == identity
    assert replace(item, title="제목은 식별키에 넣지 않음").delivery_key(owner, device) == identity
    assert item.title not in repr(item)
    changed = [
        replace(item, source_version=2).delivery_key(owner, device),
        replace(item, occurrence_date=date(2027, 11, 1)).delivery_key(owner, device),
        replace(item, lead_days=1).delivery_key(owner, device),
        item.delivery_key(UUID(int=31), device),
        item.delivery_key(owner, "b" * 64),
    ]
    assert len({identity, *changed}) == 6
    with pytest.raises(ValueError, match="invalid_delivery_identity"):
        item.delivery_key(owner, "https://provider.example/private-capability")


@pytest.mark.parametrize(
    "start,end,limit",
    [
        (datetime(2026, 1, 1), clock("2026-01-02"), 2000),
        (clock("2026-01-01"), datetime(2026, 1, 2), 2000),
        (clock("2026-01-02"), clock("2026-01-01"), 2000),
        (clock("2026-01-01"), clock("2027-01-04"), 2000),
        (clock("2026-01-01"), clock("2026-01-02"), 0),
        (clock("2026-01-01"), clock("2026-01-02"), 2001),
        (clock("2026-01-01"), clock("2026-01-02"), True),
    ],
)
def test_invalid_window_never_returns_partial_candidates(start, end, limit):
    with pytest.raises(ValueError, match="invalid_schedule_window"):
        reminder_times([], start, end, max_items=limit)


def test_oversized_sources_or_results_fail_as_a_whole_and_versions_are_required():
    start, end = clock("2026-10-24", 0), clock("2026-11-02", 0)
    with pytest.raises(ScheduleLimitError):
        reminder_times([occasion()] * 3, start, end, max_items=2)
    with pytest.raises(ScheduleLimitError):
        reminder_times([occasion()], start, end, max_items=2)
    for version in [0, -1, True, "1", 2_147_483_648]:
        with pytest.raises(ValueError, match="invalid_source_version"):
            reminder_times([occasion(version=version)], start, end, max_items=2000)
