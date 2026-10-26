import json

import httpx
import pytest

from we2day_api.agent_client import AgentClient, calendar_path, prepare_draft, read_json, write_json

KEY = "w2d_agent_" + "a" * 64
BASE = "https://fixture.invalid/api/agent/v1"


def test_draft_preparation_is_offline_preserves_retry_ids_and_refuses_overwrite(tmp_path):
    content = tmp_path / "content.json"
    content.write_text(json.dumps({"title": "synthetic", "date": "2026-11-01"}))
    request = tmp_path / "request.json"
    prepare_draft(content, request)
    first = read_json(request)
    assert first["id"] != first["request_id"] and first["content"]["title"] == "synthetic"
    with pytest.raises(FileExistsError):
        prepare_draft(content, request)
    assert read_json(request) == first
    calls = []

    def handler(req):
        assert req.method == "POST" and req.url.path == "/api/agent/v1/drafts"
        assert req.headers["Authorization"] == "Bearer " + KEY
        assert KEY not in str(req.url)
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"id": first["id"], "created": len(calls) == 1})

    client = AgentClient(BASE, KEY, transport=httpx.MockTransport(handler))
    assert client.request("draft", draft=first)["created"]
    assert not client.request("draft", draft=first)["created"]
    assert calls[0] == calls[1]


@pytest.mark.parametrize(
    "base,key",
    [
        ("http://fixture.invalid/api/agent/v1", KEY),
        ("https://user:secret@fixture.invalid/api/agent/v1", KEY),
        (BASE + "?key=secret", KEY),
        (BASE + "/other", KEY),
        (BASE, "wrong"),
    ],
)
def test_unsafe_configuration_never_connects(base, key):
    with pytest.raises(ValueError):
        AgentClient(base, key)


def test_check_suppresses_records_and_paging_reuses_exact_scope():
    def handler(req):
        assert req.url.params["offset"] == "50"
        return httpx.Response(
            200,
            json={"appointments": [{"note": "private fixture"}], "plans": [], "next_offset": 100},
        )

    client = AgentClient(BASE, KEY, transport=httpx.MockTransport(handler))
    value = client.request("check", start="2026-11-01", end="2026-11-30", offset=50)
    assert value == {"connected": True, "appointments": 1, "plans": 0, "more": True}
    assert "private fixture" not in json.dumps(value)


@pytest.mark.parametrize("status", [301, 401, 403, 409, 429, 503])
def test_errors_do_not_echo_key_or_follow_redirects(status):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(
            status, headers={"location": "https://other.invalid"}, json={"error": KEY}
        )

    client = AgentClient(BASE, KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError) as error:
        client.request("check", start="2026-11-01", end="2026-11-01")
    assert KEY not in str(error.value) and len(calls) == 1


def test_echoed_credential_is_not_returned():
    client = AgentClient(
        BASE,
        KEY,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"error": KEY})),
    )
    with pytest.raises(ValueError, match="invalid_response"):
        client.request("check", start="2026-11-01", end="2026-11-01")


def test_invalid_date_id_or_action_do_not_connect():
    def handler(req):
        pytest.fail("invalid input reached transport")

    client = AgentClient(BASE, KEY, transport=httpx.MockTransport(handler))
    for action, params in [
        ("plan", {"plan_id": "../private"}),
        ("confirm", {}),
        ("calendar", {"start": "2026-01-01", "end": "2026-12-31"}),
    ]:
        with pytest.raises(ValueError):
            client.request(action, **params)
    with pytest.raises(ValueError):
        calendar_path("2026-11-01", "2026-11-01", -1)


def test_private_outputs_refuse_existing_paths_and_duplicate_json(tmp_path):
    output = tmp_path / "output.json"
    write_json(output, {"private": "synthetic"})
    with pytest.raises(FileExistsError):
        write_json(output, {})
    output.write_text('{"title":"one","title":"two"}')
    with pytest.raises(ValueError):
        read_json(output)


def test_large_response_and_oversized_draft_are_rejected(monkeypatch):
    import we2day_api.agent_client as module

    monkeypatch.setattr(module, "MAX_RESPONSE", 20)
    client = AgentClient(
        BASE,
        KEY,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": "x" * 100})),
    )
    with pytest.raises(ValueError, match="response_limit"):
        client.request("check", start="2026-11-01", end="2026-11-01")
