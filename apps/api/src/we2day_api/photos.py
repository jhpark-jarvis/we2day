import base64
import binascii
import hashlib
import io
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date
from datetime import datetime
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from we2day_api.auth import CurrentUser, bearer, require_user, unauthenticated
from we2day_api.calendar_export import Month
from we2day_api.data import DataAPI, require_data
from we2day_api.timing import timed
from we2day_api.upstream import upstream_transport

router = APIRouter(tags=["photos"])
Store = Annotated[DataAPI, Depends(require_data)]
BUCKET = "we2day-photos"
MAX_BYTES = 1024 * 1024
MAX_BODY = 1_410_000
PUBLIC_FIELDS = (
    "id,date,caption,filename,device,captured_at,file_modified,"
    "width,height,bytes,created_by,uploaded_at,trashed_at,trashed_by,purge_after,purging_at,"
    "lifecycle_version"
)


class PhotoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    request_id: UUID
    caption: str = Field(default="", max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    device: str | None = Field(default=None, max_length=255)
    captured_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    file_modified: datetime | None = None
    image: str = Field(min_length=1, max_length=1_398_104)

    @field_validator("filename", "device", "caption")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127).strip()
        if not cleaned and value:
            raise ValueError("Invalid text")
        return cleaned

    @field_validator("file_modified")
    @classmethod
    def timestamp_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value

    @field_validator("captured_at")
    @classmethod
    def capture_time(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


class Photo(BaseModel):
    id: UUID
    date: Date
    caption: str
    filename: str
    device: str | None
    captured_at: str | None
    file_modified: datetime | None
    width: int
    height: int
    bytes: int
    created_by: UUID
    uploaded_at: datetime
    trashed_at: datetime | None = None
    trashed_by: UUID | None = None
    purge_after: datetime | None = None
    purging_at: datetime | None = None
    lifecycle_version: int = 1


class PhotoAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, le=2_147_483_646)
    request_id: UUID
    confirmation: str = Field(default="", max_length=20)


class PhotoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    caption: str = Field(max_length=500)
    expected_version: int = Field(ge=1, le=2_147_483_646)
    request_id: UUID

    @field_validator("caption")
    @classmethod
    def clean_caption(cls, value: str) -> str:
        return PhotoInput.clean_text(value)


@router.post("/photos/{photo_id}/metadata", response_model=Photo)
def edit_photo(photo_id: UUID, body: PhotoMetadata, store: Store):
    return store.rpc(
        "edit_photo",
        {
            "p_id": str(photo_id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )[0]


class PhotoPage(BaseModel):
    items: list[Photo]
    next_after: UUID | None


class AlbumDate(BaseModel):
    date: Date
    count: int = Field(ge=1)


class AlbumDates(BaseModel):
    month: str
    days: list[AlbumDate] = Field(max_length=31)


@router.get("/photos/dates", response_model=AlbumDates)
def album_dates(store: Store, month: Month):
    return {"month": month, "days": store.rpc("photo_album_dates", {"p_month": f"{month}-01"})}


_image_processing = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo-processing")


@timed("image")
def normalized_image(
    content: bytes, *, allow_jpeg: bool = False, thumbnail: bool = False
) -> tuple[bytes, int, int]:
    # Decoding multiple 1600px photos can exceed a small server's memory limit.
    # Reuse one worker so per-thread pixel allocators cannot accumulate either.
    # Upload, display and export share this process-owned worker; no local file cache.
    return _image_processing.submit(
        _normalized_image, content, allow_jpeg=allow_jpeg, thumbnail=thumbnail
    ).result()


def _normalized_image(
    content: bytes, *, allow_jpeg: bool, thumbnail: bool
) -> tuple[bytes, int, int]:
    """Bound decoding before loading pixels; never retain uploaded EXIF/ICC/XMP."""
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(422, "invalid_photo")
    try:
        with Image.open(
            io.BytesIO(content), formats=["WEBP", "JPEG"] if allow_jpeg else ["WEBP"]
        ) as image:
            width, height = image.size
            if (
                not 1 <= width <= 1600
                or not 1 <= height <= 1600
                or getattr(image, "n_frames", 1) != 1
            ):
                raise HTTPException(422, "invalid_photo")
            image.load()
            # A fresh image strips metadata, including decoded image.info inherited by convert().
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            if thumbnail:
                image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            width, height = image.size
            with Image.new(mode, image.size) as clean:
                clean.paste(image)
                output = io.BytesIO()
                clean.save(output, format="WEBP", quality=82, method=4)
                result = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "invalid_photo") from error
    if len(result) > MAX_BYTES:
        raise HTTPException(422, "invalid_photo")
    return result, width, height


def _checked_preview(content: bytes) -> tuple[int, int]:
    # Only canonical single-image WebP chunks; no EXIF/XMP/ICC, trailing bytes or animation.
    if (
        len(content) < 20
        or len(content) > MAX_BYTES
        or content[:4] != b"RIFF"
        or content[8:12] != b"WEBP"
    ):
        raise HTTPException(422, "invalid_photo")
    if int.from_bytes(content[4:8], "little") + 8 != len(content):
        raise HTTPException(422, "invalid_photo")
    offset = 12
    while offset < len(content):
        if offset + 8 > len(content) or content[offset : offset + 4] not in {
            b"VP8 ",
            b"VP8L",
            b"VP8X",
            b"ALPH",
        }:
            raise HTTPException(422, "invalid_photo")
        length = int.from_bytes(content[offset + 4 : offset + 8], "little")
        offset += 8 + length + (length % 2)
    if offset != len(content):
        raise HTTPException(422, "invalid_photo")
    try:
        with Image.open(io.BytesIO(content), formats=["WEBP"]) as image:
            if (
                not (1 <= image.width <= 640 and 1 <= image.height <= 640)
                or image.n_frames != 1
                or any(k in image.info for k in ["exif", "xmp", "icc_profile"])
            ):
                raise HTTPException(422, "invalid_photo")
            image.load()
            return image.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "invalid_photo") from error


