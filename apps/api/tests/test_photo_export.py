import hashlib
import io
import json
import zipfile
from uuid import uuid4

from fastapi.testclient import TestClient
from test_calendar_api import CONFIG, SPACE, USER
from test_photos import image_bytes

from we2day_api.data import require_data
from we2day_api.main import create_app
from we2day_api.photos import require_storage


def test_photo_export_archive_hash_paths_and_all_or_nothing_permissions():
    content = image_bytes(exif=b"Exif\x00\x00private-gps")
    photo_id = str(uuid4())
    row = {
        "id": photo_id,
        "couple_id": SPACE,
        "sha256": hashlib.sha256(content).hexdigest(),
        "date": "2026-10-19",
        "caption": "사진",
        "filename": "../../private.jpg",
        "device": None,
        "captured_at": None,
        "file_modified": None,
        "width": 32,
        "height": 24,
        "bytes": len(content),
        "created_by": USER,
        "uploaded_at": "2026-10-19T00:00:00Z",
        "lifecycle_version": 1,
    }
    state = {"rows": [row], "downloads": 0, "reads": 0, "changed": False}

    class Store:
        def call(self, method, path, params):
            state["reads"] += 1
            assert params["trashed_at"] == "is.null" and params["purging_at"] == "is.null"
            return [
                {**r, "lifecycle_version": 2} if state["changed"] and state["reads"] % 2 == 0 else r
                for r in state["rows"]
            ]

    class Files:
        def download(self, path):
            state["downloads"] += 1
            assert path == f"{SPACE}/{photo_id}.webp"
            return content

    app = create_app(CONFIG)
    app.dependency_overrides[require_data] = lambda: Store()
    app.dependency_overrides[require_storage] = lambda: Files()
    with TestClient(app) as client:
        result = client.post("/photos/export", json={"ids": [photo_id]})
        assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert archive.namelist() == [f"photos/{photo_id}.webp", "manifest.json"]
            manifest = json.loads(archive.read("manifest.json"))
            info = manifest["photos"][0]
            image = archive.read(info["archive_path"])
            assert hashlib.sha256(image).hexdigest() == info["archive_sha256"]
            assert len(image) == info["archive_bytes"]
            assert b"private-gps" not in image and b"EXIF" not in image
            assert info["filename"] == "../../private.jpg" and "couple_id" not in info
        state["changed"] = True
        assert client.post("/photos/export", json={"ids": [photo_id]}).status_code == 409
        state["rows"] = []
        downloads = state["downloads"]
        assert client.post("/photos/export", json={"ids": [photo_id]}).status_code == 404
        assert state["downloads"] == downloads
        for ids in ([photo_id, photo_id], [], [str(uuid4()) for _ in range(21)]):
            assert client.post("/photos/export", json={"ids": ids}).status_code == 422
        assert client.post("/photos/export", content=b"x" * 4097).status_code == 413
    with TestClient(create_app(CONFIG)) as client:
        assert client.post("/photos/export", json={"ids": [photo_id]}).status_code == 401
