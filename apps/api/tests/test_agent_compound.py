import copy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_agent_management import change, managed
from test_agents_database import issue, rpc
from test_database import USERS, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT


def compound_content():
    content = copy.deepcopy(CONTENT)
    content["activities"] = [
        {
            "title": "Synthetic library",
            "time": "14:00",
            "place": "Synthetic A",
            "cost": None,
            "note": "Keep A",
        },
        {
            "title": "Synthetic cafe",
            "time": "16:00",
            "place": "Synthetic B",
            "cost": 20000,
            "note": "Keep B",
        },
    ]
    return content


def test_compound_agent_edit_is_atomic_replayable_and_cannot_publish_implicitly(database_url):
    dsn = database_url
    connect_pair(dsn)
    key, identity, content = managed(dsn)["key"], uuid4(), compound_content()
    rpc(dsn, "agent_create_draft", key, identity, Jsonb(content), uuid4())
    changed = copy.deepcopy(content)
    changed["title"], changed["budget"] = "Synthetic changed", 60000
    changed["activities"].reverse()
    changed["activities"][0]["time"] = "16:30"
    request = uuid4()
    saved = change(dsn, key, "plan", identity, "save", 1, changed, request=request)
    assert saved["version"] == 2
    assert change(dsn, key, "plan", identity, "save", 1, changed, request=request)["replayed"]
    state = rpc(dsn, "agent_plan", key, identity)
    assert state["content"]["activities"][0]["note"] == "Keep B"
    assert state["content"]["activities"][1]["time"] == "14:00"
    assert state["published_revision"] == 0 and state["appointment_id"] is None
    with pytest.raises(psycopg.Error, match="request_conflict"):
        change(dsn, key, "plan", identity, "save", 1, content, request=request)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        change(dsn, key, "plan", identity, "save", 1, content)
    with pytest.raises(psycopg.Error, match="confirmation_required"):
        change(dsn, key, "plan", identity, "confirm", 2)
    assert rpc(dsn, "agent_plan", key, identity) == state


def test_concurrent_compound_agent_edits_have_one_winner(database_url):
    dsn = database_url
    connect_pair(dsn)
    key, identity, original = managed(dsn)["key"], uuid4(), compound_content()
    rpc(dsn, "agent_create_draft", key, identity, Jsonb(original), uuid4())
    variants = [copy.deepcopy(original), copy.deepcopy(original)]
    variants[0]["title"], variants[0]["activities"][0]["time"] = "Option A", "14:30"
    variants[1]["title"], variants[1]["activities"][1]["time"] = "Option B", "17:00"

    def save(content):
        try:
            change(dsn, key, "plan", identity, "save", 1, content)
            return content
        except psycopg.Error as error:
            assert "version_conflict" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, variants))
    winner = next(r for r in results if r)
    assert sum(r is not None for r in results) == 1
    state = rpc(dsn, "agent_plan", key, identity)
    assert state["version"] == 2 and state["content"]["title"] == winner["title"]
    assert [a["time"] for a in state["content"]["activities"]] == [
        a["time"] for a in winner["activities"]
    ]


def test_readonly_revoked_and_personal_scope_stay_excluded_for_compound_edits(database_url):
    dsn = database_url
    connect_pair(dsn)
    key, identity, content = managed(dsn), uuid4(), compound_content()
    rpc(dsn, "agent_create_draft", key["key"], identity, Jsonb(content), uuid4())
    readonly = issue(dsn)["key"]
    with pytest.raises(psycopg.Error, match="agent_manage_required"):
        change(dsn, readonly, "plan", identity, "save", 1, content)
    personal = call(
        dsn,
        USERS[0],
        "create_personal_appointment",
        "Synthetic private",
        "2030-01-05",
        None,
        "",
        "",
        uuid4(),
    )[0]
    with pytest.raises(psycopg.Error, match="appointment_not_found"):
        change(dsn, key["key"], "appointment", personal, "delete", 1, confirmed=True)
    call(dsn, USERS[0], "revoke_agent_connection", key["id"])
    with pytest.raises(psycopg.Error, match="invalid_agent_key"):
        change(dsn, key["key"], "plan", identity, "save", 1, content)
