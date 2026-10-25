import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from PIL import Image
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401
from test_photo_database import call, put, reserve
from test_photos import image_bytes

from we2day_api.photo_audit import read_audit
from we2day_api.photos import checked_preview, normalized_image


def test_preview_rejects_metadata_animation_trailing_data_and_dimensions():
    clean, width, height = normalized_image(image_bytes((1200, 1600)), thumbnail=True)
    assert checked_preview(clean) == (width, height) == (480, 640)
    animated = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(
        animated,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (32, 24), "blue")],
        duration=100,
        loop=0,
    )
    for bad in [
        image_bytes(exif=b"Exif\0\0private"),
        image_bytes(xmp=b"private"),
        image_bytes(icc_profile=b"private"),
        clean + b"trailing",
        image_bytes((641, 1)),
        animated.getvalue(),
    ]:
        with pytest.raises(HTTPException):
            checked_preview(bad)


def test_preview_policies_lifecycle_audit_and_two_object_purge(database_url):
    dsn = database_url
    connect_pair(dsn)
    row = reserve(dsn)
    name = f"{row['couple_id']}/{row['id']}.preview.webp"
    with psycopg.connect(dsn) as c:
        c.execute(
            "create policy unrelated_preview_broad on storage.objects "
            "for all to authenticated using(true) with check(true)"
        )
    with pytest.raises(psycopg.Error):
        put(dsn, USERS[1], row, name)  # partner cannot write a pending upload
    put(dsn, USERS[0], row)
    call(dsn, USERS[0], "complete_photo", row["id"])
    with pytest.raises(psycopg.Error):
        put(dsn, USERS[2], row, name)
    put(dsn, USERS[1], row, name)
    call(dsn, USERS[1], "complete_photo_preview", row["id"], "b" * 64, 100, 32, 24)
    call(dsn, USERS[0], "complete_photo_preview", row["id"], "b" * 64, 100, 32, 24)
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select lifecycle_version from photos").fetchone() == (1,)
        assert c.execute("delete from storage.objects").rowcount == 0
        assert c.execute("update storage.objects set name='bad'").rowcount == 0
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select * from storage.objects").fetchall() == []
    with psycopg.connect(dsn) as c:
        c.execute(
            "alter table storage.objects add column if not exists "
            "created_at timestamptz default now()"
        )
        c.execute("update storage.objects set created_at=now()-interval '25 hours'")
    result = read_audit({"conninfo": dsn})
    assert result["unreferenced_objects"] == result["missing_objects"] == 0
    assert result["storage_objects"] == 2 and result["storage_bytes"] == 200
    call(dsn, USERS[0], "change_photo_lifecycle", row["id"], "trash", 1, uuid4(), "")
    with pytest.raises(psycopg.Error, match="photo_state_conflict"):
        call(dsn, USERS[0], "complete_photo_preview", row["id"], "b" * 64, 100, 32, 24)
    with psycopg.connect(dsn) as c:
        c.execute(
            "update photos set trashed_at=now()-interval '31 days',"
            "purge_after=now()-interval '1 day'"
        )
    call(dsn, USERS[1], "change_photo_lifecycle", row["id"], "purge", 2, uuid4(), "영구 삭제")
    with actor(dsn, USERS[0]) as c:
        c.execute(
            "delete from storage.objects where name like '%%.webp' "
            "and name not like '%%.preview.webp'"
        )
    with pytest.raises(psycopg.Error, match="photo_delete_incomplete"):
        call(dsn, USERS[0], "finish_photo_purge", row["id"])
    with actor(dsn, USERS[1]) as c:
        assert c.execute("delete from storage.objects").rowcount == 1
    call(dsn, USERS[1], "finish_photo_purge", row["id"])
    with psycopg.connect(dsn) as c:
        c.execute("drop policy unrelated_preview_broad on storage.objects")


def test_preview_insert_cannot_race_past_trash(database_url):
    dsn = database_url
    connect_pair(dsn)
    row = reserve(dsn)
    put(dsn, USERS[0], row)
    call(dsn, USERS[0], "complete_photo", row["id"])
    with psycopg.connect(dsn) as locked:
        locked.execute(
            "update photos set trashed_at=now(),trashed_by=%s,"
            "purge_after=now()+interval '30 days' where id=%s",
            (USERS[0], row["id"]),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                put, dsn, USERS[1], row, f"{row['couple_id']}/{row['id']}.preview.webp"
            )
            locked.commit()
            with pytest.raises(psycopg.Error):
                future.result(timeout=5)
    with psycopg.connect(dsn) as c:
        assert c.execute("select count(*) from storage.objects").fetchone() == (1,)


def test_preview_insert_holds_parent_until_object_commit(database_url):
    dsn = database_url
    connect_pair(dsn)
    row = reserve(dsn)
    put(dsn, USERS[0], row)
    call(dsn, USERS[0], "complete_photo", row["id"])
    with actor(dsn, USERS[1]) as c, ThreadPoolExecutor(max_workers=1) as pool:
        c.execute(
            "insert into storage.objects(bucket_id,name,owner_id,metadata) "
            "values('we2day-photos',%s,%s,%s)",
            (
                f"{row['couple_id']}/{row['id']}.preview.webp",
                USERS[1],
                '{"size":100,"mimetype":"image/webp"}',
            ),
        )
        future = pool.submit(
            call, dsn, USERS[0], "change_photo_lifecycle", row["id"], "trash", 1, uuid4(), ""
        )
        try:
            with pytest.raises(TimeoutError):
                future.result(timeout=0.25)
        finally:
            c.commit()
        assert future.result(timeout=5)[0]["lifecycle_version"] == 2
