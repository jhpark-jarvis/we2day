import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401


def test_checklist_api_validation_and_projection(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    item = {"id": str(uuid4()), "title": "물", "quantity": "두 병", "done": False}
    content = {"title": "준비", "note": "", "items": [item], "archived": False}
    row = {
        **content,
        "id": id,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row]), (200, [row]), (200, [])])
    body = {**content, "expected_version": 0, "request_id": str(uuid4())}
    result = client.post(f"/checklists/{id}", json=body)
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert result.headers["cache-control"] == "private, no-store"
    assert json.loads(calls[0].content)["p_items"] == [item]
    assert client.get("/checklists?archived=true&offset=50").status_code == 200
    assert calls[-1].url.params["archived"] == "eq.true"
    assert client.get(f"/checklists/{id}").status_code == 200
    assert client.get(f"/checklists/{uuid4()}").status_code == 404
    for items in [
        [{**item, "done": "false"}],
        [item, item],
        [{**item, "quantity": "x" * 101}],
        [item] * 51,
    ]:
        assert client.post(f"/checklists/{id}", json={**body, "items": items}).status_code == 422
    assert client.get("/checklists?offset=100001").status_code == 422


def test_checklist_rpc_errors_keep_safe_status(upstream):  # noqa: F811
    client, calls, replies = upstream
    body = {
        "title": "준비",
        "note": "",
        "items": [],
        "archived": False,
        "expected_version": 1,
        "request_id": str(uuid4()),
    }
    for status, message in [
        (422, "invalid_checklist"),
        (404, "checklist_not_found"),
        (422, "checklist_items_retained"),
    ]:
        replies.append(
            (
                status,
                {
                    "code": f"PT{status}",
                    "message": message,
                    "details": "must not expose SQL details",
                },
            )
        )
        response = client.post(f"/checklists/{uuid4()}", json=body)
        assert response.status_code == status
        assert response.json() == {"detail": message}
