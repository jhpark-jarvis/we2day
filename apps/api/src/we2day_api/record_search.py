from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["record-search"])


class SearchInput(BaseModel):
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


async def read_search_input[SearchModel: SearchInput](
    request: Request, model: type[SearchModel], detail: str
) -> SearchModel:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, detail)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 4096:
            raise HTTPException(413, detail)
        content.extend(chunk)
    try:
        return model.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(422, detail) from error


class ReferenceSearchInput(SearchInput):
    field: Literal["caption", "filename", "device"] = "caption"
    uploader: Literal["all", "mine", "partner"] = "all"


class PhotoReferenceHit(BaseModel):
    id: UUID
    date: Date
    caption: str
    filename: str
    device: str | None
    captured_at: str | None
    uploaded_at: datetime
    uploaded_by_me: bool


class PhotoReferencePage(BaseModel):
    items: list[PhotoReferenceHit] = Field(max_length=50)
    next_offset: int | None


async def read_reference_search(request: Request) -> ReferenceSearchInput:
    return await read_search_input(request, ReferenceSearchInput, "invalid_photo_search")


@router.post("/photos/reference-search", response_model=PhotoReferencePage)
def search_photo_references(
    body: Annotated[ReferenceSearchInput, Depends(read_reference_search)], store: Store
):
    rows = store.rpc(
        "search_photo_references",
        {
            "p_start": body.start_date.isoformat(),
            "p_end": body.end_date.isoformat(),
            "p_query": body.query,
            "p_field": body.field,
            "p_uploader": body.uploader,
            "p_offset": body.offset,
        },
    )
    return {
        "items": rows[:50],
        "next_offset": body.offset + 50 if len(rows) > 50 and body.offset + 50 <= 100000 else None,
    }


class QuestionSearchHit(BaseModel):
    id: UUID
    date: Date
    prompt: str


class QuestionSearchPage(BaseModel):
    items: list[QuestionSearchHit] = Field(max_length=50)
    next_offset: int | None


async def read_question_search(request: Request) -> SearchInput:
    return await read_search_input(request, SearchInput, "invalid_question_search")


# Register this router before the questions/{id} router; "search" is not a UUID.
@router.post("/questions/search", response_model=QuestionSearchPage)
def search_questions(body: Annotated[SearchInput, Depends(read_question_search)], store: Store):
    rows = store.rpc(
        "search_questions",
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


class RecordSearchInput(SearchInput):
    kind: Literal["appointment", "plan", "report", "wish"]
    include_archived: bool = False


class RecordHit(BaseModel):
    id: UUID
    date: Date
    title: str
    excerpt: str
    state: str
    visibility: str | None


class RecordPage(BaseModel):
    items: list[RecordHit] = Field(max_length=50)
    next_offset: int | None


async def read_records(request: Request) -> RecordSearchInput:
    return await read_search_input(request, RecordSearchInput, "invalid_record_search")


@router.post("/records/search", response_model=RecordPage)
def search_records(body: Annotated[RecordSearchInput, Depends(read_records)], store: Store):
    rows = store.rpc(
        "search_records",
        {
            "p_kind": body.kind,
            "p_start": body.start_date.isoformat(),
            "p_end": body.end_date.isoformat(),
            "p_query": body.query,
            "p_archived": body.include_archived,
            "p_offset": body.offset,
        },
    )
    return {
        "items": rows[:50],
        "next_offset": body.offset + 50 if len(rows) > 50 and body.offset + 50 <= 100000 else None,
    }
