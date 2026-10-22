import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401


def test_questions_projection_and_input(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    q = {
        "id": id,
        "date": "2026-10-19",
        "prompt": "질문",
        "created_by": USER,
        "created_at": ROW["updated_at"],
        "fingerprint": "private",
    }
    a = {
        "question_id": id,
        "author_id": USER,
        "content": "답변",
        "shared": False,
        "skipped": False,
        "version": 1,
        "updated_at": ROW["updated_at"],
        "last_request_id": "private",
    }
    replies.extend([(200, [q]), (200, [q]), (200, [q]), (200, [a]), (200, [a])])
    body = {"date": "2026-10-19", "prompt": "질문", "request_id": str(uuid4())}
    assert "fingerprint" not in client.post(f"/questions/{id}", json=body).text
    assert client.get("/questions?date=2026-10-19").status_code == 200
    view = client.get(f"/questions/{id}").json()
    assert view["mine"]["content"] == "답변" and view["partner"] is None
    change = {
        "content": "답변",
        "shared": False,
        "skipped": False,
        "expected_version": 0,
        "request_id": str(uuid4()),
    }
    assert client.post(f"/questions/{id}/answer", json=change).status_code == 200
    assert "p_author_id" not in json.loads(calls[-1].content)
    assert (
        client.post(
            f"/questions/{id}/answer", json={**change, "shared": True, "skipped": True}
        ).status_code
        == 422
    )
    assert client.post(f"/questions/{id}", json={**body, "prompt": " "}).status_code == 422


def test_timezone_projection_and_actor_not_input(upstream):  # noqa: F811
    client, calls, replies = upstream
    row = {
        "user_id": USER,
        "timezone": "UTC",
        "version": 1,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row])])
    assert client.get("/timezones").json()["mine"]["timezone"] == "UTC"
    body = {"timezone": "UTC", "expected_version": 0, "request_id": str(uuid4())}
    result = client.post("/timezones", json=body)
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert "p_user_id" not in json.loads(calls[-1].content)
    assert client.post("/timezones", json={**body, "user_id": USER}).status_code == 422


def test_roulette_projection_unique_candidates_and_draw(upstream):  # noqa: F811
    client, calls, replies = upstream
    id, draw_id = str(uuid4()), str(uuid4())
    wheel = {
        "id": id,
        "title": "고르기",
        "candidates": ["산책", "카페"],
        "archived": False,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
    }
    draw = {
        "id": draw_id,
        "wheel_id": id,
        "wheel_version": 1,
        "candidates": wheel["candidates"],
        "selected_index": 0,
        "drawn_by": USER,
        "drawn_at": ROW["updated_at"],
    }
    replies.extend([(200, [wheel]), (200, [draw]), (200, [draw])])
    body = {
        "title": "고르기",
        "candidates": wheel["candidates"],
        "archived": False,
        "expected_version": 0,
        "request_id": str(uuid4()),
    }
    assert client.post(f"/roulette/{id}", json=body).status_code == 200
    assert (
        client.post(f"/roulette/{id}", json={**body, "candidates": ["산책", " 산책 "]}).status_code
        == 422
    )
    assert (
        client.post(
            f"/roulette/{id}/draws", json={"expected_version": 1, "request_id": draw_id}
        ).json()["selected_index"]
        == 0
    )
    assert client.get(f"/roulette/{id}/draws").status_code == 200
