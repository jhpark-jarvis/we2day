from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401

CONTENT = {
    "title": "주말 산책",
    "date": "2026-11-01",
    "budget": 50000,
    "transport": "도보",
    "activities": [
        {"title": "공원", "time": "14:00", "place": "직접 정한 장소", "cost": None, "note": ""}
    ],
    "preparation": ["물"],
}


def change(dsn, user, id, action, version, content=None, av=0, request=None):
    return call(
        dsn,
        user,
        "change_date_plan",
        id,
        action,
        Jsonb(content) if content is not None else None,
        version,
        av,
        request or uuid4(),
    )


def test_route_privacy_retry_conflict_and_no_inferred_meeting(database_url):
    dsn = database_url
    connect_pair(dsn)
    args = ("2026-10-01", "출발", 37.5, 127.0, "도착", 37.6, 127.1, 0, uuid4())
    saved = call(dsn, USERS[0], "save_meeting_route", *args)
    assert call(dsn, USERS[0], "save_meeting_route", *args) == saved
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select start_name from public.meeting_routes").fetchone() == ("출발",)
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.meeting_routes").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[1], "save_meeting_route", *(*args[:-1], uuid4()))
    for lat in [float("nan"), float("inf"), -91.0]:
        bad = (*args[:2], lat, *args[3:-1], uuid4())
        with pytest.raises(psycopg.Error, match="invalid_route"):
            call(dsn, USERS[0], "save_meeting_route", *bad)
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("delete from public.meeting_routes")


def test_plan_confirm_atomic_shared_retry_archive_and_calendar_conflict(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    change(dsn, USERS[0], id, "save", 0, CONTENT, request=request)
    change(dsn, USERS[0], id, "save", 0, CONTENT, request=request)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select count(*) from public.appointments").fetchone() == (0,)
        assert c.execute("select count(*) from public.date_plans").fetchone() == (1,)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.date_plans").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="couple_required"):
        change(dsn, USERS[2], id, "confirm", 1)
    request = uuid4()
    change(dsn, USERS[1], id, "confirm", 1, request=request)
    change(dsn, USERS[1], id, "confirm", 1, request=request)
    updated = {**CONTENT, "title": "변경한 산책"}
    change(dsn, USERS[0], id, "save", 2, updated)
    with actor(dsn, USERS[0]) as c:
        appt_id = c.execute("select appointment_id from public.date_plans").fetchone()[0]
        assert c.execute("select title from public.appointments").fetchone() == (CONTENT["title"],)
    call(
        dsn, USERS[1], "update_appointment", appt_id, 1, "달력에서 변경", "2026-11-01", None, "", ""
    )
    with pytest.raises(psycopg.Error, match="version_conflict"):
        change(dsn, USERS[0], id, "confirm", 3, av=1)
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select version from public.date_plans").fetchone() == (3,)
    change(dsn, USERS[0], id, "confirm", 3, av=2)
    change(dsn, USERS[1], id, "archive", 4)
    with pytest.raises(psycopg.Error, match="plan_archived"):
        change(dsn, USERS[0], id, "save", 5, CONTENT)
    change(dsn, USERS[1], id, "restore", 5)
    change(dsn, USERS[0], id, "confirm", 6, av=3)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select count(*),max(version) from public.appointments").fetchone() == (
            1,
            4,
        )
        assert c.execute("select count(*) from public.meeting_routes").fetchone() == (0,)
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.date_plans set version=99")


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-02-30"},
        {"budget": "100"},
        {"title": " "},
        {"activities": [{"title": "A", "time": "24:00", "place": "", "cost": None, "note": ""}]},
        {"extra": "not allowed"},
        {"preparation": [" "]},
    ],
)
def test_direct_rpc_content_validation(database_url, changes):
    connect_pair(database_url)
    with pytest.raises(psycopg.Error, match="invalid_plan"):
        change(database_url, USERS[0], uuid4(), "save", 0, {**CONTENT, **changes})
