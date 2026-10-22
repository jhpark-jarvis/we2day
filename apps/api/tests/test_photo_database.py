import json
from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401


def call(dsn, user, function, *args):
    with actor(dsn, user) as connection:
        placeholders = ",".join(["%s"] * len(args))
        return connection.execute(
            f"select to_jsonb(result) from public.{function}({placeholders}) result", args
        ).fetchone()


def reserve(dsn, user=USERS[0], request_id=None, caption="하루"):
    return call(
        dsn,
        user,
        "reserve_photo",
        "2026-10-24",
        caption,
        "camera.jpg",
        "camera",
        None,
        None,
        32,
        24,
        100,
        "a" * 64,
        request_id or str(uuid4()),
    )[0]


def put(dsn, user, row, name=None):
    with actor(dsn, user) as connection:
        connection.execute(
            "insert into storage.objects(bucket_id,name,owner_id,metadata) values(%s,%s,%s,%s)",
            (
                "we2day-photos",
                name or f"{row['couple_id']}/{row['id']}.webp",
                user,
                json.dumps({"size": row["bytes"], "mimetype": "image/webp"}),
            ),
        )


def test_photo_pair_isolation_pending_finalize_and_direct_writes(database_url):
    dsn = database_url
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "create policy unrelated_broad_policy on storage.objects "
            "for all to authenticated using(true) with check(true)"
        )
    connect_pair(dsn)
    row = reserve(dsn)
    for table in ("photos", "storage.objects"):
        with actor(dsn, USERS[1]) as connection:
            assert connection.execute(f"select * from {table}").fetchall() == []
    with pytest.raises(psycopg.Error, match="photo_upload_incomplete"):
        call(dsn, USERS[0], "complete_photo", row["id"])
    for user, name in ((USERS[1], None), (USERS[2], None), (USERS[0], "unreserved.webp")):
        with pytest.raises(psycopg.Error):
            put(dsn, user, row, name)
    put(dsn, USERS[0], row)
    with actor(dsn, USERS[1]) as connection:
        assert connection.execute("select * from storage.objects").fetchall() == []
    done = call(dsn, USERS[0], "complete_photo", row["id"])[0]
    assert done["uploaded_at"] and done["created_by"] == USERS[0]
    assert call(dsn, USERS[0], "complete_photo", row["id"])[0] == done
    for user, visible in ((USERS[0], 1), (USERS[1], 1), (USERS[2], 0)):
        with actor(dsn, user) as connection:
            assert len(connection.execute("select * from photos").fetchall()) == visible
            assert len(connection.execute("select * from storage.objects").fetchall()) == visible
    with pytest.raises(psycopg.Error, match="photo_not_found"):
        call(dsn, USERS[1], "complete_photo", row["id"])
    with actor(dsn, USERS[0]) as connection:
        assert connection.execute("update storage.objects set name='overwritten'").rowcount == 0
        assert connection.execute("delete from storage.objects").rowcount == 0
    with actor(dsn, USERS[0]) as connection, pytest.raises(psycopg.Error):
        connection.execute("update photos set caption='bypass'")
    with actor(dsn, None, "anon") as connection, pytest.raises(psycopg.Error):
        connection.execute("select * from photos")
    with psycopg.connect(dsn) as connection:
        connection.execute("drop policy unrelated_broad_policy on storage.objects")


def test_photo_request_idempotency_and_payload_validation(database_url):
    dsn = database_url
    connect_pair(dsn)
    request_id = str(uuid4())
    row = reserve(dsn, request_id=request_id)
    assert reserve(dsn, request_id=request_id) == row
    with pytest.raises(psycopg.Error, match="request_conflict"):
        reserve(dsn, request_id=request_id, caption="다른 내용")
    with pytest.raises(psycopg.Error, match="invalid_photo"):
        reserve(dsn, caption="a" * 501)
    with pytest.raises(psycopg.Error, match="couple_required"):
        reserve(dsn, user=USERS[2])
