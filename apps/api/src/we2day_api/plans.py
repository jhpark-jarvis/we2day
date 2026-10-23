from datetime import date as Date
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Appointment, Store

router = APIRouter(tags=["date-plans"])
Money = int | None


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    place: str = Field(default="", max_length=200)
    map_url: str = Field(default="", pattern=r"^(?:https://naver\.me/[A-Za-z0-9_-]{1,80})?$")
    cost: Money = Field(default=None, ge=0, le=1_000_000_000)
    note: str = Field(default="", max_length=1000)


class PlanContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    date: str = Field(pattern=r"^(20\d{2}|2100)-\d{2}-\d{2}$")
    budget: Money = Field(default=None, ge=0, le=1_000_000_000)
    transport: str = Field(default="", max_length=40)
    activities: list[Activity] = Field(default_factory=list, max_length=20)
    preparation: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        Date.fromisoformat(value)
        return value

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value

    @field_validator("preparation")
    @classmethod
    def valid_preparation(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Invalid preparation item")
        return values


class PlanChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["save", "confirm", "archive", "restore"]
    content: PlanContent | None = None
    expected_version: int = Field(ge=0, le=2_147_483_646)
    expected_appointment_version: int = Field(default=0, ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class Plan(BaseModel):
    id: UUID
    content: PlanContent
    published_content: PlanContent | None
    published_revision: int = 0
    appointment_id: UUID | None
    archived: bool
    version: int
    updated_by: UUID
    updated_at: datetime
    appointment: Appointment | None = None


SELECT = (
    "id,content,published_content,published_revision,appointment_id,archived,"
    "version,updated_by,updated_at,"
    "appointment:appointments(*)"
)


@router.get("/timeline", response_model=list[Plan])
def read_timeline(store: Store, date: Date, offset: int = Query(default=0, ge=0, le=100000)):
    if not 2000 <= date.year <= 2100:
        raise HTTPException(422, "invalid_plan")
    return store.call(
        "GET",
        "date_plans",
        params={
            "select": SELECT,
            "published_content->>date": f"eq.{date.isoformat()}",
            "archived": "eq.false",
            "order": "id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.get("/plans", response_model=list[Plan])
def list_plans(
    store: Store, archived: bool = False, offset: int = Query(default=0, ge=0, le=100000)
):
    return store.call(
        "GET",
        "date_plans",
        params={
            "select": SELECT,
            "archived": f"eq.{str(archived).lower()}",
            "order": "updated_at.desc,id.asc",
            "limit": "50",
            "offset": str(offset),
        },
    )


@router.get("/plans/{id}", response_model=Plan)
def read_plan(id: UUID, store: Store):
    rows = store.call(
        "GET", "date_plans", params={"select": SELECT, "id": f"eq.{id}", "limit": "1"}
    )
    if not rows:
        raise HTTPException(404, "plan_not_found")
    return rows[0]


@router.post("/plans/{id}", response_model=Plan)
def change_plan(id: UUID, body: PlanChange, store: Store):
    if (body.action == "save") != (body.content is not None):
        raise HTTPException(422, "invalid_plan")
    store.rpc(
        "change_date_plan",
        {
            "p_id": str(id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )
    return read_plan(id, store)