@timed("image")
def checked_preview(content: bytes) -> tuple[int, int]:
    return _image_processing.submit(_checked_preview, content).result()


def remember_preview(
    row: dict, content: bytes, width: int, height: int, store: DataAPI, files: "PhotoStorage"
) -> None:
    path = f"{UUID(row['couple_id'])}/{UUID(row['id'])}.preview.webp"
    if not files.upload(path, content):
        # Validate the actual immutable object after a concurrent or direct upload.
        content = files.download(path)
        width, height = checked_preview(content)
    store.rpc(
        "complete_photo_preview",
        {
            "p_id": str(row["id"]),
            "p_sha256": hashlib.sha256(content).hexdigest(),
            "p_bytes": len(content),
            "p_width": width,
            "p_height": height,
        },
    )


def optional_preview(row: dict, content: bytes, store: DataAPI, files: "PhotoStorage") -> None:
    try:
        preview, width, height = normalized_image(content, thumbnail=True)
        remember_preview(row, preview, width, height, store, files)
    except HTTPException as error:
        if error.status_code == 401:
            raise
        # The durable original remains saved even if optional preview creation fails.


class PhotoStorage:
    def __init__(self, transport: httpx.Client):
        self.transport = transport

    @timed("storage")
    def upload(self, path: str, content: bytes) -> bool:
        try:
            response = self.transport.post(
                f"object/{BUCKET}/{path}",
                content=content,
                headers={"Content-Type": "image/webp", "x-upsert": "false", "cache-control": "0"},
            )
        except httpx.HTTPError as error:
            raise HTTPException(503, "Photo service unavailable") from error
        if response.is_success:
            return True
        # Storage versions may report duplicate as 400 or 409. Never overwrite it.
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code == 409 or (
            response.status_code == 400 and body.get("error") == "Duplicate"
        ):
            return False
        if response.status_code == 401:
            raise unauthenticated()
        raise HTTPException(503, "Photo service unavailable")

    @timed("storage")
    def download(self, path: str) -> bytes:
        try:
            with self.transport.stream("GET", f"object/authenticated/{BUCKET}/{path}") as response:
                if response.status_code == 401:
                    raise unauthenticated()
                if not response.is_success:
                    raise HTTPException(503, "Photo service unavailable")
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > MAX_BYTES:
                        raise HTTPException(422, "invalid_photo")
                return bytes(result)
        except httpx.HTTPError as error:
            raise HTTPException(503, "Photo service unavailable") from error

    @timed("storage")
    def remove(self, path: str) -> None:
        try:
            response = self.transport.request(
                "DELETE", f"object/{BUCKET}", json={"prefixes": [path]}
            )
        except httpx.HTTPError as error:
            raise HTTPException(503, "Photo service unavailable") from error
        if response.status_code == 401:
            raise unauthenticated()
        if not response.is_success:
            raise HTTPException(503, "Photo service unavailable")


def require_storage(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_user)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> Iterator[PhotoStorage]:
    config = request.app.state.settings
    with httpx.Client(
        transport=upstream_transport(request),
        base_url=f"{config.supabase_url.rstrip('/')}/storage/v1/",
        headers={
            "apikey": config.supabase_publishable_key,
            "Authorization": f"Bearer {credentials.credentials}",
        },
        timeout=15.0,
    ) as transport:
        yield PhotoStorage(transport)


Files = Annotated[PhotoStorage, Depends(require_storage)]


def save_photo(body: PhotoInput, store: DataAPI, files: PhotoStorage) -> dict:
    try:
        raw = base64.b64decode(body.image, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, "invalid_photo") from error
    content, width, height = normalized_image(raw, allow_jpeg=True)
    digest = hashlib.sha256(content).hexdigest()
    fields = {
        f"p_{key}": value for key, value in body.model_dump(mode="json").items() if key != "image"
    }
    row = store.rpc(
        "reserve_photo",
        {
            **fields,
            "p_width": width,
            "p_height": height,
            "p_bytes": len(content),
            "p_sha256": digest,
        },
    )[0]
    if row.get("trashed_at") or row.get("purging_at"):
        raise HTTPException(409, "photo_state_conflict")
    if row["uploaded_at"] is not None:
        return row
    path = f"{UUID(row['couple_id'])}/{UUID(row['id'])}.webp"
    if not files.upload(path, content):
        existing = files.download(path)
        if hashlib.sha256(existing).hexdigest() != digest:
            raise HTTPException(409, "request_conflict")
    completed = store.rpc("complete_photo", {"p_id": row["id"]})[0]
    optional_preview(row, content, store, files)
    return completed


