import json
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from we2day_api.agent_client import AgentClient
from we2day_api.agent_contract import schema
from we2day_api.agents import AgentAppointmentChange, AgentPlanChange
from we2day_api.config import Settings
from we2day_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_generated_schema_matches_routes_examples_and_consequential_operations():
    value = schema()
    assert json.loads((ROOT / "agent-openapi.json").read_text(encoding="utf-8")) == value
    assert len(value["paths"]) == 6
    for methods in value["paths"].values():
        for method, operation in methods.items():
            assert operation["x-openai-isConsequential"] == (method == "post")
            assert len(operation["description"]) <= 300
            assert operation["security"] == [{"HTTPBearer": []}]
    for path in (ROOT / "examples/agent").glob("*.json"):
        if path.name == "plan-content.json":
            continue
        model = AgentPlanChange if path.name.startswith("plan-") else AgentAppointmentChange
        model.model_validate_json(path.read_text(encoding="utf-8"))
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        assert client.get("/agent/openapi.json").json() == value


def test_gateway_new_scope_confirmation_and_secret_sanitization():
    calls = []
    status = [200]

    def upstream(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            status[0], json={"id": str(uuid4())} if status[0] == 200 else {"secret": "no-reflect"}
        )

    app = create_app(
        Settings(
            _env_file=None,
            supabase_url="https://fixture.supabase.co",
            supabase_publishable_key="fixture-publishable",
        )
    )
    with TestClient(app) as client:
        app.state.upstream_pool = httpx.MockTransport(upstream)
        headers = {"Authorization": "Bearer w2d_agent_" + "a" * 64}
        path = f"/agent/v1/plans/{uuid4()}/changes"
        body = {"action": "confirm", "expected_version": 1, "request_id": str(uuid4())}
        assert client.post(path, headers=headers, json=body).status_code == 422
        assert calls == []
        assert (
            client.post(path, headers=headers, json={**body, "confirmed": "true"}).status_code
            == 422
        )
        assert (
            client.post(path, headers=headers, json={**body, "confirmed": True}).status_code == 200
        )
        assert calls[-1]["p_entity"] == "plan" and calls[-1]["p_confirmed"] is True
        status[0] = 403
        response = client.post(path, headers=headers, json={**body, "confirmed": True})
        assert response.status_code == 403 and "no-reflect" not in response.text
        assert client.post(path, json={**body, "confirmed": True}).status_code == 401


def test_client_uses_exact_prepared_change_ids_and_blocks_unconfirmed_write():
    calls = []

    def upstream(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"version": 2})

    client = AgentClient(
        "https://fixture.example/api/agent/v1",
        "w2d_agent_" + "a" * 64,
        transport=httpx.MockTransport(upstream),
    )
    body = {
        "action": "confirm",
        "expected_version": 1,
        "request_id": str(uuid4()),
        "confirmed": True,
    }
    id = str(uuid4())
    for _ in range(2):
        assert client.request("change-plan", target_id=id, change=body)["version"] == 2
    assert calls[0] == calls[1] and calls[0]["request_id"] == body["request_id"]
