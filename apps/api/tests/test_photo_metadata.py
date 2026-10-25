from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401
from test_photo_database import call, put, reserve


def test_edit_pair_permissions_idempotency_and_original_invariants(database_url):
    dsn = database_url
    connect_pair(dsn)
    row = reserve(dsn)
    put(dsn, USERS[0], row)
    original = call(dsn, USERS[0], "complete_photo", row["id"])[0]
    args = (row["id"], "2026-11-02", "수정 설명", 1, uuid4())
    edited = call(dsn, USERS[1], "edit_photo", *args)[0]
    assert edited["date"] == "2026-11-02" and edited["lifecycle_version"] == 2
    assert call(dsn, USERS[1], "edit_photo", *args)[0] == edited
    changed = {
        "date",
        "caption",
        "lifecycle_version",
        "metadata_request_id",
        "metadata_actor",
        "metadata_fingerprint",
    }
    assert {k: v for k, v in edited.items() if k not in changed} == {
        k: v for k, v in original.items() if k not in changed
    }
    for user, payload, error in [
        (USERS[0], args, "request_conflict"),
        (USERS[2], (*args[:-1], uuid4()), "photo_not_found"),
        (USERS[0], (*args[:-1], uuid4()), "version_conflict"),
        (USERS[1], (row["id"], "2026-11-03", "수정 설명", 1, args[-1]), "request_conflict"),
    ]:
        with pytest.raises(psycopg.Error, match=error):
            call(dsn, user, "edit_photo", *payload)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "change_photo_lifecycle", row["id"], "trash", 1, uuid4(), "")
    call(dsn, USERS[0], "change_photo_lifecycle", row["id"], "trash", 2, uuid4(), "")
    with pytest.raises(psycopg.Error, match="photo_state_conflict"):
        call(dsn, USERS[1], "edit_photo", row["id"], "2026-11-03", "", 3, uuid4())
    pending = reserve(dsn)
    with pytest.raises(psycopg.Error, match="photo_not_found"):
        call(dsn, USERS[0], "edit_photo", pending["id"], "2026-11-03", "", 1, uuid4())
    for date, caption in [
        ("1999-12-31", ""),
        ("2026-11-03", "x" * 501),
        ("2026-11-03", "bad\ncaption"),
    ]:
        with pytest.raises(psycopg.Error, match="invalid_photo_metadata"):
            call(dsn, USERS[0], "edit_photo", row["id"], date, caption, 3, uuid4())
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from edit_photo(%s,'2026-11-01','',1,%s)", (row["id"], uuid4()))


def test_metadata_api_strict_fields_and_no_storage(upstream):  # noqa: F811
    client, calls, _ = upstream
    id = uuid4()
    body = {"date": "2026-11-01", "caption": "", "expected_version": 1, "request_id": str(uuid4())}
    for extra in [
        {"created_by": str(uuid4())},
        {"caption": "x" * 501},
        {"date": "bad"},
        {"expected_version": 0},
    ]:
        assert client.post(f"/photos/{id}/metadata", json={**body, **extra}).status_code == 422
    assert calls == []