@router.post("/photos", response_model=Photo, status_code=201)
async def upload_photo(request: Request, store: Store, files: Files):
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_BODY:
            raise HTTPException(413, "Photo request too large")
    try:
        body = PhotoInput.model_validate_json(payload)
    except (ValidationError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(422, "invalid_photo") from error
    return await run_in_threadpool(save_photo, body, store, files)


@router.get("/photos", response_model=PhotoPage)
def list_photos(
    store: Store,
    date: Annotated[Date | None, Query(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))] = None,
    after: UUID | None = None,
    trash: bool = False,
):
    if not trash and date is None:
        raise HTTPException(422, "invalid_photo")
    params = {
        "select": PUBLIC_FIELDS,
        "uploaded_at": "not.is.null",
        "trashed_at": "not.is.null" if trash else "is.null",
        "order": "id.asc",
        "limit": "51",
    }
    if date is not None:
        params["date"] = f"eq.{date}"
    if not trash:
        params["purging_at"] = "is.null"
    if after:
        params["id"] = f"gt.{after}"
    rows = store.call("GET", "photos", params=params)
    return {"items": rows[:50], "next_after": rows[49]["id"] if len(rows) > 50 else None}


@router.get("/photos/{photo_id}/image")
def photo_image(
    photo_id: UUID, store: Store, files: Files, trash: bool = False, thumbnail: bool = False
):
    rows = store.call(
        "GET",
        "photos",
        params={
            "select": (
                "id,couple_id,sha256,preview_sha256,preview_bytes,preview_width,preview_height"
            ),
            "id": f"eq.{photo_id}",
            "uploaded_at": "not.is.null",
            "trashed_at": "not.is.null" if trash else "is.null",
            "purging_at": "is.null",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(404, "photo_not_found")
    row = rows[0]
    clean = None
    if thumbnail and row.get("preview_sha256"):
        try:
            preview = files.download(f"{UUID(row['couple_id'])}/{photo_id}.preview.webp")
            if hashlib.sha256(preview).hexdigest() == row["preview_sha256"]:
                dimensions = checked_preview(preview)
                if (
                    dimensions == (row["preview_width"], row["preview_height"])
                    and len(preview) == row["preview_bytes"]
                ):
                    clean = preview
        except HTTPException as error:
            if error.status_code == 401:
                raise
    if clean is None:
        content = files.download(f"{UUID(row['couple_id'])}/{photo_id}.webp")
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise HTTPException(409, "photo_upload_incomplete")
        clean, width, height = normalized_image(content, thumbnail=thumbnail)
        if thumbnail and not trash:
            try:
                remember_preview(row, clean, width, height, store, files)
            except HTTPException as error:
                if error.status_code == 401:
                    raise
    return Response(
        clean,
        media_type="image/webp",
        headers={
            "Content-Disposition": f'inline; filename="we2day-{photo_id}.webp"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


def change_photo(photo_id: UUID, action: str, body: PhotoAction, store: DataAPI):
    return store.rpc(
        "change_photo_lifecycle",
        {
            "p_id": str(photo_id),
            "p_action": action,
            "p_expected_version": body.expected_version,
            "p_request_id": str(body.request_id),
            "p_confirmation": body.confirmation,
        },
    )[0]


@router.post("/photos/{photo_id}/trash", response_model=Photo)
def trash_photo(photo_id: UUID, body: PhotoAction, store: Store):
    return change_photo(photo_id, "trash", body, store)


@router.post("/photos/{photo_id}/restore", response_model=Photo)
def restore_photo(photo_id: UUID, body: PhotoAction, store: Store):
    return change_photo(photo_id, "restore", body, store)


@router.post("/photos/{photo_id}/purge", status_code=204)
def purge_photo(photo_id: UUID, body: PhotoAction, store: Store, files: Files):
    if body.confirmation != "영구 삭제":
        raise HTTPException(422, "photo_confirmation_required")
    try:
        row = change_photo(photo_id, "purge", body, store)
    except HTTPException as error:
        if error.status_code == 404 and error.detail == "photo_not_found":
            return Response(status_code=204)
        raise
    files.remove(f"{UUID(row['couple_id'])}/{UUID(row['id'])}.webp")
    files.remove(f"{UUID(row['couple_id'])}/{UUID(row['id'])}.preview.webp")
    try:
        store.rpc("finish_photo_purge", {"p_id": str(photo_id)})
    except HTTPException as error:
        if error.status_code != 404 or error.detail != "photo_not_found":
            raise
    return Response(status_code=204)
