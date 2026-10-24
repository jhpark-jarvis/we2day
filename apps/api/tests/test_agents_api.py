import json
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from we2day_api.config import Settings
from we2day_api.main import create_app


def test_gateway_separates_credentials_and_sanitizes_upstream_errors():
    calls = []
    status = [200]

    def handler(request):
        calls.append(request)
        assert request.headers["apikey"] == "fixture-publishable"
        assert "authorization" not in request.headers
        assert request.url.path.startswith("/rest/v1/rpc/agent_")
        return httpx.Response(
            status[0], json={"private": "do-not-reflect"} if status[0] != 200 else {"plans": []}
        )

    app = create_app(
        Settings(
            _env_file=None,
            supabase_url="https://fixture.supabase.co",
            supabase_publishable_key="fixture-publishable",
        )
    )
    with TestClient(app) as client:
        app.state.upstream_pool = httpx.MockTransport(handler)
        path = "/agent/v1/calendar?start=2026-11-01&end=2026-11-02"
        token = "w2d_agent_" + "a" * 64
        for bad in ["", "Bearer wrong", "Bearer " + token + "?extra"]:
            assert client.get(path, headers={"Authorization": bad}).status_code == 401
        assert calls == []
        assert client.get("/plans", headers={"Authorization": "Bearer " + token}).status_code == 401
        assert calls == []
        headers = {"Authorization": "Bearer " + token}
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
        assert json.loads(calls[-1].content)["p_key"] == token
        for code in [401, 404, 409, 422, 429, 500]:
            status[0] = code
            response = client.get(path, headers=headers)
            assert response.status_code == (503 if code == 500 else code)
            assert "do-not-reflect" not in response.text and token not in response.text
        assert (
            client.post(
                "/agent/v1/drafts",
                headers=headers,
                json={
                    "id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "action": "confirm",
                    "content": {},
                },
            ).status_code
            == 422
        )
