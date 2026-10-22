from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def search(dsn, user, query="", start="2026-10-01", end="2026-10-31", offset=0):
    with actor(dsn, user) as c:
        return c.execute(
            "select * from public.search_photos(%s,%s,%s,%s)", (start, end, query, offset)
        ).fetchall()


def test_search_literal_range_lifecycle_and_rls(database_url):
    dsn = database_url
    space = connect_pair(dsn)
    with psycopg.connect(dsn) as c:
        for date, caption, state in [
            ("2026-10-01", "산책 100% _ ' OR 1=1 --", "active"),
            ("2026-10-31", "AUTUMN 산책", "active"),
            ("2026-09-30", "산책", "active"),
            ("2026-10-02", "산책", "pending"),
            ("2026-10-03", "산책", "trash"),
            ("2026-10-04", "산책", "purging"),
        ]:
            c.execute(
                """
                insert into public.photos(couple_id,date,caption,filename,width,height,bytes,
                  sha256,created_by,uploaded_at,request_id,creation_fingerprint,
                  trashed_at,trashed_by,purge_after,purging_at)
                values(%s,%s,%s,'fixture.webp',1,1,100,repeat('a',64),%s,
                  case when %s='pending' then null else now() end,gen_random_uuid(),'fixture',
                  case when %s in ('trash','purging') then now()-interval '31 days' end,
                  case when %s in ('trash','purging') then %s::uuid end,
                  case when %s in ('trash','purging') then now()-interval '1 day' end,
                  case when %s='purging' then now() end)
                """,
                (space["id"], date, caption, USERS[0], state, state, state, USERS[0], state, state),
            )
    rows = search(dsn, USERS[1], "산책")
    assert [str(r[1]) for r in rows] == ["2026-10-31", "2026-10-01"]
    for literal in ["%", "_", "' OR 1=1 --"]:
        assert len(search(dsn, USERS[1], literal)) == 1
    assert len(search(dsn, USERS[1], "autumn")) == 1
    assert search(dsn, USERS[1], "없는 내용") == []
    assert len(search(dsn, USERS[0])) == 2
    call(dsn, USERS[2], "create_couple")
    assert search(dsn, USERS[2]) == []
    with pytest.raises(psycopg.Error, match="couple_required"):
        search(dsn, USERS[3])
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from public.search_photos('2026-10-01','2026-10-31','',0)")


def test_search_paging_and_direct_rpc_validation(database_url):
    dsn = database_url
    space = connect_pair(dsn)
    with psycopg.connect(dsn) as c:
        c.execute(
            """
            insert into public.photos(couple_id,date,caption,filename,width,height,bytes,
              sha256,created_by,uploaded_at,request_id,creation_fingerprint)
            select %s,'2026-10-01','합성 검색','fixture.webp',1,1,100,
              repeat('a',64),%s,now(),gen_random_uuid(),'fixture'
              from generate_series(1,52)
            """,
            (space["id"], USERS[0]),
        )
    first, second = search(dsn, USERS[0]), search(dsn, USERS[0], offset=50)
    assert len(first) == 51 and len(second) == 2
    assert not set(r[0] for r in first[:50]) & set(r[0] for r in second)
    assert search(dsn, USERS[0], offset=52) == []
    for start, end, query, offset in [
        ("1999-12-31", "2000-01-01", "", 0),
        ("2026-10-02", "2026-10-01", "", 0),
        ("2026-01-01", "2027-01-02", "", 0),
        ("2026-10-01", "2026-10-31", "x" * 101, 0),
        ("2026-10-01", "2026-10-31", "x\ny", 0),
        (None, "2026-10-31", "", 0),
        ("2026-10-01", "2026-10-31", None, 0),
        ("2026-10-01", "2026-10-31", "", -1),
    ]:
        with pytest.raises(psycopg.Error, match="invalid_photo_search"):
            search(dsn, USERS[0], query, start, end, offset)


def test_search_api_projection_body_and_paging(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = {"id": str(uuid4()), "date": "2026-10-01", "caption": "예시", "sha256": "private"}
    body = {"start_date": "2026-10-01", "end_date": "2026-10-31", "query": "  예시  "}
    replies.append((200, [row] * 51))
    result = client.post("/photos/search", json=body)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert len(result.json()["items"]) == 50 and result.json()["next_offset"] == 50
    assert set(result.json()["items"][0]) == {"id", "date", "caption"}
    assert calls[-1].url.path.endswith("/rpc/search_photos")
    assert calls[-1].url.query == b""
    assert b'"p_query":"' in calls[-1].content and "예시" in calls[-1].content.decode()
    for change in [
        {"end_date": "2026-09-30"},
        {"query": "x" * 101},
        {"query": "x\ny"},
        {"start_date": "2026-02-30"},
        {"offset": -1},
        {"couple_id": str(uuid4())},
        {"start_date": "2026-01-01", "end_date": "2027-01-02"},
    ]:
        before = len(calls)
        assert client.post("/photos/search", json={**body, **change}).status_code == 422
        assert len(calls) == before
    assert (
        client.post(
            "/photos/search", content="x" * 4097, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
    assert client.post("/photos/search", content="bad").status_code == 415
    replies.append((200, []))
    assert client.post("/photos/search", json=body).json() == {"items": [], "next_offset": None}
    client.headers.pop("Authorization")
    assert client.post("/photos/search", json=body).status_code == 401
