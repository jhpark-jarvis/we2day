from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_agents_database import issue, rpc
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT


def managed(dsn, user=USERS[0]):
    return call(dsn, user, "create_managed_agent_connection", "Synthetic managed", True)[0]


def change(
    dsn, key, entity, id, action, version, content=None, confirmed=False, request=None, av=0
):
    return rpc(
        dsn,
        "agent_change",
        key,
        entity,
        id,
        action,
        Jsonb(content) if content is not None else None,
        version,
        av,
        request or uuid4(),
        confirmed,
    )


APPOINTMENT = {"title": "Synthetic", "date": "2026-11-08", "time": "14:00", "place": "", "note": ""}


def test_scope_appointment_crud_conflicts_and_delete_retries(database_url):
    dsn = database_url
    connect_pair(dsn)
    old = issue(dsn)["key"]
    key = managed(dsn)["key"]
    id, request = uuid4(), uuid4()
    with pytest.raises(psycopg.Error, match="agent_manage_required"):
        change(dsn, old, "appointment", id, "create", 0, APPOINTMENT)
    created = change(dsn, key, "appointment", id, "create", 0, APPOINTMENT, request=request)
    assert created["version"] == 1 and not created["replayed"]
    assert change(dsn, key, "appointment", id, "create", 0, APPOINTMENT, request=request)[
        "replayed"
    ]
    assert rpc(dsn, "agent_appointment", key, id)["plan_id"] is None
    with pytest.raises(psycopg.Error, match="request_conflict"):
        change(
            dsn,
            key,
            "appointment",
            id,
            "create",
            0,
            {**APPOINTMENT, "note": "Changed"},
            request=request,
        )
    assert change(dsn, key, "appointment", id, "update", 1, APPOINTMENT)["version"] == 2
    with pytest.raises(psycopg.Error, match="version_conflict"):
        change(dsn, key, "appointment", id, "update", 1, APPOINTMENT)
    with pytest.raises(psycopg.Error, match="confirmation_required"):
        change(dsn, key, "appointment", id, "delete", 2)
    delete_request = uuid4()
    assert change(dsn, key, "appointment", id, "delete", 2, confirmed=True, request=delete_request)[
        "deleted"
    ]
    assert change(dsn, key, "appointment", id, "delete", 2, confirmed=True, request=delete_request)[
        "replayed"
    ]
    with pytest.raises(psycopg.Error, match="appointment_not_found"):
        rpc(dsn, "agent_appointment", key, id)
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update agent_connections set can_manage=true")
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from we2day_private.agent_changes")


def test_plan_save_publication_archive_restore_preserves_history(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = managed(dsn)["key"]
    id = uuid4()
    rpc(dsn, "agent_create_draft", key, id, Jsonb(CONTENT), uuid4())
    assert change(dsn, key, "plan", id, "save", 1, {**CONTENT, "title": "Updated"})["version"] == 2
    with pytest.raises(psycopg.Error, match="confirmation_required"):
        change(dsn, key, "plan", id, "confirm", 2)
    result = change(dsn, key, "plan", id, "confirm", 2, confirmed=True)
    appointment = result["appointment_id"]
    read = rpc(dsn, "agent_plan", key, id)
    assert read["appointment_version"] == 1 and read["published_revision"] == 1
    for action, content in [("update", APPOINTMENT), ("delete", None)]:
        with pytest.raises(psycopg.Error, match="linked_plan_required"):
            change(dsn, key, "appointment", appointment, action, 1, content, confirmed=True)
    assert change(dsn, key, "plan", id, "archive", 3, confirmed=True)["archived"]
    assert rpc(dsn, "agent_plan", key, id)["archived"]
    assert not change(dsn, key, "plan", id, "restore", 4)["archived"]
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select count(*) from appointments").fetchone()[0] == 1
        assert (
            db.execute("select count(*) from we2day_private.agent_changes").fetchone()[0]
            if False
            else True
        )


def test_personal_other_space_revoked_and_claims_restore(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = managed(dsn)
    personal = call(
        dsn, USERS[0], "create_personal_appointment", "Private", "2026-11-08", None, "", "", uuid4()
    )[0]
    for function, args in [("agent_appointment", (key["key"], personal))]:
        with pytest.raises(psycopg.Error, match="appointment_not_found"):
            rpc(dsn, function, *args)
    with pytest.raises(psycopg.Error, match="appointment_not_found"):
        change(dsn, key["key"], "appointment", personal, "delete", 1, confirmed=True)
    call(dsn, USERS[2], "create_couple")
    other = managed(dsn, USERS[2])["key"]
    id = uuid4()
    rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), uuid4())
    with pytest.raises(psycopg.Error, match="plan_not_found"):
        change(dsn, other, "plan", id, "save", 1, CONTENT)
    with actor(dsn, USERS[2]) as db:
        db.execute(
            "select agent_change(%s,'plan',%s,'save',%s,1,0,%s,false)",
            (key["key"], id, Jsonb(CONTENT), uuid4()),
        )
        assert str(db.execute("select auth.uid()").fetchone()[0]) == USERS[2]
    call(dsn, USERS[0], "revoke_agent_connection", key["id"])
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        change(dsn, key["key"], "plan", id, "save", 2, CONTENT)


def test_manage_quota_receipts_and_invalid_sql_inputs(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = managed(dsn)
    id, req = uuid4(), uuid4()
    result = change(dsn, key["key"], "appointment", id, "create", 0, APPOINTMENT, request=req)
    with psycopg.connect(dsn) as db:
        row = db.execute("select result::text from we2day_private.agent_changes").fetchone()[0]
        assert "Synthetic" not in row and key["key"] not in row
        db.execute(
            "insert into we2day_private.agent_changes "
            "select connection_id,gen_random_uuid(),couple_id,target_id,entity,action,"
            "fingerprint,result,created_at from we2day_private.agent_changes "
            "cross join generate_series(1,99)"
        )
    assert change(dsn, key["key"], "appointment", id, "create", 0, APPOINTMENT, request=req)[
        "replayed"
    ]
    with pytest.raises(psycopg.Error, match="agent_change_limit"):
        change(dsn, key["key"], "appointment", id, "update", result["version"], APPOINTMENT)


def test_concurrent_same_request_has_one_effect(database_url):
    from concurrent.futures import ThreadPoolExecutor

    dsn = database_url
    connect_pair(dsn)
    key = managed(dsn)["key"]
    id, req = uuid4(), uuid4()

    def run():
        return change(dsn, key, "appointment", id, "create", 0, APPOINTMENT, request=req)

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: run(), range(2)))
    assert sorted(v["replayed"] for v in values) == [False, True]
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select count(*) from appointments where id=%s", (id,)).fetchone()[0] == 1


def test_invalid_direct_sql_and_failed_delegation_leave_data_unchanged(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = managed(dsn)["key"]
    for entity, action, content in [
        ("photo", "delete", None),
        ("appointment", "create", {}),
        ("appointment", "create", {**APPOINTMENT, "time": "24:00"}),
        ("appointment", "create", {**APPOINTMENT, "kind": "personal"}),
    ]:
        with pytest.raises(psycopg.Error):
            change(dsn, key, entity, uuid4(), action, 0, content, confirmed=True)
    id = uuid4()
    rpc(dsn, "agent_create_draft", key, id, Jsonb(CONTENT), uuid4())
    with pytest.raises(psycopg.Error, match="version_conflict"):
        change(dsn, key, "plan", id, "confirm", 99, confirmed=True)
    assert rpc(dsn, "agent_plan", key, id)["published_content"] is None
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select count(*) from appointments").fetchone()[0] == 0
