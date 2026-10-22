import json
from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import ROW, USER, upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_profile_projection_validation_and_no_actor_input(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = {
        "user_id": USER,
        "display_name": "예시 이름",
        "version": 1,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row])])
    view = client.get("/profiles")
    assert view.json()["mine"]["display_name"] == "예시 이름"
    assert "last_fingerprint" not in view.text
    assert calls[-1].url.params["select"] == "user_id,display_name,version,updated_at"
    body = {"display_name": "예시 이름", "expected_version": 0, "request_id": str(uuid4())}
    assert client.post("/profiles", json=body).status_code == 200
    assert "p_user_id" not in json.loads(calls[-1].content)
    assert client.post("/profiles", json={**body, "user_id": USER}).status_code == 422
    for name in ("", "  ", " padded", "line\nbreak", "a" * 41):
        assert client.post("/profiles", json={**body, "display_name": name}).status_code == 422
    client.headers.clear()
    assert client.get("/profiles").status_code == 401


def test_profile_self_write_couple_read_retry_and_conflict(database_url):
    dsn = database_url
    connect_pair(dsn)
    req = uuid4()
    first = call(dsn, USERS[0], "save_profile", "예시 하나", 0, req)
    assert call(dsn, USERS[0], "save_profile", "예시 하나", 0, req) == first
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[0], "save_profile", "다른 이름", 0, req)
    for user in USERS[:2]:
        with actor(dsn, user) as db:
            assert db.execute("select display_name from public.user_profiles").fetchall() == [
                ("예시 하나",)
            ]
    with actor(dsn, USERS[2]) as db:
        assert db.execute("select display_name from public.user_profiles").fetchall() == []
    second = call(dsn, USERS[1], "save_profile", "예시 둘", 0, uuid4())
    assert str(second[0]) == USERS[1]
    changed = call(dsn, USERS[0], "save_profile", "바꾼 이름", 1, uuid4())
    assert changed[1:3] == ("바꾼 이름", 2)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_profile", "이전 입력", 1, uuid4())
    for name in ("", " ", "\n", " a", "a" * 41):
        with pytest.raises(psycopg.Error, match="invalid_profile"):
            call(dsn, USERS[0], "save_profile", name, 2, uuid4())
    for statement in (
        "update public.user_profiles set display_name='tamper'",
        "select last_fingerprint from public.user_profiles",
    ):
        with actor(dsn, USERS[1]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(statement)
    with actor(dsn, None, "anon") as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select display_name from public.user_profiles")
