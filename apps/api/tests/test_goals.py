from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_shared_goal_manual_completion_retry_restore_and_isolation(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    step = {"id": str(uuid4()), "title": "첫 단계", "done": False}
    args = (id, "함께 하는 목표", "2020-01-01", Jsonb([step]), False, False, 0, request)
    saved = call(dsn, USERS[0], "save_goal", *args)
    assert call(dsn, USERS[0], "save_goal", *args) == saved
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select completed,steps from public.shared_goals").fetchone() == (
            False,
            [step],
        )
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.shared_goals").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "save_goal", *args)
    checked = {**step, "done": True}
    call(
        dsn,
        USERS[1],
        "save_goal",
        id,
        "함께 하는 목표",
        None,
        Jsonb([checked]),
        False,
        False,
        1,
        uuid4(),
    )
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select completed,target_date from public.shared_goals").fetchone() == (
            False,
            None,
        )
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_goal", *(*args[:-1], uuid4()))
    call(
        dsn,
        USERS[0],
        "save_goal",
        id,
        "함께 하는 목표",
        None,
        Jsonb([step]),
        True,
        True,
        2,
        uuid4(),
    )
    call(
        dsn,
        USERS[1],
        "save_goal",
        id,
        "함께 하는 목표",
        None,
        Jsonb([step]),
        False,
        False,
        3,
        uuid4(),
    )
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select completed,archived,steps from public.shared_goals").fetchone() == (
            False,
            False,
            [step],
        )
        assert c.execute("select count(*) from public.appointments").fetchone() == (0,)
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="goal_steps_retained"):
        call(dsn, USERS[0], "save_goal", id, "목표", None, Jsonb([]), False, False, 4, uuid4())
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="goal_not_found"):
        call(dsn, USERS[2], "save_goal", *args)
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.shared_goals set completed=true")
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("delete from public.shared_goals")


def test_goal_boundaries_zero_steps_and_invalid_shape(database_url):
    dsn = database_url
    connect_pair(dsn)
    step = {"id": str(uuid4()), "title": "단" * 100, "done": False}
    invalid = [
        None,
        {},
        [None],
        [{**step, "done": "false"}],
        [{**step, "id": "bad"}],
        [{**step, "title": " "}],
        [{**step, "extra": "x"}],
        [step, {**step, "id": step["id"].upper()}],
        [{**step, "id": str(uuid4())} for _ in range(51)],
    ]
    for steps in invalid:
        with pytest.raises(psycopg.Error, match="invalid_goal"):
            call(
                dsn,
                USERS[0],
                "save_goal",
                uuid4(),
                "목표",
                None,
                Jsonb(steps),
                False,
                False,
                0,
                uuid4(),
            )
    for target in ["1999-12-31", "2101-01-01", "infinity", "-infinity"]:
        with pytest.raises(psycopg.Error, match="invalid_goal"):
            call(
                dsn,
                USERS[0],
                "save_goal",
                uuid4(),
                "목표",
                target,
                Jsonb([]),
                False,
                False,
                0,
                uuid4(),
            )
    call(
        dsn,
        USERS[0],
        "save_goal",
        uuid4(),
        "단계 미정도 직접 달성 선택 가능",
        None,
        Jsonb([]),
        True,
        False,
        0,
        uuid4(),
    )
    call(
        dsn,
        USERS[0],
        "save_goal",
        uuid4(),
        "목" * 100,
        "2100-12-31",
        Jsonb([{**step, "id": str(uuid4())} for _ in range(50)]),
        False,
        False,
        0,
        uuid4(),
    )
