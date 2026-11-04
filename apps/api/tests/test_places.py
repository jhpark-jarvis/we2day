import json

import httpx
import pytest
from fastapi.testclient import TestClient

from we2day_api import places
from we2day_api.config import Settings
from we2day_api.data import require_data
from we2day_api.main import create_app


class Store:
    connected = True

    def rpc(self, name):
        assert name == "get_my_couple"
        return {"member_count": 2} if self.connected else None


@pytest.fixture
def search(monkeypatch):
    config = Settings(
        _env_file=None,
        naver_search_enabled=True,
        naver_search_client_id="synthetic-id",
        naver_search_client_secret="synthetic-secret",
    )
    app = create_app(config)
    store = Store()
    app.dependency_overrides[require_data] = lambda: store
    calls, replies = [], []
    original = httpx.Client

    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(places.HUB_URL + "?")
        assert request.headers["X-NCP-APIGW-API-KEY-ID"] == "synthetic-id"
        assert request.headers["X-NCP-APIGW-API-KEY"] == "synthetic-secret"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(
        places.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    with TestClient(app) as client:
        yield client, config, store, calls, replies


def test_search_hub_contract_order_and_no_store(search):
    client, config, store, calls, replies = search
    # Authored fictional fixtures; not copied or cached NAVER results.
    items = [{"title": "<b>가상</b> 카페", "roadAddress": "예시 거리"}, {"title": "두 번째"}]
    replies.append(httpx.Response(200, json={"items": items, "unneeded": "discard"}))
    result = client.post("/places/search", json={"query": " 가상 카페 "})
    assert result.status_code == 200
    assert [x["title"] for x in result.json()["items"]] == [x["title"] for x in items]
    assert "unneeded" not in result.text and "synthetic" not in result.text
    assert "no-store" in result.headers["cache-control"]
    assert dict(calls[0].url.params) == {
        "query": "가상 카페",
        "display": "5",
        "start": "1",
        "sort": "random",
    }
    replies.append(httpx.Response(200, json={"items": []}))
    assert client.post("/places/search", json={"query": "없는 가상 장소"}).json() == {"items": []}
    before = len(calls)
    store.connected = False
    assert client.post("/places/search", json={"query": "검색"}).status_code == 403
    store.connected = True
    config.naver_search_enabled = False
    assert client.post("/places/search", json={"query": "검색"}).json()["detail"] == (
        "place_search_not_configured"
    )
    config.naver_search_enabled = True
    config.naver_search_client_secret = None
    assert client.post("/places/search", json={"query": "검색"}).status_code == 503
    assert len(calls) == before


@pytest.mark.parametrize("query", ["", "   ", "a" * 101, "a\nb", 42, None])
def test_invalid_search_never_calls_provider(search, query):
    client, _, _, calls, _ = search
    response = client.post("/places/search", json={"query": query})
    assert response.status_code == 422 and not calls
    assert "input" not in response.text


def test_search_body_limits_authentication_and_extra_fields(search):
    client, _, _, calls, _ = search
    assert (
        client.post(
            "/places/search", content="x" * 2049, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
    assert client.post("/places/search", content="bad").status_code == 415
    assert (
        client.post("/places/search", json={"query": "a", "url": "https://bad.invalid"}).status_code
        == 422
    )
    assert not calls
    with TestClient(create_app(Settings(_env_file=None))) as anonymous:
        assert anonymous.post("/places/search", json={"query": "a"}).status_code == 401


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(302, headers={"location": "https://bad.invalid"}),
        httpx.Response(401, text="synthetic-secret query"),
        httpx.Response(500, text="synthetic-secret query"),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, json={"items": [{"title": "x"}] * 6}),
        httpx.Response(200, content=json.dumps({"items": None})),
        httpx.ReadTimeout("private-query synthetic-secret"),
    ],
)
def test_provider_failure_is_bounded_and_does_not_leak(search, reply):
    client, _, _, calls, replies = search
    replies.append(reply)
    response = client.post("/places/search", json={"query": "검색"})
    assert response.status_code == 503 and len(calls) == 1
    assert response.json() == {"detail": "place_search_unavailable"}


def test_provider_quota_no_automatic_retry(search):
    client, _, _, calls, replies = search
    replies.append(httpx.Response(429, text="private"))
    response = client.post("/places/search", json={"query": "검색"})
    assert response.status_code == 429 and len(calls) == 1
    assert response.json() == {"detail": "place_search_limited"}


@pytest.mark.parametrize("x,y", [("127.04", "37.54"), ("1270400000", "375400000")])
def test_provider_coordinates_are_normalized_and_server_only(x, y):
    item = places.PlaceResult(title="공공 예시", mapx=x, mapy=y)
    assert item.coordinates == (127.04, 37.54)
    assert not {"mapx", "mapy", "coordinates"} & item.model_dump().keys()


@pytest.mark.parametrize(
    "x,y",
    [
        (None, None),
        ("", ""),
        ("NaN", "37"),
        ("inf", "37"),
        (True, "37"),
        ("37.54", "127.04"),
        ("311277", "552097"),
        ("1270400000", "37.54"),
        ("181", "91"),
        ([], {}),
        ("0", "0"),
        ("1" * 1000, "375400000"),
    ],
)
def test_invalid_coordinates_do_not_discard_a_usable_place(x, y):
    item = places.PlaceResult(title="좌표 없는 후보", mapx=x, mapy=y)
    assert item.coordinates is None
    assert item.model_dump()["title"] == "좌표 없는 후보"


def test_authenticated_search_never_exposes_coordinates(search):
    client, _, _, _, replies = search
    replies.append(
        httpx.Response(
            200,
            json={
                "items": [
                    {"title": "공공 예시", "mapx": "1270400000", "mapy": "375400000"},
                    {"title": "비정상 좌표", "mapx": [], "mapy": "NaN"},
                ]
            },
        )
    )
    result = client.post("/places/search", json={"query": "공공 예시"})
    assert result.status_code == 200 and len(result.json()["items"]) == 2
    assert not any(key in result.text for key in ["mapx", "mapy", "1270400000", "coordinates"])


def test_straight_line_distance_is_symmetric_but_not_a_travel_estimate():
    a, b = (127.04, 37.54), (127.041, 37.54)
    assert places.straight_line_m(a, a) == 0
    assert 80 < places.straight_line_m(a, b) < 95
    assert places.straight_line_m(a, b) == pytest.approx(places.straight_line_m(b, a))
