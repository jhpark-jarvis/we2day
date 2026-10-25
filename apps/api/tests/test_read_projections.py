from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401
from test_photo_database import call, put, reserve
from test_routes_plans import CONTENT, change


def test_plan_projection_states_isolation_and_bounds(database_url):
    dsn = database_url
    connect_pair(dsn)
    draft, confirmed, changed, archived = [uuid4() for _ in range(4)]
    for id in [draft, confirmed, changed, archived]:
        change(dsn, USERS[0], id, "save", 0, CONTENT)
    for id in [confirmed, changed]:
        change(dsn, USERS[0], id, "confirm", 1)
    change(dsn, USERS[0], changed, "save", 2, {**CONTENT, "title": "변경"})
    change(dsn, USERS[0], archived, "archive", 1)
    with actor(dsn, USERS[1]) as c:
        rows = c.execute(
            "select id,status,activity_count from list_plan_summaries(false,0)"
        ).fetchall()
        assert {str(id): state for id, state, _ in rows} == {
            str(draft): "draft",
            str(confirmed): "confirmed",
            str(changed): "changed",
        }
        assert all(count == 1 for _, _, count in rows)
        assert c.execute("select status from list_plan_summaries(true,0)").fetchall() == [
            ("archived",)
        ]
        assert c.execute("select * from list_plan_summaries(false,50)").fetchall() == []
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select * from list_plan_summaries(false,0)").fetchall() == []
    for value in [-1, 100001]:
        with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.Error, match="invalid_plan"):
            c.execute("select * from list_plan_summaries(false,%s)", (value,))
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from list_plan_summaries(false,0)")


def test_album_dates_only_completed_normal_shared_photos(database_url):
    dsn = database_url
    connect_pair(dsn)
    reserve(dsn)  # pending uploads do not enable dates
    rows = [reserve(dsn) for _ in range(3)]
    for row in rows:
        put(dsn, USERS[0], row)
        call(dsn, USERS[0], "complete_photo", row["id"])
    call(dsn, USERS[0], "change_photo_lifecycle", rows[-1]["id"], "trash", 1, uuid4(), "")
    with actor(dsn, USERS[1]) as c:
        assert c.execute(
            "select to_jsonb(t) from photo_album_dates('2026-10-01') t"
        ).fetchall() == [({"date": "2026-10-24", "count": 2},)]
        assert c.execute("select * from photo_album_dates('2026-11-01')").fetchall() == []
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select * from photo_album_dates('2026-10-01')").fetchall() == []
    for value in ["2026-10-02", "1999-12-01", "2101-01-01"]:
        with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.Error, match="invalid_photo_search"):
            c.execute("select * from photo_album_dates(%s)", (value,))
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from photo_album_dates('2026-10-01')")
