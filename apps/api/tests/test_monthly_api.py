import json

from test_calendar_api import upstream  # noqa: F401


def test_monthly_api_rpc_projection_and_month_validation(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.append(
        (
            200,
            {
                "month": "2026-10",
                "meeting_count": 0,
                "photo_count": 0,
                "route_count": 0,
                "days": [],
                "photos": [],
                "internal": "private",
            },
        )
    )
    result = client.get("/memories/month?month=2026-10")
    assert result.status_code == 200 and "internal" not in result.text
    assert json.loads(calls[0].content) == {"p_month": "2026-10-01"}
    assert client.get("/memories/month?month=2026-13").status_code == 422
    assert "no-store" in result.headers["cache-control"]
