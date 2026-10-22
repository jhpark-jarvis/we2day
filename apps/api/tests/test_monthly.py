from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_photo_database import call as photo_call
from test_photo_database import put, reserve


def test_monthly_counts_originals_trash_pending_and_couple_isolation(database_url):
    dsn = database_url
    connect_pair(dsn)
    for index in range(3):
        photo = reserve(dsn, caption=f"합성 사진 {index}")
        put(dsn, USERS[0], photo)
        photo_call(dsn, USERS[0], "complete_photo", photo["id"])
        if index == 1:
            with psycopg.connect(dsn) as c:
                c.execute("update public.photos set date='2026-09-25' where id=%s", (photo["id"],))
        if index == 2:
            call(dsn, USERS[0], "change_photo_lifecycle", photo["id"], "trash", 1, uuid4(), "")
    reserve(dsn)  # An incomplete reservation must not appear in a memory or total.
    with psycopg.connect(dsn) as c:
        c.execute("update public.photos set date='2026-09-24' where date='2026-10-24'")
    call(dsn, USERS[0], "save_meeting_day", "2026-09-24", True, "만난 날", 0, uuid4())
    call(dsn, USERS[0], "save_meeting_day", "2026-09-25", False, "메모만", 0, uuid4())
    call(
        dsn,
        USERS[0],
        "save_meeting_route",
        "2026-09-01",
        "출발",
        37.5,
        127.0,
        "도착",
        37.6,
        127.1,
        0,
        uuid4(),
    )
    result = call(dsn, USERS[1], "get_monthly_memories", "2026-09-01")[0]
    assert (result["meeting_count"], result["photo_count"], result["route_count"]) == (1, 2, 1)
    assert [day["date"] for day in result["days"]] == ["2026-09-01", "2026-09-24", "2026-09-25"]
    assert len(result["photos"]) == 2
    assert all(set(photo) == {"id", "date", "caption"} for photo in result["photos"])
    empty = call(dsn, USERS[1], "get_monthly_memories", "2026-11-01")[0]
    assert empty["photo_count"] == 0 and empty["days"] == [] and empty["photos"] == []
    call(dsn, USERS[2], "create_couple")
    other = call(dsn, USERS[2], "get_monthly_memories", "2026-09-01")[0]
    assert other["meeting_count"] == other["photo_count"] == other["route_count"] == 0
    for month in ["2026-09-02", "1999-12-01", "2101-01-01"]:
        with pytest.raises(psycopg.Error, match="invalid_request"):
            call(dsn, USERS[0], "get_monthly_memories", month)
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.get_monthly_memories('2026-09-01')")


def test_monthly_totals_exceed_preview_and_rest_page_without_inferred_meetings(database_url):
    dsn = database_url
    space = connect_pair(dsn)
    call(dsn, USERS[0], "create_appointment", "계획만 있음", "2026-09-01", None, "", "", uuid4())
    # Synthetic read-model rows only: no Storage files or personal photos are created.
    with psycopg.connect(dsn) as c:
        c.execute(
            """
          insert into public.photos(couple_id,date,caption,filename,width,height,bytes,
            sha256,created_by,uploaded_at,request_id,creation_fingerprint)
          select %s,'2026-09-01','합성 읽기 모델','fixture.webp',1,1,100,
            repeat('a',64),%s,now(),gen_random_uuid(),'fixture'
          from generate_series(1,1001)
        """,
            (space["id"], USERS[0]),
        )
    result = call(dsn, USERS[1], "get_monthly_memories", "2026-09-01")[0]
    assert result["photo_count"] == result["days"][0]["photo_count"] == 1001
    assert len(result["photos"]) == 6
    assert result["meeting_count"] == result["route_count"] == 0
