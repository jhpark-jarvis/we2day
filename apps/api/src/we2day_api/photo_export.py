import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from we2day_api.photos import PUBLIC_FIELDS, Files, Photo, PhotoStorage, Store, normalized_image

router = APIRouter(tags=["photos"])


class PhotoExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate photo")
        return value


def export_photos(body: PhotoExportInput, store, files: PhotoStorage) -> bytes:
    ids = [str(value) for value in body.ids]
    params = {
        "select": f"{PUBLIC_FIELDS},couple_id,sha256",
        "id": f"in.({','.join(ids)})",
        "uploaded_at": "not.is.null",
        "trashed_at": "is.null",
        "purging_at": "is.null",
    }
    rows = store.call("GET", "photos", params=params)
    by_id = {str(row["id"]): row for row in rows}
    if set(by_id) != set(ids):
        raise HTTPException(404, "photo_not_found")
    output = io.BytesIO()
    manifest = {
        "format": "we2day-photo-export",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "photos": [],
    }
    total = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for photo_id in ids:
            row = by_id[photo_id]
            content = files.download(f"{UUID(row['couple_id'])}/{UUID(photo_id)}.webp")
            if hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise HTTPException(409, "photo_upload_incomplete")
            clean, _, _ = normalized_image(content)
            total += len(clean)
            if total > 20 * 1024 * 1024:
                raise HTTPException(413, "Photo export too large")
            # Original filenames remain reference data, never ZIP paths.
            path = f"photos/{UUID(photo_id)}.webp"
            archive.writestr(path, clean)
            manifest["photos"].append(
                {
                    **Photo.model_validate(row).model_dump(mode="json"),
                    "archive_path": path,
                    "archive_bytes": len(clean),
                    "archive_sha256": hashlib.sha256(clean).hexdigest(),
                }
            )
        # Recheck membership and lifecycle after file reads; never silently export a subset.
        current = store.call("GET", "photos", params=params)
        versions = {str(row["id"]): (row["lifecycle_version"], row["sha256"]) for row in current}
        if versions != {
            key: (row["lifecycle_version"], row["sha256"]) for key, row in by_id.items()
        }:
            raise HTTPException(409, "photo_state_conflict")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return output.getvalue()


@router.post("/photos/export")
async def photo_export(request: Request, store: Store, files: Files):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 4096:
            raise HTTPException(413, "Photo export request too large")
    try:
        body = PhotoExportInput.model_validate_json(content)
    except (ValidationError, ValueError) as error:
        raise HTTPException(422, "invalid_photo_export") from error
    archive = await run_in_threadpool(export_photos, body, store, files)
    return Response(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="we2day-photos.zip"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
