from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT, change

REPORT = {
    "summary": "즐거운 산책",
    "visits": ["직접 확인한 공원"],
    "actual_cost": None,
    "highlights": "대화",
    "next_time": "물 준비",
    "revisit": True,
}


def save(dsn, user, plan, version, content=None, shared=False, request=None):
    return call(
        dsn,
        user,
        "save_date_report",
        plan,
        Jsonb(content or REPORT),
        shared,
        version,
        request or uuid4(),
    )


def confirmed(dsn):
    connect_pair(dsn)
    plan = uuid4()
    change(dsn, USERS[0], plan, "save", 0, {**CONTENT, "date": "2026-01-01"})
    change(dsn, USERS[0], plan, "confirm", 1)
    return plan


def test_report_private_shared_withdraw_owner_and_snapshot(database_url):
    dsn = database_url
    plan = confirmed(dsn)
    request = uuid4()
    saved = save(dsn, USERS[0], plan, 0, request=request)
    assert save(dsn, USERS[0], plan, 0, request=request) == saved
    for user in USERS[1:3]:
        with actor(dsn, user) as c:
            assert c.execute("select count(*) from public.date_reports").fetchone() == (0,)
    save(dsn, USERS[0], plan, 1, shared=True)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select content->>'summary' from public.date_reports").fetchone() == (
            REPORT["summary"],
        )
    save(dsn, USERS[1], plan, 0, content={**REPORT, "summary": "상대의 원문"}, shared=True)
    save(dsn, USERS[0], plan, 2, shared=False)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select content->>'summary' from public.date_reports").fetchall() == [
            ("상대의 원문",)
        ]
    change(dsn, USERS[0], plan, "save", 2, {**CONTENT, "title": "다른 계획", "date": "2026-01-01"})
    change(dsn, USERS[0], plan, "confirm", 3, av=1)
    save(dsn, USERS[0], plan, 3, shared=True)
    with actor(dsn, USERS[0]) as c:
        assert c.execute(
            "select plan_snapshot->>'title',content->'actual_cost' "
            "from public.date_reports where author_id=auth.uid()"
        ).fetchone() == (CONTENT["title"], None)
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        save(dsn, USERS[0], plan, 1)
    with actor(dsn, USERS[1]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.date_reports set shared=true")
    # A different couple cannot use a guessed plan ID.
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="plan_not_found"):
        save(dsn, USERS[2], plan, 0)


def test_report_unconfirmed_future_and_direct_json_validation(database_url):
    dsn = database_url
    connect_pair(dsn)
    plan = uuid4()
    change(dsn, USERS[0], plan, "save", 0, {**CONTENT, "date": "2100-12-31"})
    with pytest.raises(psycopg.Error, match="report_not_ready"):
        save(dsn, USERS[0], plan, 0)
    change(dsn, USERS[0], plan, "confirm", 1)
    with pytest.raises(psycopg.Error, match="report_not_ready"):
        save(dsn, USERS[0], plan, 0)
    for changes in [
        {"summary": None},
        {"summary": " "},
        {"visits": "a"},
        {"visits": [None]},
        {"actual_cost": "10"},
        {"actual_cost": -1},
        {"revisit": "yes"},
        {"extra": True},
    ]:
        with pytest.raises(psycopg.Error, match="invalid_report"):
            save(dsn, USERS[0], plan, 0, {**deepcopy(REPORT), **changes})


def test_report_combined_multibyte_limits(database_url):
    plan = confirmed(database_url)
    content = {
        **REPORT,
        "summary": "🌷" * 2000,
        "highlights": "🌷" * 2000,
        "next_time": "🌷" * 2000,
        "visits": ["🌷" * 200] * 20,
    }
    saved = save(database_url, USERS[0], plan, 0, content)
    assert saved is not None
