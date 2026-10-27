import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def begin(dsn, cid, rid, lease, version=0, fingerprint="a" * 64, user=USERS[0]):
    return call(
        dsn, user, "begin_ai_planner_turn", cid, rid, version, "합성 질문", fingerprint, lease
    )[0]


def finish(dsn, cid, rid, lease, version=0):
    return call(
        dsn,
        USERS[0],
        "finish_ai_planner_turn",
        cid,
        rid,
        lease,
        version,
        "합성 질문",
        Jsonb({"reply": "합성 답변", "plan": None, "context": {"region": "가상동"}}),
        "test-v1",
    )[0]


def test_small_head_exact_old_replay_lease_expiry_and_private_access(database_url):
    dsn = database_url
    connect_pair(dsn)
    cid, rid, lease = uuid4(), uuid4(), uuid4()
    assert begin(dsn, cid, rid, lease)["context"] == {}
    with pytest.raises(psycopg.Error, match="ai_request_in_progress"):
        begin(dsn, cid, rid, uuid4())
    with pytest.raises(psycopg.Error, match="request_conflict"):
        begin(dsn, cid, rid, uuid4(), fingerprint="b" * 64)
    with pytest.raises(psycopg.Error, match="ai_conversation_not_found"):
        begin(dsn, cid, rid, uuid4(), user=USERS[1])
    assert finish(dsn, cid, rid, lease)["version"] == 1
    with psycopg.connect(dsn) as db:
        assert (
            db.execute("select count(*) from we2day_private.ai_request_leases").fetchone()[0] == 0
        )
    # Exact lookup outside the UI's last-50-turn page, with old API writes retained.
    for version in range(1, 52):
        call(
            dsn,
            USERS[0],
            "append_ai_conversation",
            cid,
            uuid4(),
            version,
            "합성",
            Jsonb(
                {
                    "reply": "other",
                    "context": {"region": "가상동"},
                    "plan": {"title": "이전 제안", "date": "2030-01-01"} if version == 1 else None,
                }
            ),
            "old-v1",
        )
    replay = begin(dsn, cid, rid, uuid4())["replay"]
    assert replay["version"] == 1 and replay["prompt_version"] == "test-v1"
    with pytest.raises(psycopg.Error, match="request_conflict"):
        begin(dsn, cid, rid, uuid4(), fingerprint="b" * 64)
    next_rid, next_lease = uuid4(), uuid4()
    head = begin(dsn, cid, next_rid, next_lease, 52)
    assert head["context"] == {"region": "가상동"} and "turns" not in head
    assert head["proposal"]["title"] == "이전 제안"
    full = call(dsn, USERS[0], "read_ai_conversations", cid)[0]
    assert len(json.dumps(head)) < len(json.dumps(full)) / 3
    with psycopg.connect(dsn) as db:
        db.execute(
            "update we2day_private.ai_request_leases set expires_at=now()-interval '1 second'"
        )
    new_lease = uuid4()
    begin(dsn, cid, next_rid, new_lease, 52)
    with pytest.raises(psycopg.Error, match="ai_lease_expired"):
        finish(dsn, cid, next_rid, next_lease, 52)
    assert not call(dsn, USERS[0], "release_ai_planner_turn", cid, next_rid, next_lease)[0]
    assert call(dsn, USERS[0], "release_ai_planner_turn", cid, next_rid, new_lease)[0]
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from we2day_private.ai_request_leases")
    with psycopg.connect(dsn) as db:
        for role in ["anon", "we2day_reminder_worker"]:
            assert not db.execute(
                "select has_function_privilege(%s,"
                "'public.begin_ai_planner_turn(uuid,uuid,integer,text,text,uuid)','EXECUTE')",
                (role,),
            ).fetchone()[0]


def test_concurrent_admission_has_only_one_owner_and_failed_lease_releases(database_url):
    dsn = database_url
    connect_pair(dsn)
    cid, rid = uuid4(), uuid4()
    leases = [uuid4(), uuid4()]

    def attempt(lease):
        try:
            begin(dsn, cid, rid, lease)
            return lease
        except psycopg.Error as error:
            assert error.diag.message_primary == "ai_request_in_progress"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, leases))
    winner = next(x for x in results if x)
    assert len([x for x in results if x]) == 1
    assert call(dsn, USERS[0], "release_ai_planner_turn", cid, rid, winner)[0]
    begin(dsn, cid, rid, uuid4())
