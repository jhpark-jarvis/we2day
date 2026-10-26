import base64
import hashlib
import json
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient

from we2day_api.agent_oauth import CALLBACK, CLIENT, SCOPE, tools
from we2day_api.config import Settings
from we2day_api.main import create_app

ORIGIN = "https://fixture.example"
RESOURCE = ORIGIN + "/api/agent/mcp"
VERIFIER = "a" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)
AUTH = dict(
    client_id=CLIENT,
    redirect_uri=CALLBACK,
    response_type="code",
    code_challenge=CHALLENGE,
    code_challenge_method="S256",
    state="s" * 32,
    resource=RESOURCE,
    scope=SCOPE,
)


def app():
    return create_app(
        Settings(
            _env_file=None,
            agent_oauth_origin=ORIGIN,
            supabase_url="https://fixture.supabase.co",
            supabase_publishable_key="fixture-publishable",
        )
    )


def test_metadata_callback_and_pkce_cannot_be_redirected():
    with TestClient(app()) as client:
        assert client.get("/agent/oauth/metadata").json()["issuer"] == ORIGIN
        assert client.get("/agent/oauth/resource").json()["resource"] == RESOURCE
        result = client.get("/agent/oauth/authorize?" + urlencode(AUTH), follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"].startswith(ORIGIN + "/settings/agents/authorize?")
        for field, bad in [
            ("client_id", "https://evil.example/client.json"),
            ("redirect_uri", CALLBACK + "/evil"),
            ("code_challenge_method", "plain"),
            ("resource", "https://evil.example/mcp"),
            ("scope", "admin"),
            ("state", ""),
            ("code_challenge", "short"),
        ]:
            response = client.get("/agent/oauth/authorize?" + urlencode({**AUTH, field: bad}))
            assert response.status_code == 400 and "location" not in response.headers
        assert (
            client.get("/agent/oauth/authorize?" + urlencode(AUTH) + "&scope=admin").status_code
            == 400
        )
        assert client.post("/agent/oauth/approve", json=AUTH).status_code == 401


def test_mcp_metadata_and_bound_dispatch():
    instance = app()
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.url.path == "/rest/v1/rpc/agent_oauth_dispatch"
        data = json.loads(request.content)
        assert data["p_resource"] == RESOURCE and data["p_function"] == "agent_calendar"
        return httpx.Response(200, json={"appointments": [], "plans": []})

    with TestClient(instance) as client:
        instance.state.upstream_pool = httpx.MockTransport(upstream)

        def rpc(method, params=None, **kwargs):
            return client.post(
                "/agent/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                **kwargs,
            )

        assert rpc("initialize").json()["result"]["serverInfo"]["name"] == "we2day"
        entries = rpc("tools/list").json()["result"]["tools"]
        assert len(entries) == 6
        assert sum(t["annotations"]["readOnlyHint"] for t in entries) == 3
        assert all(t["securitySchemes"][0]["scopes"] == [SCOPE] for t in tools())
        params = {"name": "readCalendar", "arguments": {"start": "2026-10-26", "end": "2026-11-01"}}
        denied = rpc("tools/call", params)
        assert (
            denied.status_code == 401 and "resource_metadata=" in denied.headers["www-authenticate"]
        )
        assert not calls
        headers = {"Authorization": "Bearer w2d_agent_" + "a" * 64}
        result = rpc("tools/call", params, headers=headers)
        assert result.json()["result"]["structuredContent"]["plans"] == []
        assert len(calls) == 1
        for args in [
            {"start": "x"},
            {"start": "2026-10-26", "end": "2027-11-01"},
            {"start": "2026-10-26", "end": "2026-11-01", "key": "wrong"},
        ]:
            assert rpc(
                "tools/call", {"name": "readCalendar", "arguments": args}, headers=headers
            ).json()["result"]["isError"]
        assert len(calls) == 1
        assert (
            rpc(
                "tools/call", params, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post("/agent/mcp?access_token=secret", json={}).status_code == 400
        assert (
            client.post(
                "/agent/mcp", content="[1]", headers={"content-type": "application/json"}
            ).status_code
            == 400
        )
        assert rpc("tools/call", [1]).json()["error"]["code"] == -32602


def test_exchange_never_reflects_upstream_or_accepts_unbound_fields():
    instance = app()
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(401, json={"message": "private-diagnostic"})

    with TestClient(instance) as client:
        instance.state.oauth_async_transport = httpx.MockTransport(upstream)
        fields = dict(
            grant_type="authorization_code",
            code="a" * 64,
            client_id=CLIENT,
            redirect_uri=CALLBACK,
            resource=RESOURCE,
            code_verifier=VERIFIER,
        )
        response = client.post("/agent/oauth/token", data=fields)
        assert response.status_code == 400 and response.json() == {"error": "invalid_grant"}
        assert "private-diagnostic" not in response.text
        assert "no-store" in response.headers["cache-control"]
        for bad in [
            {**fields, "resource": "https://evil.example"},
            {**fields, "grant_type": "password"},
        ]:
            assert client.post("/agent/oauth/token", data=bad).status_code == 400
        assert len(requests) == 1
