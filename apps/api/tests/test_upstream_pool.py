import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from fastapi.testclient import TestClient

from we2day_api.config import Settings
from we2day_api.main import create_app


def test_pool_reuses_connections_without_sharing_auth_or_cookies(monkeypatch):
    calls = []
    users = {
        "first": "11111111-1111-4111-8111-111111111111",
        "second": "22222222-2222-4222-8222-222222222222",
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()

        def do_GET(self):
            token = self.headers["Authorization"].removeprefix("Bearer ")
            calls.append((token, self.headers.get("Cookie"), self.client_address[1]))
            if token == "revoked":
                payload, status = {"msg": "revoked", "error_code": "bad_jwt"}, 401
            elif self.path == "/rest/v1/rpc/get_my_couple":
                payload, status = {"id": users[token], "member_count": 1}, 200
            else:
                payload, status = (
                    {
                        "id": users[token],
                        "aud": "authenticated",
                        "created_at": "2026-10-21T00:00:00Z",
                        "app_metadata": {},
                        "user_metadata": {},
                    },
                    200,
                )
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Set-Cookie", "upstream=must-not-cross-callers; Path=/")
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    closed = []
    original_close = httpx.HTTPTransport.close

    def close(pool):
        closed.append(pool)
        original_close(pool)

    monkeypatch.setattr(httpx.HTTPTransport, "close", close)
    app = create_app(
        Settings(
            _env_file=None,
            supabase_url=f"http://127.0.0.1:{server.server_port}",
            supabase_publishable_key="synthetic-key",
        )
    )
    try:
        with TestClient(app) as client:

            def read(token):
                response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
                assert "no-store" in response.headers["cache-control"]
                return response

            assert read("first").json()["id"] == users["first"]
            assert read("second").json()["id"] == users["second"]
            assert calls[0][2] == calls[1][2]
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(read, ["first", "second"] * 3))
            assert [r.json()["id"] for r in results] == [users[t] for t in ["first", "second"] * 3]
            assert read("revoked").status_code == 401
            for token in users:
                response = client.get("/couple", headers={"Authorization": f"Bearer {token}"})
                assert response.json()["id"] == users[token]
            assert len(calls) == 13  # Auth runs every time; each couple read also calls REST.
            assert all(cookie is None for _, cookie, _ in calls)
            assert app.state.upstream_pool not in closed
        assert closed.count(app.state.upstream_pool) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
