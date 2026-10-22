from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_question_author_privacy_share_withdraw_skip_and_retry(database_url):
    dsn = database_url
    connect_pair(dsn)
    q, request = uuid4(), uuid4()
    args = (q, "2026-10-19", "함께 해보고 싶은 일은?", request)
    created = call(dsn, USERS[0], "create_question", *args)
    assert call(dsn, USERS[0], "create_question", *args) == created
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "create_question", *args)

    def save(user, version, text="개인 답변", shared=False, skipped=False, req=None):
        return call(
            dsn, user, "save_question_answer", q, text, shared, skipped, version, req or uuid4()
        )

    req = uuid4()
    first = save(USERS[0], 0, req=req)
    assert save(USERS[0], 0, req=req) == first
    for user in USERS[1:3]:
        with actor(dsn, user) as c:
            assert c.execute("select count(*) from public.question_answers").fetchone() == (0,)
    save(USERS[0], 1, shared=True)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select content from public.question_answers").fetchone() == ("개인 답변",)
    save(USERS[1], 0, text="상대 답변", shared=True)
    save(USERS[0], 2, skipped=True)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select content from public.question_answers").fetchall() == [
            ("상대 답변",)
        ]
    with actor(dsn, USERS[0]) as c:
        assert c.execute(
            "select content,skipped from public.question_answers where author_id=auth.uid()"
        ).fetchone() == ("개인 답변", True)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        save(USERS[0], 1)
    with pytest.raises(psycopg.Error, match="invalid_answer"):
        save(USERS[0], 3, shared=True, skipped=True)
    with actor(dsn, USERS[1]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.question_answers set content='다른 사람 원문'")
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="question_not_found"):
        save(USERS[2], 0)
    with pytest.raises(psycopg.Error, match="invalid_question"):
        call(dsn, USERS[0], "create_question", uuid4(), "2026-10-19", " ", uuid4())


def test_timezone_self_write_couple_read_clear_retry_and_validation(database_url):
    dsn = database_url
    connect_pair(dsn)
    req = uuid4()
    saved = call(dsn, USERS[0], "save_timezone", "America/New_York", 0, req)
    assert call(dsn, USERS[0], "save_timezone", "America/New_York", 0, req) == saved
    call(dsn, USERS[1], "save_timezone", "Asia/Seoul", 0, uuid4())
    call(dsn, USERS[2], "save_timezone", "UTC", 0, uuid4())
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select count(*) from public.timezone_preferences").fetchone() == (2,)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select timezone from public.timezone_preferences").fetchall() == [
            ("UTC",)
        ]
    call(dsn, USERS[0], "save_timezone", None, 1, uuid4())
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_timezone", "UTC", 1, uuid4())
    for bad in ["invalid/timezone", "", "../../etc/passwd", "x" * 65]:
        with pytest.raises(psycopg.Error, match="invalid_timezone"):
            call(dsn, USERS[0], "save_timezone", bad, 2, uuid4())
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.timezone_preferences set timezone='UTC'")


def test_roulette_snapshot_draw_idempotency_conflict_archive_and_isolation(database_url):
    dsn = database_url
    connect_pair(dsn)
    wheel, req = uuid4(), uuid4()
    args = (wheel, "함께 고르기", Jsonb(["산책", "집에서 영화"]), False, 0, req)
    saved = call(dsn, USERS[0], "save_roulette", *args)
    assert call(dsn, USERS[0], "save_roulette", *args) == saved
    draw_id = uuid4()
    draw = call(dsn, USERS[0], "draw_roulette", wheel, 1, draw_id)
    assert draw[4][draw[5]] in ["산책", "집에서 영화"]
    assert call(dsn, USERS[0], "draw_roulette", wheel, 1, draw_id) == draw
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "draw_roulette", wheel, 1, draw_id)
    call(
        dsn,
        USERS[1],
        "save_roulette",
        wheel,
        "수정 후보",
        Jsonb(["카페", "독서"]),
        False,
        1,
        uuid4(),
    )
    assert call(dsn, USERS[0], "draw_roulette", wheel, 1, draw_id) == draw
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "draw_roulette", wheel, 1, uuid4())
    call(dsn, USERS[1], "draw_roulette", wheel, 2, uuid4())
    call(
        dsn,
        USERS[0],
        "save_roulette",
        wheel,
        "수정 후보",
        Jsonb(["카페", "독서"]),
        True,
        2,
        uuid4(),
    )
    with pytest.raises(psycopg.Error, match="roulette_archived"):
        call(dsn, USERS[0], "draw_roulette", wheel, 3, uuid4())
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select count(*) from public.roulette_draws").fetchone() == (2,)
        assert c.execute("select count(*) from public.appointments").fetchone() == (0,)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.roulette_draws").fetchone() == (0,)
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("delete from public.roulette_draws")
    for bad in [[], ["하나"], ["중복", " 중복 "], [None, "후보"], ["x" * 101, "후보"]]:
        with pytest.raises(psycopg.Error, match="invalid_roulette"):
            call(dsn, USERS[0], "save_roulette", uuid4(), "이름", Jsonb(bad), False, 0, uuid4())
