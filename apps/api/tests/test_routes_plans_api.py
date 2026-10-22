import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401

CONTENT = {
    "title": "함께 산책",
    "date": "2026-11-01",
    "budget": None,
    "transport": "",
    "activities": [],
    "preparation": [],
}


def test_routes_api_projection_bounds_and_rpc(upstream):  # noqa: F811
    client, calls, replies = upstream
    route = {
        "date": "2026-10-01",
        "start_name": "출발",
        "start_lat": 37.5,
        "start_lng": 127.0,
        "end_name": "도착",
        "end_lat": 37.6,
        "end_lng": 127.1,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [route]), (200, [route])])
    result = client.get("/routes?date=2026-10-01")
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    content = {k: v for k, v in route.items() if k.startswith(("start_", "end_"))}
    body = {**content, "expected_version": 0, "request_id": str(uuid4())}
    result = client.post("/routes/2026-10-01", json=body)
    assert result.status_code == 200
    assert json.loads(calls[-1].content)["p_expected_version"] == 0
    assert client.post("/routes/2026-10-01", json={**body, "start_lat": 91}).status_code == 422
    assert client.post("/routes/2100-12-31", json=body).status_code == 422
    assert "no-store" in result.headers["cache-control"]


def test_plan_api_save_read_and_contract(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    plan = {
        "id": id,
        "content": CONTENT,
        "published_content": None,
        "appointment_id": None,
        "appointment": None,
        "archived": False,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [plan]), (200, [plan])])
    result = client.post(
        f"/plans/{id}",
        json={
            "action": "save",
            "content": CONTENT,
            "expected_version": 0,
            "request_id": str(uuid4()),
        },
    )
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert json.loads(calls[0].content)["p_content"] == CONTENT
    assert calls[1].url.params["id"] == f"eq.{id}"
    assert (
        client.post(
            f"/plans/{id}",
            json={
                "action": "confirm",
                "content": CONTENT,
                "expected_version": 1,
                "request_id": str(uuid4()),
            },
        ).status_code
        == 422
    )
