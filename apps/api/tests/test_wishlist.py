from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_wish_location_roundtrip_retry_legacy_edit_export_and_isolation(database_url):
    from we2day_api.wishlist import WishChange, save_wish

    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    args = (
        id,
        "합성 카페",
        "place",
        "메모",
        False,
        False,
        0,
        request,
        "합성 카페 (서울특별시 성동구 합성로 10)",
        "https://naver.me/fixture123",
    )
    saved = call(dsn, USERS[0], "save_wish_location", *args)
    assert call(dsn, USERS[0], "save_wish_location", *args) == saved
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select place,map_url from public.wishes").fetchone() == args[-2:]
        exported = c.execute(
            "select public.export_record_snapshot('wishes','2026-01-01','2026-12-31')"
        ).fetchone()[0]
        assert exported[0]["map_url"] == args[-1]
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.wishes").fetchone() == (0,)
    for changed in [(*args[:-1], "https://naver.me/changed"), (*args[:-2], "다른 장소", args[-1])]:
        with pytest.raises(psycopg.Error, match="request_conflict"):
            call(dsn, USERS[0], "save_wish_location", *changed)
    call(
        dsn,
        USERS[1],
        "save_wish",
        id,
        "수정 이름",
        "place",
        "구버전 메모",
        False,
        False,
        1,
        uuid4(),
    )
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select place,map_url,version from public.wishes").fetchone() == (
            *args[-2:],
            2,
        )
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_wish_location", *(*args[:7], uuid4(), *args[8:]))
    for link in ["https://example.com/a", "https://naver.me.evil/a", "javascript:alert(1)"]:
        with pytest.raises(psycopg.Error, match="invalid_wish"):
            call(dsn, USERS[0], "save_wish_location", *(*args[:7], uuid4(), args[-2], link))
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="wish_not_found"):
        call(dsn, USERS[2], "save_wish_location", *args)

    class Store:
        def rpc(self, name, body):
            self.name, self.body = name, body
            return [body]

    store = Store()
    common = dict(title="이름", kind="place", expected_version=0, request_id=str(uuid4()))
    save_wish(id, WishChange(**common), store)
    assert store.name == "save_wish" and "p_place" not in store.body
    save_wish(id, WishChange(**common, place=args[-2], map_url=args[-1]), store)
    assert store.name == "save_wish_location" and store.body["p_map_url"] == args[-1]


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
