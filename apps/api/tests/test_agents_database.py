from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT, change


def issue(dsn, user=USERS[0]):
    return call(dsn, user, "create_agent_connection", "Synthetic agent")[0]


def rpc(dsn, function, *args):
    with actor(dsn, None, "anon") as db:
        return db.execute(
            f"select public.{function}({','.join(['%s'] * len(args))})", args
        ).fetchone()[0]


def test_key_management_hash_secrecy_and_scope(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = issue(dsn)
    assert key["key"].startswith("w2d_agent_")
    with actor(dsn, USERS[0]) as db:
        assert (
            db.execute("select label from public.agent_connections").fetchone()[0] == key["label"]
        )
    for user in [USERS[0], USERS[1]]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), actor(dsn, user) as db:
            db.execute("select token_hash from public.agent_connections")
    with actor(dsn, USERS[1]) as db:
        assert db.execute("select id from public.agent_connections").fetchall() == []
    with pytest.raises(psycopg.Error, match="agent_connection_not_found"):
        call(dsn, USERS[1], "revoke_agent_connection", key["id"])
    with psycopg.connect(dsn) as db:
        digest = db.execute(
            "select encode(token_hash,'hex') from public.agent_connections"
        ).fetchone()[0]
    for token in [digest, "w2d_agent_" + digest, "w2d_agent_" + "0" * 64]:
        with pytest.raises(psycopg.Error, match="invalid_agent_key"):
            rpc(dsn, "agent_calendar", token, "2026-11-01", "2026-11-02", 0)
    id = uuid4()
    change(dsn, USERS[0], id, "save", 0, CONTENT)
    assert rpc(dsn, "agent_plan", key["key"], id)["content"]["title"] == CONTENT["title"]
    other_space = call(dsn, USERS[2], "create_couple")
    other_key = issue(dsn, USERS[2])
    assert other_space
    with pytest.raises(psycopg.Error, match="plan_not_found"):
        rpc(dsn, "agent_plan", other_key["key"], id)
    assert (
        rpc(dsn, "agent_calendar", other_key["key"], "2026-11-01", "2026-11-02", 0)["plans"] == []
    )
    assert call(dsn, USERS[0], "revoke_agent_connection", key["id"])[0]
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        rpc(dsn, "agent_plan", key["key"], id)


def test_draft_only_idempotency_and_human_confirmation(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = issue(dsn)
    id, request = uuid4(), uuid4()
    result = rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), request)
    assert result == {"id": str(id), "created": True}
    assert (
        rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), request)["created"] is False
    )
    with actor(dsn, USERS[1]) as db:
        assert db.execute("select count(*) from public.appointments").fetchone()[0] == 0
        assert db.execute("select published_content from public.date_plans").fetchone()[0] is None
    with pytest.raises(psycopg.Error, match="request_conflict"):
        rpc(
            dsn,
            "agent_create_draft",
            key["key"],
            id,
            Jsonb({**CONTENT, "title": "Changed"}),
            request,
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), actor(dsn, None, "anon") as db:
        db.execute("select public.change_date_plan(%s,'confirm',null,1,0,%s)", (id, uuid4()))
    change(dsn, USERS[1], id, "confirm", 1)
    assert (
        rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), request)["created"] is False
    )
    with actor(dsn, USERS[1]) as db:
        assert db.execute("select count(*) from public.appointments").fetchone()[0] == 1
    with pytest.raises(psycopg.Error, match="request_conflict"):
        rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), uuid4())


def test_expiry_membership_rate_limits_and_issuance_limits(database_url):
    dsn = database_url
    connect_pair(dsn)
    keys = [issue(dsn) for _ in range(5)]
    with pytest.raises(psycopg.Error, match="agent_connection_limit"):
        issue(dsn)
    for column, value in [("expires_at", "now()-interval '1 second'"), ("window_count", "60")]:
        with psycopg.connect(dsn) as db:
            db.execute(
                f"update public.agent_connections set {column}={value} where id=%s",
                (keys[0]["id"],),
            )
        expected = "invalid_agent_key" if column == "expires_at" else "agent_rate_limit"
        with pytest.raises(psycopg.Error, match=expected):
            rpc(dsn, "agent_calendar", keys[0]["key"], "2026-11-01", "2026-11-02", 0)
        with psycopg.connect(dsn) as db:
            db.execute(
                "update public.agent_connections set expires_at=now()+interval '1 day' where id=%s",
                (keys[0]["id"],),
            )
    with psycopg.connect(dsn) as db:
        db.execute("delete from public.couple_members where user_id=%s", (USERS[0],))
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        rpc(dsn, "agent_calendar", keys[1]["key"], "2026-11-01", "2026-11-02", 0)


def test_daily_draft_quota_preserves_retry_and_no_calendar_side_effect(database_url):
    dsn = database_url
    connect_pair(dsn)
    key = issue(dsn)
    first = None
    for _ in range(20):
        id, request = uuid4(), uuid4()
        first = first or (id, request)
        rpc(dsn, "agent_create_draft", key["key"], id, Jsonb(CONTENT), request)
    assert not rpc(dsn, "agent_create_draft", key["key"], first[0], Jsonb(CONTENT), first[1])[
        "created"
    ]
    with pytest.raises(psycopg.Error, match="agent_draft_limit"):
        rpc(dsn, "agent_create_draft", key["key"], uuid4(), Jsonb(CONTENT), uuid4())
    with actor(dsn, USERS[1]) as db:
        assert db.execute("select count(*) from public.date_plans").fetchone()[0] == 20
        assert db.execute("select count(*) from public.appointments").fetchone()[0] == 0
