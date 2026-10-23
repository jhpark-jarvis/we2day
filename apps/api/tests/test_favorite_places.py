import json
from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError
from test_calendar_api import ROW, USER, upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401

from we2day_api.favorite_places import FavoriteChange


def test_favorite_projection_pagination_validation_and_auth(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = dict(
        id=str(uuid4()),
        label="공유 장소",
        destination="직접 입력한 곳",
        archived=False,
        version=1,
        updated_by=USER,
        updated_at=ROW["updated_at"],
        couple_id="private",
        last_fingerprint="private",
    )
    replies.extend([(200, [row] * 51), (200, []), (200, [row])])
    view = client.get("/favorite-places")
    assert len(view.json()["items"]) == 50
    assert view.json()["next_offset"] == 50
    assert "private" not in view.text
    assert calls[-1].url.params["limit"] == "51"
    assert calls[-1].url.params["select"] == (
        "id,label,destination,archived,version,updated_by,updated_at"
    )
    assert client.get("/favorite-places?archived=true&offset=50").json() == {
        "items": [],
        "next_offset": None,
    }
    assert calls[-1].url.params["archived"] == "eq.true"
    assert calls[-1].url.params["offset"] == "50"
    body = dict(
        label=row["label"],
        destination=row["destination"],
        archived=False,
        expected_version=0,
        request_id=str(uuid4()),
    )
    path = "/favorite-places/" + row["id"]
    assert client.post(path, json=body).status_code == 200
    assert json.loads(calls[-1].content) == {
        "p_id": row["id"],
        **{"p_" + key: value for key, value in body.items()},
    }
    for extra in [dict(couple_id="other"), dict(updated_by=USER)]:
        assert client.post(path, json={**body, **extra}).status_code == 422
    assert (
        client.post(path, content="{}", headers={"content-type": "text/plain"}).status_code == 415
    )
    assert (
        client.post(
            path, content="x" * 2049, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
    assert client.get("/favorite-places?offset=-1").status_code == 422
    client.headers.clear()
    assert client.get("/favorite-places").status_code == 401


def test_favorite_input_bounds_and_plain_text():
    base = dict(
        label="우리의 카페",
        destination="직접 입력한 장소",
        expected_version=0,
        request_id=str(uuid4()),
    )
    assert FavoriteChange(**base).label == "우리의 카페"
    for changed in [
        dict(label=" "),
        dict(destination="x" * 201),
        dict(destination="a\nb"),
        dict(label="a\x00"),
        dict(unexpected="value"),
    ]:
        with pytest.raises(ValidationError):
            FavoriteChange(**{**base, **changed})


def test_favorite_sharing_retry_conflict_archive_and_denial(database_url):
    dsn = database_url
    connect_pair(dsn)
    id, request = uuid4(), uuid4()
    args = (id, "산책 출발", "직접 입력한 목적지", False, 0, request)
    saved = call(dsn, USERS[0], "save_favorite_place", *args)
    assert call(dsn, USERS[0], "save_favorite_place", *args) == saved
    with actor(dsn, USERS[1]) as db:
        assert db.execute(
            "select label,destination,version from public.favorite_places"
        ).fetchone() == (args[1], args[2], 1)
    with actor(dsn, USERS[2]) as db:
        assert db.execute("select count(*) from public.favorite_places").fetchone() == (0,)
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[1], "save_favorite_place", *args)
    call(dsn, USERS[1], "save_favorite_place", id, args[1], args[2], True, 1, uuid4())
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "save_favorite_place", *(*args[:-1], uuid4()))
    call(dsn, USERS[0], "save_favorite_place", id, "함께 쓰는 장소", args[2], False, 2, uuid4())
    call(dsn, USERS[2], "create_couple")
    with pytest.raises(psycopg.Error, match="favorite_place_not_found"):
        call(dsn, USERS[2], "save_favorite_place", *args)
    for text in ["", " ", "x" * 201, "a\nb"]:
        with pytest.raises(psycopg.Error, match="invalid_favorite_place"):
            call(dsn, USERS[0], "save_favorite_place", uuid4(), "목적지", text, False, 0, uuid4())
    with actor(dsn, USERS[0]) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("delete from public.favorite_places")
    with actor(dsn, None, "anon") as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from public.favorite_places")
    with psycopg.connect(dsn) as db:
        for role in ["anon", "we2day_reminder_worker"]:
            assert not db.execute(
                "select has_table_privilege(%s,'public.favorite_places','SELECT')", (role,)
            ).fetchone()[0]
            assert not db.execute(
                "select has_function_privilege(%s,"
                "'public.save_favorite_place(uuid,text,text,boolean,integer,uuid)','EXECUTE')",
                (role,),
            ).fetchone()[0]
