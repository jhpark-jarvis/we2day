from test_calendar_api import upstream  # noqa: F401


def test_route_history_pages_projection_and_geojson_pairs(upstream):  # noqa: F811
    client, calls, replies = upstream
    body = {"start_date": "2026-10-01", "end_date": "2026-10-31"}
    row = {
        "date": "2026-10-01",
        "start_name": "start",
        "start_lat": 37.0,
        "start_lng": 127.0,
        "end_name": "end",
        "end_lat": 38.0,
        "end_lng": 128.0,
        "version": 1,
        "updated_at": "2026-10-21T00:00:00Z",
        "couple_id": "hidden",
    }
    replies.extend([(200, {"id": "synthetic"}), (200, [row] * 51)])
    result = client.post("/routes/history", json=body)
    assert result.status_code == 200 and len(result.json()["items"]) == 50
    assert result.json()["next_offset"] == 50 and "couple_id" not in result.text
    assert calls[-1].url.params["and"] == "(date.gte.2026-10-01,date.lte.2026-10-31)"
    replies.extend([(200, {"id": "synthetic"}), (200, [row])])
    result = client.post("/routes/export", json=body)
    assert result.status_code == 200 and result.headers["content-type"].startswith(
        "application/geo+json"
    )
    feature = result.json()["features"][0]
    assert feature["geometry"]["coordinates"] == [[127.0, 37.0], [128.0, 38.0]]
    assert feature["properties"]["route_type"] == "manual_pair" and "couple_id" not in result.text
    assert client.post("/routes/history", json=body | {"end_date": "2028-01-01"}).status_code == 422
    replies.append((200, None))
    assert client.post("/routes/history", json=body).status_code == 409
    assert client.post("/routes/export", json=body | {"offset": 50}).status_code == 422
