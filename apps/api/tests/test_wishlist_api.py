import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401


def test_wishlist_api_validation_and_projection(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    content = {"title": "공원", "kind": "place", "note": "", "done": False, "archived": False}
    row = {
        **content,
        "id": id,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row])])
    body = {**content, "expected_version": 0, "request_id": str(uuid4())}
    result = client.post(f"/wishlist/{id}", json=body)
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert json.loads(calls[0].content)["p_id"] == id
    assert client.get("/wishlist?archived=true&offset=50").status_code == 200
    assert calls[-1].url.params["archived"] == "eq.true"
    assert client.post(f"/wishlist/{id}", json={**body, "note": "x" * 1001}).status_code == 422
    assert client.get("/wishlist?offset=100001").status_code == 422
