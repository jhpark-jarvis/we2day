from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_routes_plans import CONTENT, change

from we2day_api.config import Settings
from we2day_api.data import require_data
from we2day_api.main import create_app


def test_draft_delete_shared_scope_version_and_confirmed_guard(database_url):
    dsn = database_url
    connect_pair(dsn)
    id = uuid4()
    change(dsn, USERS[0], id, "save", 0, CONTENT)
    call(dsn, USERS[2], "create_couple")
    call(dsn, USERS[2], "delete_plan_draft", id, 1)
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select id from public.date_plans where id=%s", (id,)).fetchone()
    change(dsn, USERS[1], id, "save", 1, {**CONTENT, "title": "Changed"})
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "delete_plan_draft", id, 1)
    call(dsn, USERS[1], "delete_plan_draft", id, 2)
    call(dsn, USERS[1], "delete_plan_draft", id, 2)
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select id from public.date_plans where id=%s", (id,)).fetchone() is None
    id = uuid4()
    change(dsn, USERS[0], id, "save", 0, CONTENT)
    change(dsn, USERS[0], id, "confirm", 1)
    with pytest.raises(psycopg.Error, match="plan_draft_required"):
        call(dsn, USERS[1], "delete_plan_draft", id, 2)
    with actor(dsn, USERS[0]) as db:
        assert db.execute("select count(*) from public.appointments").fetchone() == (1,)
    with actor(dsn, None, "anon") as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.delete_plan_draft(%s,1)", (id,))
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("delete from public.date_plans where id=%s", (id,))


def test_ordering_across_page_boundary_and_rls(database_url):
    dsn = database_url
    connect_pair(dsn)
    with actor(dsn, USERS[0]) as db:
        for index in range(55):
            content = {
                **CONTENT,
                "title": f"Plan {54 - index:02}",
                "date": f"2030-{1 + index // 28:02}-{1 + index % 28:02}",
            }
            db.execute(
                "select public.change_date_plan(%s,'save',%s,0,0,%s)",
                (uuid4(), Jsonb(content), uuid4()),
            )
    for sort, column, reverse in [
        ("date_desc", 2, True),
        ("date_asc", 2, False),
        ("title_asc", 1, False),
    ]:
        with actor(dsn, USERS[1]) as db:
            rows = db.execute(
                "select * from public.list_plan_summaries(false,0,%s)", (sort,)
            ).fetchall()
            rows += db.execute(
                "select * from public.list_plan_summaries(false,50,%s)", (sort,)
            ).fetchall()
        assert len(rows) == 55 and len({row[0] for row in rows}) == 55
        assert [row[column] for row in rows] == sorted(
            [row[column] for row in rows], reverse=reverse
        )
    with actor(dsn, USERS[2]) as db:
        assert not db.execute(
            "select * from public.list_plan_summaries(false,0,'date_desc')"
        ).fetchall()
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.Error, match="invalid_plan"):
        db.execute("select * from public.list_plan_summaries(false,0,'injection')")


def test_api_delete_and_sort_validation():
    calls = []

    class Store:
        def rpc(self, name, body):
            calls.append((name, body))
            return [] if name == "list_plan_summaries" else None

    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[require_data] = lambda: Store()
    id = str(uuid4())
    with TestClient(app) as client:
        response = client.request("DELETE", f"/plans/{id}", json={"expected_version": 1})
        assert response.status_code == 204 and not response.content
        assert calls[-1] == ("delete_plan_draft", {"p_id": id, "p_expected_version": 1})
        assert (
            client.request("DELETE", f"/plans/{id}", json={"expected_version": 0}).status_code
            == 422
        )
        assert client.get("/plans?summary=true&sort=date_asc").status_code == 200
        assert calls[-1][1]["p_sort"] == "date_asc"
        assert client.get("/plans?sort=invalid").status_code == 422
