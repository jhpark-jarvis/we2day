import json
from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import ROW, upstream  # noqa: F401
from test_database import USERS, actor, call, reset_database  # noqa: F401
from test_reports import confirmed, save

from we2day_api.snapshot_format import EXPORT_FIELDS, canonical, encode_snapshot, inspect_snapshot


def snapshot(dsn, user, kind, private=False, start="2026-01-01", end="2026-12-31"):
    return call(dsn, user, "export_record_snapshot", kind, start, end, private)[0]


def test_snapshot_all_kinds_projection_privacy_withdrawal_and_no_mutation(database_url):
    dsn = database_url
    plan = confirmed(dsn)
    save(dsn, USERS[0], plan, 0)
    q = uuid4()
    call(dsn, USERS[0], "create_question", q, "2026-10-01", "synthetic", uuid4())
    call(dsn, USERS[0], "save_question_answer", q, "private answer", False, False, 0, uuid4())
    for user in USERS[:2]:
        for kind, fields in EXPORT_FIELDS.items():
            rows = snapshot(dsn, user, kind)
            assert all(set(row) == set(fields) for row in rows)
            assert not any(
                key in json.dumps(rows) for key in ["fingerprint", "request_id", "couple_id"]
            )
    assert snapshot(dsn, USERS[0], "date_reports") == []
    assert len(snapshot(dsn, USERS[0], "date_reports", True)) == 1
    assert snapshot(dsn, USERS[1], "date_reports", True) == []
    assert len(snapshot(dsn, USERS[0], "question_answers", True)) == 1
    assert snapshot(dsn, USERS[1], "question_answers", True) == []
    save(dsn, USERS[0], plan, 1, shared=True)
    assert len(snapshot(dsn, USERS[1], "date_reports")) == 1
    save(dsn, USERS[0], plan, 2)
    assert snapshot(dsn, USERS[1], "date_reports") == []
    call(dsn, USERS[2], "create_couple")
    for kind in EXPORT_FIELDS:
        assert snapshot(dsn, USERS[2], kind, True) == []
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    for user, message in [(None, "authentication_required"), (USERS[3], "couple_required")]:
        with pytest.raises(psycopg.Error, match=message):
            snapshot(dsn, user, "appointments")
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.export_record_snapshot('appointments','2026-01-01','2026-12-31')")


def test_snapshot_limits_invalid_inputs_and_complete_failure(database_url):
    dsn = database_url
    confirmed(dsn)
    for kwargs in [
        {"kind": "auth.users"},
        {"kind": "appointments", "private": None},
        {"kind": "appointments", "start": "2025-01-01"},
    ]:
        with pytest.raises(psycopg.Error, match="invalid_record_export"):
            snapshot(dsn, USERS[0], **kwargs)
    with psycopg.connect(dsn) as c:
        c.execute("""insert into public.appointments(couple_id,title,date,
    created_by,updated_by,request_id,creation_fingerprint)
   select couple_id,'synthetic limit','2026-02-01',
    created_by,updated_by,gen_random_uuid(),'synthetic'
   from public.appointments cross join generate_series(1,500)""")
    with pytest.raises(psycopg.Error, match="record_export_too_large"):
        snapshot(dsn, USERS[0], "appointments")
    assert snapshot(dsn, USERS[0], "appointments", start="2026-03-01", end="2026-03-01") == []


def test_snapshot_api_bounds_minimal_export_and_offline_damage_check(upstream):  # noqa: F811
    client, calls, replies = upstream
    body = {"kind": "appointments", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    for changes in [
        {"kind": "users"},
        {"include_private": "true"},
        {"end_date": "2027-01-02"},
        {"offset": 1},
        {"offset": False},
    ]:
        assert client.post("/records/export", json=body | changes).status_code == 422
    assert (
        client.post(
            "/records/export", content="x" * 4097, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert calls == []
    replies.append((200, [ROW]))
    response = client.post("/records/export", json=body)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert "fingerprint" not in response.text and "couple_id" not in response.text
    assert inspect_snapshot(response.content)["count"] == 1
    original = json.loads(response.content)
    original["payload"]["records"][0]["title"] = "changed"
    with pytest.raises(ValueError, match="checksum_mismatch"):
        inspect_snapshot(canonical(original))
    for invalid in [b'{"format":1,"format":2}', b"[]", b"NaN", b"{}", b"\xff"]:
        with pytest.raises(ValueError):
            inspect_snapshot(invalid)
    with pytest.raises(ValueError, match="snapshot_too_large"):
        encode_snapshot("appointments", [ROW] * 501, "2026-01-01", "2026-12-31", False)
