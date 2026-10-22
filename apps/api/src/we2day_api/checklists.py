from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["checklists"])
UUID_PATTERN = r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$"


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    title: str = Field(min_length=1, max_length=100)
    quantity: str = Field(max_length=100)
    done: bool

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value


class ChecklistContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    note: str = Field(max_length=1000)
    items: list[ChecklistItem] = Field(max_length=50)
    archived: bool

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        return ChecklistItem.nonblank(value)

    @field_validator("items")
    @classmethod
    def unique_ids(cls, value):
        if len({item.id.lower() for item in value}) != len(value):
            raise ValueError("Item IDs must be unique")
        return value


class ChecklistChange(ChecklistContent):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=UUID_PATTERN)


class Checklist(ChecklistContent):
    model_config = ConfigDict(extra="ignore", strict=False)
    id: UUID
    version: int
    updated_by: UUID
    updated_at: datetime


SELECT = "id,title,note,items,archived,version,updated_by,updated_at"


@router.get("/checklists", response_model=list[Checklist])
def list_checklists(store: Store, archived: bool = False, offset: int = Query(0, ge=0, le=100000)):
    return store.call(
        "GET",
        "shared_checklists",
        params={
            "select": SELECT,
            "archived": f"eq.{str(archived).lower()}",
            "order": "updated_at.desc,id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.get("/checklists/{id}", response_model=Checklist)
def read_checklist(id: UUID, store: Store):
    rows = store.call(
        "GET",
        "shared_checklists",
        params={
            "select": SELECT,
            "id": f"eq.{id}",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(404, "checklist_not_found")
    return rows[0]


@router.post("/checklists/{id}", response_model=Checklist)
def save_checklist(id: UUID, body: ChecklistChange, store: Store):
    return store.rpc(
        "save_checklist",
        {
            "p_id": str(id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )[0]
