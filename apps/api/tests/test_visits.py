from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT, change


def plan(dsn):
    id = uuid4()
    content = {**deepcopy(CONTENT), "date": "2026-01-01"}
    change(dsn, USERS[0], id, "save", 0, content)
    change(dsn, USERS[0], id, "confirm", 1)
    return id, content


def visit(
    dsn, id, user=USERS[0], publication=1, activity=0, state="visited", version=0, request=None
):
    return call(
        dsn,
        user,
        "change_visit_progress",
        id,
        publication,
        activity,
        state,
        version,
        request or uuid4(),
    )


def test_visit_shared_cas_retry_permissions_and_no_inference(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, content = plan(dsn)
    request = uuid4()
    first = visit(dsn, id, request=request)
    assert visit(dsn, id, request=request) == first
    with pytest.raises(psycopg.Error, match="request_conflict"):
        visit(dsn, id, request=request, state="skipped")
    with actor(dsn, USERS[1]) as c:
        row = c.execute("select snapshot,states,version from public.plan_visit_progress").fetchone()
        assert row == (content, ["visited"], 1)
        assert c.execute("select count(*) from public.meeting_days").fetchone() == (0,)
        assert c.execute("select count(*) from public.meeting_routes").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        visit(dsn, id, USERS[1], state="skipped")
    visit(dsn, id, USERS[1], state="skipped", version=1)
    visit(dsn, id, state="planned", version=2)
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select states,version from public.plan_visit_progress").fetchone() == (
            ["planned"],
            3,
        )
    for kwargs in [{"activity": 1}, {"activity": -1}, {"state": "arrived"}, {"version": -1}]:
        with pytest.raises(psycopg.Error, match="invalid_visit_progress"):
            visit(dsn, id, **kwargs)
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="plan_not_found"):
        visit(dsn, id, USERS[2])
    with actor(dsn, USERS[2]) as c:
        assert c.execute("select count(*) from public.plan_visit_progress").fetchone() == (0,)
    for role, user in [("anon", None), ("authenticated", USERS[0])]:
        with actor(dsn, user, role) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("delete from public.plan_visit_progress")
    with actor(dsn, None, "anon") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.change_visit_progress(%s,1,0,'visited',0,%s)", (id, uuid4()))


def test_publication_changes_preserve_history_and_block_old_future_archive(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, content = plan(dsn)
    visit(dsn, id)
    modified = {**content, "title": "새 확정안"}
    change(dsn, USERS[0], id, "save", 2, modified)
    with actor(dsn, USERS[1]) as c:
        assert c.execute("select published_revision from public.date_plans").fetchone() == (1,)
    change(dsn, USERS[1], id, "confirm", 3, av=1)
    with pytest.raises(psycopg.Error, match="publication_changed"):
        visit(dsn, id, version=1)
    visit(dsn, id, USERS[1], publication=2, state="skipped")
    # Same confirmed content and archive/restore keep the publication identity.
    change(dsn, USERS[0], id, "confirm", 4, av=2)
    change(dsn, USERS[0], id, "archive", 5)
    with pytest.raises(psycopg.Error, match="plan_archived"):
        visit(dsn, id, publication=2, version=1)
    change(dsn, USERS[0], id, "restore", 6)
    change(dsn, USERS[0], id, "save", 7, content)
    change(dsn, USERS[0], id, "confirm", 8, av=3)
    with actor(dsn, USERS[0]) as c:
        assert c.execute("select published_revision from public.date_plans").fetchone() == (3,)
        assert c.execute(
            "select publication,snapshot,states from public.plan_visit_progress "
            "order by publication"
        ).fetchall() == [(1, content, ["visited"]), (2, modified, ["skipped"])]
    future = {**content, "date": "2100-01-01"}
    change(dsn, USERS[0], id, "save", 9, future)
    change(dsn, USERS[0], id, "confirm", 10, av=4)
    with pytest.raises(psycopg.Error, match="invalid_visit_progress"):
        visit(dsn, id, publication=4)


def test_visit_api_projection_and_strict_change(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    row = dict(
        plan_id=id,
        publication=1,
        snapshot=CONTENT,
        states=["visited"],
        version=1,
        updated_by=str(uuid4()),
        updated_at="2026-10-20T00:00:00Z",
        last_fingerprint="private",
    )
    body = dict(
        publication=1, activity=0, state="visited", expected_version=0, request_id=str(uuid4())
    )
    replies.append((200, [row]))
    response = client.post(f"/plans/{id}/visits", json=body)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert "last_fingerprint" not in response.json()
    assert calls[-1].url.path.endswith("/rpc/change_visit_progress")
    plan_row = dict(
        id=id,
        content=CONTENT,
        published_content=CONTENT,
        published_revision=1,
        appointment_id=str(uuid4()),
        archived=False,
        version=2,
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )
    replies.extend([(200, [plan_row]), (200, [row])])
    result = client.get(f"/plans/{id}/visits?offset=20")
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert calls[-1].url.params["limit"] == "20" and calls[-1].url.params["offset"] == "20"
    for change_ in [
        {"publication": 0},
        {"activity": True},
        {"state": "arrived"},
        {"snapshot": CONTENT},
    ]:
        before = len(calls)
        assert client.post(f"/plans/{id}/visits", json={**body, **change_}).status_code == 422
        assert len(calls) == before
    client.headers.pop("Authorization")
    assert client.post(f"/plans/{id}/visits", json=body).status_code == 401
