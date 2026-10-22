import json
from datetime import date, timedelta
from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_reports import REPORT, confirmed, save
from test_routes_plans import CONTENT, change


def search(
    dsn, user, kind, query="", archived=False, offset=0, start="2026-01-01", end="2026-12-31"
):
    with actor(dsn, user) as c:
        return c.execute(
            "select * from public.search_records(%s,%s,%s,%s,%s,%s)",
            (kind, start, end, query, archived, offset),
        ).fetchall()


def test_search_preserves_report_visibility_withdrawal_and_snapshot(database_url):
    dsn = database_url
    plan = confirmed(dsn)
    save(dsn, USERS[0], plan, 0, content={**REPORT, "summary": "literal %_ private"})
    assert len(search(dsn, USERS[0], "report", "%_")) == 1
    assert search(dsn, USERS[1], "report") == []
    save(dsn, USERS[0], plan, 1, content={**REPORT, "summary": "literal %_ shared"}, shared=True)
    assert search(dsn, USERS[1], "report", "%_")[0][-1] == "partner_shared"
    save(dsn, USERS[0], plan, 2, shared=False)
    assert search(dsn, USERS[1], "report") == []
    change(
        dsn, USERS[0], plan, "save", 2, {**CONTENT, "title": "changed draft", "date": "2026-02-02"}
    )
    assert search(dsn, USERS[0], "plan", "changed draft")[0][4] == "changed"
    assert search(dsn, USERS[0], "report")[0][1] == date(2026, 1, 1)
    change(dsn, USERS[0], plan, "archive", 3)
    assert search(dsn, USERS[0], "plan") == []
    assert search(dsn, USERS[1], "plan", archived=True)[0][4] == "archived"
    call(dsn, USERS[2], "create_couple")
    for kind in ["report", "plan", "appointment", "wish"]:
        assert search(dsn, USERS[2], kind) == []
    with pytest.raises(psycopg.Error, match="authentication_required"):
        search(dsn, None, "report")
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from public.search_records('report','2026-01-01','2026-01-01','')")


def test_search_literal_pagination_dates_and_validation(database_url):
    dsn = database_url
    connect_pair(dsn)
    for index in range(52):
        call(
            dsn,
            USERS[0],
            "create_appointment",
            f"literal %_ {index}",
            "2026-02-02",
            None,
            "park",
            "note",
            uuid4(),
        )
    first = search(dsn, USERS[1], "appointment", "%_")
    second = search(dsn, USERS[1], "appointment", "%_", offset=50)
    assert len(first) == 51 and len(second) == 2
    assert len({row[0] for row in first[:50] + second}) == 52
    assert search(dsn, USERS[1], "appointment", "%wrong") == []
    wish = uuid4()
    call(dsn, USERS[0], "save_wish", wish, "wish literal", "place", "note", False, True, 0, uuid4())
    assert search(dsn, USERS[1], "wish") == []
    assert search(dsn, USERS[1], "wish", archived=True)[0][4] == "archived"
    for changes in [
        {"kind": "unknown"},
        {"query": "x" * 101},
        {"query": "x\n"},
        {"offset": -1},
        {"start": "2025-01-01"},
        {"end": "2025-01-01"},
        {"archived": None},
    ]:
        with pytest.raises(psycopg.Error, match="invalid_record_search"):
            search(dsn, USERS[0], **({"kind": "appointment"} | changes))


def test_next_appointment_korean_clock_order_isolation_and_no_writes(database_url):
    dsn = database_url
    connect_pair(dsn)
    with psycopg.connect(dsn) as c:
        now = c.execute("select statement_timestamp() at time zone 'Asia/Seoul'").fetchone()[0]
    today = now.date()
    future = today + timedelta(days=1)
    call(
        dsn,
        USERS[0],
        "create_appointment",
        "past",
        str(today - timedelta(days=1)),
        None,
        "",
        "",
        uuid4(),
    )
    later = call(
        dsn, USERS[0], "create_appointment", "future", str(future), "12:00", "public", "", uuid4()
    )[0]
    assert call(dsn, USERS[1], "get_next_appointment")[0] == later
    all_day = call(
        dsn, USERS[0], "create_appointment", "unknown time", str(today), None, "", "", uuid4()
    )[0]
    assert call(dsn, USERS[1], "get_next_appointment")[0] == all_day
    if now.hour < 23:
        timed = call(
            dsn,
            USERS[0],
            "create_appointment",
            "today timed",
            str(today),
            f"{now.hour + 1:02d}:00",
            "",
            "",
            uuid4(),
        )[0]
        assert call(dsn, USERS[1], "get_next_appointment")[0] == timed
    call(dsn, USERS[2], "create_couple")
    assert call(dsn, USERS[2], "get_next_appointment") is None
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="authentication_required"):
        call(dsn, None, "get_next_appointment")


def test_discovery_api_bounds_projection_and_caller_identity(upstream):  # noqa: F811
    client, calls, replies = upstream
    body = {
        "kind": "report",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "query": " park ",
    }
    for changes in [
        {"query": "x" * 101},
        {"kind": "bad"},
        {"include_archived": "true"},
        {"offset": True},
        {"end_date": "2027-01-02"},
    ]:
        assert client.post("/records/search", json=body | changes).status_code == 422
    assert (
        client.post(
            "/records/search", content="x" * 4097, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert client.post("/records/search", content="{}").status_code == 415
    assert calls == []
    hit = {
        "id": str(uuid4()),
        "date": "2026-01-01",
        "title": "public title",
        "excerpt": "shared",
        "state": "report",
        "visibility": "partner_shared",
        "author_id": "hidden",
    }
    replies.append((200, [hit] * 51))
    response = client.post("/records/search", json=body)
    assert len(response.json()["items"]) == 50 and response.json()["next_offset"] == 50
    assert "author_id" not in response.text and "no-store" in response.headers["cache-control"]
    assert json.loads(calls[-1].content)["p_query"] == "park"
    replies.append(
        (
            200,
            [
                {
                    "id": hit["id"],
                    "title": "next",
                    "date": "2026-10-22",
                    "time": None,
                    "place": "park",
                    "note": "private-extra",
                }
            ],
        )
    )
    response = client.get("/appointments/next")
    assert response.status_code == 200 and "note" not in response.json()["item"]
    replies.append((200, []))
    assert client.get("/appointments/next").json()["item"] is None
