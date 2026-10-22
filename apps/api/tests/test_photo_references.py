from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def search(dsn, user, field="caption", uploader="all", query="", offset=0, start="2026-10-01"):
    with actor(dsn, user) as c:
        return c.execute(
            "select * from public.search_photo_references(%s,'2026-10-31',%s,%s,%s,%s)",
            (start, query, field, uploader, offset),
        ).fetchall()


def test_reference_filters_rls_lifecycle_and_paging(database_url):
    dsn = database_url
    space = connect_pair(dsn)
    with psycopg.connect(dsn) as c:
        for author, device, state in [
            (USERS[0], "ExamplePhone 100%", "active"),
            (USERS[1], None, "active"),
            (USERS[0], "ExamplePhone", "pending"),
            (USERS[0], "ExamplePhone", "trash"),
            (USERS[0], "ExamplePhone", "purging"),
        ]:
            c.execute(
                """
                insert into public.photos(couple_id,date,caption,filename,device,captured_at,
                  width,height,bytes,sha256,created_by,uploaded_at,request_id,creation_fingerprint,
                  trashed_at,trashed_by,purge_after,purging_at)
                values(%s,'2026-10-01','합성','IMG_100%%.jpg',%s,'2026-10-01 12:30:00',
                  1,1,100,repeat('a',64),%s,
                  case when %s='pending' then null else now() end,gen_random_uuid(),'fixture',
                  case when %s in ('trash','purging') then now()-interval '31 days' end,
                  case when %s in ('trash','purging') then %s::uuid end,
                  case when %s in ('trash','purging') then now()-interval '1 day' end,
                  case when %s='purging' then now() end)
                """,
                (space["id"], device, author, state, state, state, author, state, state),
            )
    assert len(search(dsn, USERS[0])) == 2
    assert len(search(dsn, USERS[1], "filename", query="img_100%")) == 2
    assert len(search(dsn, USERS[1], "device", query="examplephone 100%")) == 1
    mine = search(dsn, USERS[0], uploader="mine")
    partner = search(dsn, USERS[1], uploader="partner")
    assert len(mine) == len(partner) == 1
    assert mine[0][0] == partner[0][0] and mine[0][-1] is True and partner[0][-1] is False
    assert mine[0][4:6] == ("ExamplePhone 100%", "2026-10-01 12:30:00")
    assert search(dsn, USERS[0], "device", query="' OR 1=1 --") == []
    call(dsn, USERS[2], "create_couple")
    assert search(dsn, USERS[2]) == []
    with pytest.raises(psycopg.Error, match="couple_required"):
        search(dsn, USERS[3])
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute(
            "select * from public.search_photo_references("
            "now()::date,now()::date,'','caption','all')"
        )
    for kwargs in [
        {"field": "sha256"},
        {"uploader": USERS[0]},
        {"field": None},
        {"query": "x\ny"},
        {"query": "x" * 101},
        {"offset": -1},
        {"start": "2025-01-01"},
    ]:
        with pytest.raises(psycopg.Error, match="invalid_photo_search"):
            search(dsn, USERS[0], **kwargs)
    with psycopg.connect(dsn) as c:
        c.execute(
            """insert into public.photos(couple_id,date,caption,filename,width,height,bytes,
              sha256,created_by,uploaded_at,request_id,creation_fingerprint)
              select %s,'2026-10-31','페이지','page.jpg',1,1,100,repeat('a',64),%s,
              now(),gen_random_uuid(),'fixture' from generate_series(1,52)""",
            (space["id"], USERS[0]),
        )
    a, b = search(dsn, USERS[0], query="페이지"), search(dsn, USERS[0], query="페이지", offset=50)
    assert len(a) == 51 and len(b) == 2
    assert not set(r[0] for r in a[:50]) & set(r[0] for r in b)


def test_reference_api_projection_filters_and_limits(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = dict(
        id=str(uuid4()),
        date="2026-10-01",
        caption="예시",
        filename="IMG.jpg",
        device=None,
        captured_at=None,
        uploaded_at="2026-10-01T00:00:00Z",
        uploaded_by_me=False,
        sha256="private",
        created_by=str(uuid4()),
    )
    body = dict(
        start_date="2026-10-01",
        end_date="2026-10-31",
        field="filename",
        uploader="partner",
        query=" IMG ",
    )
    replies.append((200, [row] * 51))
    result = client.post("/photos/reference-search", json=body)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    assert len(result.json()["items"]) == 50 and result.json()["next_offset"] == 50
    assert set(result.json()["items"][0]) == set(row) - {"sha256", "created_by"}
    assert calls[-1].url.path.endswith("/rpc/search_photo_references")
    assert calls[-1].url.query == b"" and b'"p_uploader":"partner"' in calls[-1].content
    for change in [
        {"field": "sha256"},
        {"uploader": str(uuid4())},
        {"offset": True},
        {"query": "x\ny"},
        {"end_date": "2025-01-01"},
        {"created_by": str(uuid4())},
    ]:
        before = len(calls)
        assert client.post("/photos/reference-search", json={**body, **change}).status_code == 422
        assert len(calls) == before
    assert (
        client.post(
            "/photos/reference-search",
            content="x" * 4097,
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )
    assert client.post("/photos/reference-search", content="bad").status_code == 415
    client.headers.pop("Authorization")
    assert client.post("/photos/reference-search", json=body).status_code == 401
