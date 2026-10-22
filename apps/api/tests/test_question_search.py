from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def search(dsn, user, query="", offset=0, start="2026-10-01", end="2026-10-31"):
    with actor(dsn, user) as c:
        return c.execute(
            "select * from public.search_questions(%s,%s,%s,%s)", (start, end, query, offset)
        ).fetchall()


def test_prompt_search_scope_paging_and_private_answers(database_url):
    dsn = database_url
    connect_pair(dsn)
    question_id = str(uuid4())
    call(
        dsn,
        USERS[0],
        "create_question",
        question_id,
        "2026-10-01",
        "AUTUMN 100% _ ' OR 1=1 --",
        str(uuid4()),
    )
    call(
        dsn,
        USERS[0],
        "save_question_answer",
        question_id,
        "비공개답변 전용검색어",
        False,
        False,
        0,
        str(uuid4()),
    )
    for user in USERS[:2]:
        for literal in ["autumn", "%", "_", "' OR 1=1 --"]:
            rows = search(dsn, user, literal)
            assert len(rows) == 1 and len(rows[0]) == 3 and str(rows[0][0]) == question_id
        assert search(dsn, user, "비공개답변 전용검색어") == []
    call(dsn, USERS[2], "create_couple")
    assert search(dsn, USERS[2]) == []
    with pytest.raises(psycopg.Error, match="couple_required"):
        search(dsn, USERS[3])
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from public.search_questions(now()::date,now()::date,'')")
    for kwargs in [
        {"start": "1999-12-31"},
        {"end": "2101-01-01"},
        {"end": "2026-09-30"},
        {"start": "2025-01-01"},
        {"query": None},
        {"query": "x" * 101},
        {"query": "x\ny"},
        {"offset": -1},
        {"offset": 100001},
    ]:
        with pytest.raises(psycopg.Error, match="invalid_question_search"):
            search(dsn, USERS[0], **kwargs)
    for i in range(52):
        call(
            dsn,
            USERS[1],
            "create_question",
            str(uuid4()),
            "2026-10-31",
            f"페이지 {i}",
            str(uuid4()),
        )
    a, b = search(dsn, USERS[0], "페이지"), search(dsn, USERS[1], "페이지", offset=50)
    assert len(a) == 51 and len(b) == 2
    assert not set(r[0] for r in a[:50]) & set(r[0] for r in b)
    assert search(dsn, USERS[0], "페이지", start="2026-10-01", end="2026-10-30") == []


def test_question_search_exact_route_projection_and_validation(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = dict(
        id=str(uuid4()), date="2026-10-01", prompt="합성 질문", content="private", skipped=True
    )
    body = dict(start_date="2026-10-01", end_date="2026-10-31", query=" 합성 ")
    replies.append((200, [row] * 51))
    result = client.post("/questions/search", json=body)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    assert len(result.json()["items"]) == 50 and result.json()["next_offset"] == 50
    assert set(result.json()["items"][0]) == {"id", "date", "prompt"}
    assert len(calls) == 1 and calls[-1].url.path.endswith("/rpc/search_questions")
    assert calls[-1].url.query == b""
    for change in [
        {"query": "x\ny"},
        {"query": "x" * 101},
        {"offset": True},
        {"end_date": "2026-02-30"},
        {"author_id": str(uuid4())},
    ]:
        before = len(calls)
        assert client.post("/questions/search", json={**body, **change}).status_code == 422
        assert len(calls) == before
    assert (
        client.post(
            "/questions/search", content="x" * 4097, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
    assert client.post("/questions/search", content="bad").status_code == 415
    client.headers.pop("Authorization")
    assert client.post("/questions/search", json=body).status_code == 401
