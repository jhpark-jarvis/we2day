from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_shared_checks_retry_restore_conflict_and_permissions(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    item = {"id": str(uuid4()), "title": "물", "quantity": "두 병", "done": False}
    args = (id, "산책 준비", "함께 챙겨요", Jsonb([item]), False, 0, request)
    saved = call(dsn, USERS[0], "save_checklist", *args)
    assert call(dsn, USERS[0], "save_checklist", *args) == saved
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select items from public.shared_checklists").fetchone() == ([item],)
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.shared_checklists").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "save_checklist", *args)
    checked = {**item, "done": True}
    call(dsn, USERS[1], "save_checklist", id, "산책 준비", "", Jsonb([checked]), True, 1, uuid4())
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_checklist", *(*args[:-1], uuid4()))
    call(dsn, USERS[0], "save_checklist", id, "산책 준비", "", Jsonb([item]), False, 2, uuid4())
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select items,archived from public.shared_checklists").fetchone() == (
            [item],
            False,
        )
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
        assert c.execute("select count(*) from public.appointments").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="checklist_items_retained"):
        call(dsn, USERS[0], "save_checklist", id, "산책 준비", "", Jsonb([]), False, 3, uuid4())
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="checklist_not_found"):
        call(dsn, USERS[2], "save_checklist", *args)
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("delete from public.shared_checklists")
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.shared_checklists set archived=true")


def test_checklist_database_shape_unicode_and_item_boundaries(database_url):
    dsn = database_url
    connect_pair(dsn)
    item = {"id": str(uuid4()), "title": "준" * 100, "quantity": "비" * 100, "done": False}
    invalid = [
        None,
        {},
        [None],
        [{**item, "done": "false"}],
        [{**item, "id": "bad"}],
        [{**item, "title": " "}],
        [{**item, "quantity": "a" * 101}],
        [{**item, "extra": "x"}],
        [item, {**item, "id": item["id"].upper()}],
        [{**item, "id": str(uuid4())} for _ in range(51)],
    ]
    for items in invalid:
        with pytest.raises(psycopg.Error, match="invalid_checklist"):
            call(
                dsn,
                USERS[0],
                "save_checklist",
                uuid4(),
                "준비",
                "",
                Jsonb(items),
                False,
                0,
                uuid4(),
            )
    items = [{**item, "id": str(uuid4())} for _ in range(50)]
    call(
        dsn,
        USERS[0],
        "save_checklist",
        uuid4(),
        "제" * 100,
        "메" * 1000,
        Jsonb(items),
        False,
        0,
        uuid4(),
    )
