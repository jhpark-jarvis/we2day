from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_ai_budget_permissions_limit_and_race(database_url):
    dsn = database_url
    with psycopg.connect(dsn) as db:
        db.execute("truncate we2day_private.ai_planner_budget")
    with pytest.raises(psycopg.Error, match="couple_required"):
        call(dsn, USERS[0], "reserve_ai_planner_request")
    connect_pair(dsn)
    assert call(dsn, USERS[0], "reserve_ai_planner_request") == (True,)
    assert call(dsn, USERS[1], "reserve_ai_planner_request") == (False,)
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from we2day_private.ai_planner_budget")
    with actor(dsn, None, "anon") as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.reserve_ai_planner_request()")
    with psycopg.connect(dsn) as db:
        db.execute(
            "update we2day_private.ai_planner_budget set requests=49, "
            "last_request=now()-interval '1 minute'"
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda user: call(dsn, user, "reserve_ai_planner_request")[0], USERS[:2])
        )
    assert sum(results) == 1
    with psycopg.connect(dsn) as db:
        assert db.execute("select requests from we2day_private.ai_planner_budget").fetchone() == (
            50,
        )
        db.execute(
            "update we2day_private.ai_planner_budget set last_request=now()-interval '1 minute'"
        )
    assert call(dsn, USERS[0], "reserve_ai_planner_request") == (False,)
