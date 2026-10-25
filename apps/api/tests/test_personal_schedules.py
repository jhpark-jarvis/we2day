import json
from uuid import UUID, uuid4

import psycopg
import pytest
from test_agents_database import issue, rpc
from test_calendar_api import BODY, ROW, upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401

from we2day_api.snapshot_format import canonical, encode_snapshot, inspect_snapshot


def create(dsn, user=USERS[0], request=None, personal=True):
    return call(
        dsn,
        user,
        "create_personal_appointment" if personal else "create_appointment",
        "개인 준비",
        "2026-10-24",
        None,
        "",
        "메모",
        request or uuid4(),
    )


def test_personal_owner_shared_read_and_direct_rpc_boundaries(database_url):
    dsn = database_url
    connect_pair(dsn)
    request = uuid4()
    row = create(dsn, request=request)
    assert create(dsn, request=request) == row
    id = row[0]
    with actor(dsn, USERS[1]) as c:
        assert c.execute(
            "select kind,created_by,place from appointments where id=%s", (id,)
        ).fetchone() == ("personal", UUID(USERS[0]), "")
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select * from appointments").fetchall() == []
    for function, args in [
        ("update_appointment", (id, 1, "변경", "2026-10-24", None, "", "")),
        ("delete_personal_appointment", (id, 1)),
    ]:
        with pytest.raises(psycopg.Error, match="appointment_owner_required"):
            call(dsn, USERS[1], function, *args)
    with pytest.raises(psycopg.Error, match="invalid_appointment"):
        call(
            dsn,
            USERS[0],
            "create_personal_appointment",
            "개인",
            "2026-10-24",
            None,
            "장소",
            "",
            uuid4(),
        )
    with pytest.raises(psycopg.Error, match="request_conflict"):
        create(dsn, request=request, personal=False)
    changed = call(
        dsn, USERS[0], "update_appointment", id, 1, "개인 수정", "2026-10-25", None, "", "수정 메모"
    )
    assert changed[1:3] == row[1:2] + ("개인 수정",)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "delete_personal_appointment", id, 1)
    with pytest.raises(psycopg.Error, match="invalid_appointment"):
        call(dsn, USERS[0], "update_appointment", id, 2, "개인", "2026-10-25", None, "장소", "")
    call(dsn, USERS[0], "delete_personal_appointment", id, 2)
    shared = create(dsn, personal=False)
    call(
        dsn,
        USERS[1],
        "update_appointment",
        shared[0],
        1,
        "공동 수정",
        "2026-10-24",
        None,
        "",
        "메모",
    )
    with pytest.raises(psycopg.Error, match="personal_appointment_required"):
        call(dsn, USERS[0], "delete_personal_appointment", shared[0], 2)
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select delete_personal_appointment(%s,1)", (shared[0],))
    with actor(dsn, USERS[0]) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update appointments set kind='shared'")


def test_next_shared_appointment_excludes_personal(database_url):
    dsn = database_url
    connect_pair(dsn)
    personal = call(
        dsn,
        USERS[0],
        "create_personal_appointment",
        "개인 먼저",
        "2099-01-01",
        None,
        "",
        "",
        uuid4(),
    )
    shared = call(
        dsn, USERS[0], "create_appointment", "공동 약속", "2099-01-02", None, "", "", uuid4()
    )
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select id from get_next_appointment()").fetchone() == (shared[0],)
        assert c.execute("select count(*) from appointments").fetchone() == (2,)
    assert personal[0] != shared[0]
    key = issue(dsn)
    result = rpc(dsn, "agent_calendar", key["key"], "2099-01-01", "2099-01-02", 0)
    assert [item["id"] for item in result["appointments"]] == [str(shared[0])]
    assert "개인 먼저" not in json.dumps(result, ensure_ascii=False)


def test_personal_api_dispatch_and_projections(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.extend(
        [
            (200, [{**ROW, "kind": "personal"}]),
            (403, {"code": "PT403", "message": "appointment_owner_required"}),
            (200, {"deleted": True}),
        ]
    )
    saved = client.post(
        "/appointments", json={**BODY, "place": "", "kind": "personal", "request_id": str(uuid4())}
    )
    assert saved.status_code == 201 and saved.json()["kind"] == "personal"
    assert calls[-1].url.path.endswith("create_personal_appointment")
    assert "p_kind" not in json.loads(calls[-1].content)
    denied = client.patch(f"/appointments/{ROW['id']}", json={**BODY, "expected_version": 1})
    assert denied.status_code == 403 and denied.json()["detail"] == "appointment_owner_required"
    result = client.request("DELETE", f"/appointments/{ROW['id']}", json={"expected_version": 1})
    assert result.status_code == 204 and "no-store" in result.headers["cache-control"]
    before = len(calls)
    assert (
        client.post(
            "/appointments",
            json={**BODY, "place": "금지", "kind": "personal", "request_id": str(uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/appointments/{ROW['id']}", json={**BODY, "kind": "personal", "expected_version": 1}
        ).status_code
        == 422
    )
    assert len(calls) == before


def test_personal_export_classification_and_legacy_copies(database_url):
    import hashlib

    connect_pair(database_url)
    create(database_url)
    rows = call(
        database_url,
        USERS[1],
        "export_record_snapshot",
        "appointments",
        "2026-10-01",
        "2026-10-31",
        False,
    )[0]
    assert rows[0]["kind"] == "personal"
    content = encode_snapshot("appointments", rows, "2026-10-01", "2026-10-31", False)
    assert inspect_snapshot(content)["count"] == 1
    old = json.loads(content)
    del old["payload"]["records"][0]["kind"]
    old["sha256"] = hashlib.sha256(canonical(old["payload"])).hexdigest()
    assert inspect_snapshot(canonical(old))["count"] == 1
