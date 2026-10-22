from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_shared_wish_retry_conflict_archive_and_isolation(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    args = (id, "함께 산책", "activity", "물 준비", False, False, 0, request)
    saved = call(dsn, USERS[0], "save_wish", *args)
    assert call(dsn, USERS[0], "save_wish", *args) == saved
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select title from public.wishes").fetchone() == ("함께 산책",)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.wishes").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "save_wish", *args)
    call(dsn, USERS[1], "save_wish", id, "함께 산책", "activity", "메모", True, True, 1, uuid4())
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_wish", *(*args[:-1], uuid4()))
    call(dsn, USERS[0], "save_wish", id, "함께 산책", "activity", "메모", True, False, 2, uuid4())
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select done,archived from public.wishes").fetchone() == (True, False)
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="wish_not_found"):
        call(dsn, USERS[2], "save_wish", *args)
    for bad in ["", " " * 10, "x" * 101]:
        with pytest.raises(psycopg.Error, match="invalid_wish"):
            call(dsn, USERS[0], "save_wish", uuid4(), bad, "place", "", False, False, 0, uuid4())
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("delete from public.wishes")
