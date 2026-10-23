import base64
import hashlib
import io
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from test_calendar_api import CONFIG, SPACE, USER

from we2day_api import auth
from we2day_api.main import create_app
from we2day_api.photos import normalized_image


def image_bytes(size=(32, 24), **options):
    output = io.BytesIO()
    Image.new("RGB", size, "#a15038").save(output, "WEBP", **options)
    return output.getvalue()


def test_image_validation_and_metadata_stripping():
    source = image_bytes(exif=b"Exif\x00\x00private-gps", xmp=b"private-caption")
    clean, width, height = normalized_image(source)
    assert (width, height) == (32, 24)
    assert b"private" not in clean and b"EXIF" not in clean and b"XMP " not in clean
    for invalid in (b"<svg>fake</svg>", b"x" * 1_048_577, image_bytes((1601, 1))):
        with pytest.raises(HTTPException):
            normalized_image(invalid)


@pytest.fixture
def upstream(monkeypatch):
    calls, state = [], {"stage": "pending", "duplicate": False, "content": None, "deny": False}
    photo_id = str(uuid4())
    original = httpx.Client

    def handler(request):
        assert request.headers["apikey"] == "synthetic-key"
        assert request.headers["authorization"] == "Bearer caller-token"
        if request.url.path == "/auth/v1/user":
            return httpx.Response(
                200,
                json={
                    "id": USER,
                    "aud": "authenticated",
                    "created_at": "2026-10-19T00:00:00Z",
                    "app_metadata": {},
                    "user_metadata": {},
                },
            )
        calls.append(request)
        row = {
            "id": photo_id,
            "couple_id": SPACE,
            "date": "2026-10-24",
            "caption": "산책",
            "filename": "camera.jpg",
            "device": "Camera",
            "captured_at": None,
            "file_modified": None,
            "width": 32,
            "height": 24,
            "bytes": 100,
            "created_by": USER,
            "uploaded_at": None,
            "sha256": state.get("sha256"),
        }
        if state["stage"] == "ready":
            row["uploaded_at"] = "2026-10-19T01:00:00Z"
        if "reserve_photo" in request.url.path:
            import json

            state["sha256"] = json.loads(request.content)["p_sha256"]
            return httpx.Response(200, json=[row])
        if "complete_photo" in request.url.path:
            state["stage"] = "ready"
            return httpx.Response(200, json=[{**row, "uploaded_at": "2026-10-19T01:00:00Z"}])
        if request.url.path == "/rest/v1/photos":
            return httpx.Response(200, json=[] if state["deny"] else [row])
        if request.method == "POST":
            if state["duplicate"]:
                return httpx.Response(409, json={"error": "Duplicate"})
            assert request.headers["x-upsert"] == "false"
            state["content"] = request.content
            return httpx.Response(200, json={"Key": "unused"})
        return httpx.Response(200, content=state["content"])

    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}),
    )
    with TestClient(create_app(CONFIG)) as client:
        client.headers["Authorization"] = "Bearer caller-token"
        body = {
            "date": "2026-10-24",
            "caption": "산책",
            "filename": "camera.jpg",
            "device": "Camera",
            "request_id": str(uuid4()),
            "image": base64.b64encode(image_bytes()).decode(),
        }
        yield client, calls, state, body, photo_id


def test_create_list_download_and_completed_retry(upstream):
    client, calls, state, body, photo_id = upstream
    saved = client.post("/photos", json=body)
    assert saved.status_code == 201 and saved.json()["created_by"] == USER
    assert "couple_id" not in saved.text and "sha256" not in saved.text
    count = len(calls)
    assert client.post("/photos", json=body).status_code == 201
    assert len(calls) == count + 1  # already complete: no second object write
    listed = client.get("/photos?date=2026-10-24")
    assert listed.json()["items"][0]["id"] == photo_id
    result = client.get(f"/photos/{photo_id}/image")
    assert result.status_code == 200 and result.headers["content-type"] == "image/webp"
    assert "no-store" in result.headers["cache-control"]
    state["deny"] = True
    count = len(calls)
    assert client.get(f"/photos/{photo_id}/image").status_code == 404
    assert len(calls) == count + 1  # no Storage download when DB RLS hides the row


def test_lost_upload_response_retry_matches_bytes_and_rejects_conflict(upstream):
    client, _, state, body, _ = upstream
    content, _, _ = normalized_image(base64.b64decode(body["image"]))
    state.update(duplicate=True, content=content)
    assert client.post("/photos", json=body).status_code == 201
    state.update(stage="pending", content=image_bytes((1, 1)))
    assert client.post("/photos", json=body).status_code == 409
    assert state["stage"] == "pending"


