from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401


def test_meeting_api_validation_minimum_fields_and_version(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = {
        "date": "2026-10-10",
        "met": True,
        "note": "산책",
        "version": 1,
        "updated_by": USERS[0],
        "updated_at": "2026-10-19T00:00:00Z",
        "last_request_id": "private",
        "couple_id": "private",
    }
    body = {"met": True, "note": "산책", "expected_version": 0, "request_id": str(uuid4())}
    replies.extend([(200, [row]), (200, [row])])
    assert client.post("/meetings/2026-10-10", json=body).json()["version"] == 1
    result = client.get("/meetings?month=2026-10")
    assert "private" not in result.text and result.json()[0]["met"] is True
    before = len(calls)
    assert client.post("/meetings/2100-12-31", json=body).status_code == 422
    assert client.post("/meetings/2026-10-10", json={**body, "met": "false"}).status_code == 422
    assert len(calls) == before


def test_meeting_sql_pair_sharing_retry_conflict_unmark_and_future(database_url):
    dsn = database_url
    connect_pair(dsn)
    request_id = uuid4()

    def save(user, met=True, note="산책", version=0, request=None, day="2026-10-10"):
        with actor(dsn, user) as connection:
            return connection.execute(
                "select to_jsonb(r) from public.save_meeting_day(%s,%s,%s,%s,%s) r",
                (day, met, note, version, request or uuid4()),
            ).fetchone()[0]

    row = save(USERS[0], request=request_id)
    assert save(USERS[0], request=request_id) == row
    for user, count in ((USERS[1], 1), (USERS[2], 0)):
        with actor(dsn, user) as connection:
            assert len(connection.execute("select * from meeting_days").fetchall()) == count
    unmarked = save(USERS[1], met=False, version=1)
    assert unmarked["met"] is False and unmarked["note"] == "산책" and unmarked["version"] == 2
    with pytest.raises(psycopg.Error, match="version_conflict"):
        save(USERS[0], version=1)
    with pytest.raises(psycopg.Error, match="couple_required"):
        save(USERS[2])
    with pytest.raises(psycopg.Error, match="invalid_meeting_day"):
        save(USERS[0], day="2100-12-31")
    with actor(dsn, USERS[0]) as connection, pytest.raises(psycopg.Error):
        connection.execute("update meeting_days set note='bypass'")
