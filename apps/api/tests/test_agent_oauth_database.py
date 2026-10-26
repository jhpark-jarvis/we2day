import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_agents_database import rpc
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401

CLIENT = "https://chatgpt.com/oauth/client.json"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
RESOURCE = "https://fixture.example/api/agent/mcp"
VERIFIER = "a" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


def approve(dsn):
    return call(dsn, USERS[0], "approve_agent_oauth", CLIENT, CALLBACK, RESOURCE, CHALLENGE)[0]


def exchange(dsn, code, verifier=VERIFIER, resource=RESOURCE):
    return rpc(dsn, "exchange_agent_oauth", code, CLIENT, CALLBACK, resource, verifier)


def test_oauth_grant_hash_pkce_replay_resource_and_revocation(database_url):
    dsn = database_url
    connect_pair(dsn)
    code = approve(dsn)
    for verifier, resource in [
        ("b" * 64, RESOURCE),
        (VERIFIER, "https://wrong.example/api/agent/mcp"),
    ]:
        with pytest.raises(psycopg.Error, match="invalid_grant"):
            exchange(dsn, code, verifier, resource)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), actor(dsn, USERS[0]) as db:
        db.execute("select * from we2day_private.agent_oauth_codes")
    result = exchange(dsn, code)
    key = result["access_token"]
    assert key.startswith("w2d_agent_") and 365 * 86400 <= result["expires_in"] <= 366 * 86400
    with pytest.raises(psycopg.Error, match="invalid_grant"):
        exchange(dsn, code)
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        rpc(dsn, "agent_calendar", key, "2026-10-26", "2026-11-01", 0)
    args = Jsonb({"p_start": "2026-10-26", "p_end": "2026-11-01", "p_offset": 0})
    assert rpc(dsn, "agent_oauth_dispatch", key, RESOURCE, "agent_calendar", args)["plans"] == []
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        rpc(dsn, "agent_oauth_dispatch", key, RESOURCE + "/other", "agent_calendar", args)
    with psycopg.connect(dsn) as db:
        id, expiry = db.execute(
            "select id,expires_at=created_at+interval '1 year' from public.agent_connections"
        ).fetchone()
        assert expiry
        assert (
            db.execute("select code_hash from we2day_private.agent_oauth_codes").fetchone()[0]
            != code.encode()
        )
    call(dsn, USERS[0], "revoke_agent_connection", id)
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        rpc(dsn, "agent_oauth_dispatch", key, RESOURCE, "agent_calendar", args)


def test_oauth_one_exchange_under_race_and_expiry(database_url):
    dsn = database_url
    connect_pair(dsn)
    code = approve(dsn)

    def attempt(_):
        try:
            exchange(dsn, code)
            return True
        except psycopg.Error:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, range(2))) == 1
    code = approve(dsn)
    with psycopg.connect(dsn) as db:
        db.execute(
            "update we2day_private.agent_oauth_codes set expires_at=now()-interval '1 second'"
        )
    with pytest.raises(psycopg.Error, match="invalid_grant"):
        exchange(dsn, code)
