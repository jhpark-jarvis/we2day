from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401


def test_private_history_replay_cas_and_pagination(database_url):
    dsn = database_url
    connect_pair(dsn)
    cid, rid = uuid4(), uuid4()
    result = {"reply": "합성 응답", "plan": None}
    assert call(dsn, USERS[0], "read_ai_conversations")[0] == []
    assert call(dsn, USERS[0], "read_ai_conversations", cid)[0] is None
    args = (cid, rid, 0, "합성 질문", Jsonb(result), "test-v1")
    assert call(dsn, USERS[0], "append_ai_conversation", *args)[0]["version"] == 1
    assert call(dsn, USERS[0], "append_ai_conversation", *args)[0]["version"] == 1
    assert call(dsn, USERS[1], "read_ai_conversations")[0] == []
    for function, values in [("read_ai_conversations", (cid,)), ("append_ai_conversation", args)]:
        with pytest.raises(psycopg.Error, match="ai_conversation_not_found"):
            call(dsn, USERS[1], function, *values)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(
            dsn, USERS[0], "append_ai_conversation", cid, uuid4(), 0, "새 질문", Jsonb(result), "v1"
        )
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[0], "append_ai_conversation", cid, rid, 0, "다른 질문", Jsonb(result), "v1")
    for version in range(1, 52):
        call(
            dsn,
            USERS[0],
            "append_ai_conversation",
            cid,
            uuid4(),
            version,
            "합성",
            Jsonb(result),
            "v1",
        )
    detail = call(dsn, USERS[0], "read_ai_conversations", cid)[0]
    assert detail["version"] == 52 and len(detail["turns"]) == 50
    assert detail["turns"][0]["version"] == 3
    older = call(dsn, USERS[0], "read_ai_conversations", cid, 3)[0]
    assert [t["version"] for t in older["turns"]] == [1, 2]
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from we2day_private.ai_conversations")
    with actor(dsn, None, "anon") as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.read_ai_conversations()")
    with psycopg.connect(dsn) as db:
        for role in ["anon", "we2day_reminder_worker"]:
            assert not db.execute(
                "select has_function_privilege(%s,"
                "'public.read_ai_conversations(uuid,integer)','EXECUTE')",
                (role,),
            ).fetchone()[0]