def test_rejects_oversize_malformed_and_unauthenticated_uploads(upstream):
    client, calls, _, body, _ = upstream
    for change in (
        {"image": "!!!"},
        {"date": "2026-02-30"},
        {"created_by": USER},
        {"filename": " "},
        {"file_modified": "2026-10-19T00:00:00"},
        {"captured_at": "2026-02-30 00:00:00"},
    ):
        assert client.post("/photos", json={**body, **change}).status_code == 422
    assert not calls
    assert client.post("/photos", content=b"x" * 1_410_001).status_code == 413
    client.headers.pop("Authorization")
    assert client.post("/photos", json=body).status_code == 401
    assert client.get("/photos?date=2026-10-24").status_code == 401


def test_image_integrity_failure_is_not_served(upstream):
    client, _, state, body, photo_id = upstream
    assert client.post("/photos", json=body).status_code == 201
    state["content"] = b"invalid stored content"
    assert hashlib.sha256(state["content"]).hexdigest() != state["sha256"]
    assert client.get(f"/photos/{photo_id}/image").status_code == 409


def test_lifecycle_http_contract_confirmation_and_storage_failure():
    from we2day_api.data import require_data
    from we2day_api.photos import require_storage

    app = create_app(CONFIG)
    calls = []
    photo_id = str(uuid4())
    row = {
        "id": photo_id,
        "couple_id": SPACE,
        "date": "2026-10-19",
        "caption": "사진",
        "filename": "example.jpg",
        "device": None,
        "captured_at": None,
        "file_modified": None,
        "width": 32,
        "height": 24,
        "bytes": 100,
        "created_by": USER,
        "uploaded_at": "2026-10-19T00:00:00Z",
        "trashed_at": "2026-09-01T00:00:00Z",
        "purge_after": "2026-10-01T00:00:00Z",
        "lifecycle_version": 2,
    }

    class Store:
        def rpc(self, name, body):
            calls.append((name, body))
            return [row] if name == "change_photo_lifecycle" else {"deleted": True}

        def call(self, method, path, params):
            calls.append(params)
            return [row]

    class Files:
        failing = True

        def remove(self, path):
            calls.append("storage-remove")
            if self.failing:
                raise HTTPException(503, "Photo service unavailable")

    files = Files()
    app.dependency_overrides[require_data] = lambda: Store()
    app.dependency_overrides[require_storage] = lambda: files
    body = {"expected_version": 2, "request_id": str(uuid4())}
    with TestClient(app) as client:
        assert client.get("/photos?trash=true").json()["items"][0]["lifecycle_version"] == 2
        assert calls[-1]["trashed_at"] == "not.is.null" and "date" not in calls[-1]
        assert client.get("/photos?trash=true&date=2026-10-24").status_code == 200
        assert calls[-1]["date"] == "eq.2026-10-24"
        assert calls[-1]["trashed_at"] == "not.is.null"
        before = len(calls)
        assert client.get("/photos?trash=true&date=invalid").status_code == 422
        assert len(calls) == before
        assert client.post(f"/photos/{photo_id}/restore", json=body).status_code == 200
        assert calls[-1][1]["p_action"] == "restore"
        before = len(calls)
        assert client.post(f"/photos/{photo_id}/purge", json=body).status_code == 422
        assert len(calls) == before
        body["confirmation"] = "영구 삭제"
        assert client.post(f"/photos/{photo_id}/purge", json=body).status_code == 503
        assert calls[-1] == "storage-remove"  # no false DB completion after a file failure
        files.failing = False
        assert client.post(f"/photos/{photo_id}/purge", json=body).status_code == 204
        assert calls[-1][0] == "finish_photo_purge"


def jpeg_bytes(size=(32, 24)):
    output = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "private-device"
    exif[0x9286] = "private-comment"
    Image.new("RGB", size, "#a15038").save(output, "JPEG", exif=exif)
    return output.getvalue()


def test_jpeg_upload_normalizes_to_webp_without_metadata():
    source = jpeg_bytes()
    with pytest.raises(HTTPException):
        normalized_image(source)  # Stored-object reads remain WebP-only.
    clean, width, height = normalized_image(source, allow_jpeg=True)
    assert (width, height) == (32, 24)
    assert clean[:4] == b"RIFF" and clean[8:12] == b"WEBP"
    assert b"private" not in clean and b"EXIF" not in clean and b"XMP " not in clean
    assert normalized_image(source, allow_jpeg=True)[0] == clean
    invalid_png = io.BytesIO()
    Image.new("RGB", (1, 1)).save(invalid_png, "PNG")
    for invalid in (jpeg_bytes((1601, 1)), source[:10], invalid_png.getvalue()):
        with pytest.raises(HTTPException):
            normalized_image(invalid, allow_jpeg=True)


def test_jpeg_upload_and_retry_keep_canonical_storage(upstream):
    client, calls, state, body, photo_id = upstream
    body["image"] = base64.b64encode(jpeg_bytes()).decode()
    assert client.post("/photos", json=body).status_code == 201
    assert state["content"][:4] == b"RIFF" and state["content"][8:12] == b"WEBP"
    count = len(calls)
    assert client.post("/photos", json=body).status_code == 201
    assert len(calls) == count + 1
    assert client.get(f"/photos/{photo_id}/image").headers["content-type"] == "image/webp"
