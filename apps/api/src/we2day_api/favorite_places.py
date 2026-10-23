"""Explicitly saved couple destinations, independent of provider search responses."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["favorite-places"])


class FavoriteContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=200)
    archived: bool = False

    @field_validator("label", "destination")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid destination text")
        return value.strip()


class FavoriteChange(FavoriteContent):
    expected_version: int = Field(ge=0, le=2147483646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class Favorite(FavoriteContent):
    model_config = ConfigDict(extra="ignore", strict=False)
    id: UUID
    version: int
    updated_by: UUID
    updated_at: datetime


class FavoritePage(BaseModel):
    items: list[Favorite] = Field(max_length=50)
    next_offset: int | None


async def read_change(request: Request) -> FavoriteChange:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "invalid_favorite_place")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 2048:
            raise HTTPException(413, "invalid_favorite_place")
        content.extend(chunk)
    try:
        return FavoriteChange.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(422, "invalid_favorite_place") from error


@router.get("/favorite-places", response_model=FavoritePage)
def list_favorites(store: Store, archived: bool = False, offset: int = Query(0, ge=0, le=100000)):
    rows = store.call(
        "GET",
        "favorite_places",
        params={
            "select": "id,label,destination,archived,version,updated_by,updated_at",
            "archived": f"eq.{str(archived).lower()}",
            "order": "label.asc,id.asc",
            "offset": str(offset),
            "limit": "51",
        },
    )
    return {"items": rows[:50], "next_offset": offset + 50 if len(rows) > 50 else None}


@router.post("/favorite-places/{id}", response_model=Favorite)
def save_favorite(id: UUID, store: Store, body: Annotated[FavoriteChange, Depends(read_change)]):
    return store.rpc(
        "save_favorite_place",
        {
            "p_id": str(id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )[0]
