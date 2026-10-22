import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401


def test_goal_api_dates_steps_projection_and_safe_errors(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    step = {"id": str(uuid4()), "title": "작은 단계", "done": True}
    content = {
        "title": "목표",
        "target_date": "2028-02-29",
        "steps": [step],
        "completed": False,
        "archived": False,
    }
    row = {
        **content,
        "id": id,
        "version": 1,
        "updated_by": USER,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row]), (200, [{**row, "target_date": None}]), (200, [])])
    body = {**content, "expected_version": 0, "request_id": str(uuid4())}
    response = client.post(f"/goals/{id}", json=body)
    assert response.status_code == 200 and "last_fingerprint" not in response.text
    assert response.json()["completed"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert json.loads(calls[0].content)["p_target_date"] == "2028-02-29"
    assert client.get("/goals?archived=true&offset=50").status_code == 200
    assert calls[-1].url.params["archived"] == "eq.true"
    assert client.get(f"/goals/{id}").json()["target_date"] is None
    assert client.get(f"/goals/{uuid4()}").status_code == 404
    for target in ["2027-02-29", "1999-12-31", "2101-01-01", "20260101", "", 20260101]:
        assert client.post(f"/goals/{id}", json={**body, "target_date": target}).status_code == 422
    for steps in [[{**step, "done": "false"}], [step, step], [step] * 51]:
        assert client.post(f"/goals/{id}", json={**body, "steps": steps}).status_code == 422
    assert client.get("/goals?offset=100001").status_code == 422
    for status, message in [
        (422, "invalid_goal"),
        (404, "goal_not_found"),
        (422, "goal_steps_retained"),
    ]:
        replies.append((status, {"code": f"PT{status}", "message": message, "details": "private"}))
        result = client.post(f"/goals/{id}", json=body)
        assert result.status_code == status and result.json() == {"detail": message}
