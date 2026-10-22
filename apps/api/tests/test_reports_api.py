import json
from uuid import uuid4

from test_calendar_api import ROW, USER, upstream  # noqa: F401
from test_reports import REPORT
from test_routes_plans import CONTENT


def test_report_rpc_caller_authority_and_projection(upstream):  # noqa: F811
    client, calls, replies = upstream
    id = str(uuid4())
    row = {
        "plan_id": id,
        "author_id": USER,
        "observed_plan_version": 2,
        "plan_snapshot": CONTENT,
        "content": REPORT,
        "shared": False,
        "version": 1,
        "updated_at": ROW["updated_at"],
        "last_fingerprint": "private",
    }
    replies.extend([(200, [row]), (200, [row])])
    body = {"content": REPORT, "shared": False, "expected_version": 0, "request_id": str(uuid4())}
    result = client.post(f"/reports/{id}", json=body)
    assert result.status_code == 200 and "last_fingerprint" not in result.text
    assert "author_id" not in json.loads(calls[0].content)
    assert client.get(f"/reports/{id}").status_code == 200
    assert "no-store" in result.headers["cache-control"]
    assert client.post(f"/reports/{id}", json={**body, "author_id": USER}).status_code == 422
    assert (
        client.post(
            f"/reports/{id}", json={**body, "content": {**REPORT, "actual_cost": True}}
        ).status_code
        == 422
    )
