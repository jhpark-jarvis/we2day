from test_calendar_api import upstream  # noqa: F401


def test_timeline_filters_published_date_and_bounds(upstream):  # noqa: F811
    client, calls, replies = upstream
    replies.append((200, []))
    result = client.get("/timeline?date=2026-10-19&offset=50")
    assert result.status_code == 200 and result.json() == []
    assert calls[0].url.params["published_content->>date"] == "eq.2026-10-19"
    assert calls[0].url.params["archived"] == "eq.false"
    assert calls[0].url.params["offset"] == "50"
    for date in ["2026-02-30", "1999-12-31", "2101-01-01"]:
        assert client.get(f"/timeline?date={date}").status_code == 422
