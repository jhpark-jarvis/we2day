from datetime import date as Date
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from we2day_api.photos import Store

router = APIRouter(tags=["photo-search"])


class PhotoSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    end_date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    query: str = Field(default="", max_length=100)
    offset: int = Field(default=0, ge=0, le=100000)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid query")
        return value.strip()

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Search range must contain at most 366 days")
        return self


class PhotoSearchHit(BaseModel):
    id: UUID
    date: Date
    caption: str


class PhotoSearchPage(BaseModel):
    items: list[PhotoSearchHit] = Field(max_length=50)
    next_offset: int | None


async def read_search(request: Request) -> PhotoSearchInput:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "invalid_photo_search")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 4096:
            raise HTTPException(413, "invalid_photo_search")
        content.extend(chunk)
    try:
        return PhotoSearchInput.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(422, "invalid_photo_search") from error


@router.post("/photos/search", response_model=PhotoSearchPage)
def search_photos(body: Annotated[PhotoSearchInput, Depends(read_search)], store: Store):
    rows = store.rpc(
        "search_photos",
        {
            "p_start": body.start_date.isoformat(),
            "p_end": body.end_date.isoformat(),
            "p_query": body.query,
            "p_offset": body.offset,
        },
    )
    return {
        "items": rows[:50],
        "next_offset": body.offset + 50 if len(rows) > 50 and body.offset + 50 <= 100000 else None,
    }
