from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["roulette"])


class DrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1, le=2_147_483_647)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class WheelChange(DrawRequest):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    title: str = Field(min_length=1, max_length=100)
    candidates: list[str] = Field(min_length=2, max_length=20)
    archived: bool

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value.strip()

    @field_validator("candidates")
    @classmethod
    def valid_candidates(cls, values):
        values = [v.strip() for v in values]
        if len(set(values)) != len(values) or any(not v or len(v) > 100 for v in values):
            raise ValueError("Use unique nonempty candidates, at most 100 characters each")
        return values


class Wheel(BaseModel):
    id: UUID
    title: str
    candidates: list[str]
    archived: bool
    version: int
    updated_by: UUID
    updated_at: datetime


class RouletteDraw(BaseModel):
    id: UUID
    wheel_id: UUID
    wheel_version: int
    candidates: list[str]
    selected_index: int
    drawn_by: UUID
    drawn_at: datetime


FIELDS = "id,title,candidates,archived,version,updated_by,updated_at"


@router.get("/roulette", response_model=list[Wheel])
def list_wheels(store: Store, archived: bool = False, offset: int = Query(0, ge=0, le=100000)):
    return store.call(
        "GET",
        "roulette_wheels",
        params={
            "select": FIELDS,
            "archived": f"eq.{str(archived).lower()}",
            "order": "updated_at.desc,id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.get("/roulette/{id}", response_model=Wheel)
def read_wheel(id: UUID, store: Store):
    rows = store.call(
        "GET",
        "roulette_wheels",
        params={
            "select": FIELDS,
            "id": f"eq.{id}",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(404, "roulette_not_found")
    return rows[0]


@router.post("/roulette/{id}", response_model=Wheel)
def save_wheel(id: UUID, body: WheelChange, store: Store):
    return store.rpc(
        "save_roulette",
        {
            "p_id": str(id),
            **{f"p_{k}": v for k, v in body.model_dump(mode="json").items()},
        },
    )[0]


@router.get("/roulette/{id}/draws", response_model=list[RouletteDraw])
def read_draws(id: UUID, store: Store, offset: int = Query(0, ge=0, le=100000)):
    return store.call(
        "GET",
        "roulette_draws",
        params={
            "select": "id,wheel_id,wheel_version,candidates,selected_index,drawn_by,drawn_at",
            "wheel_id": f"eq.{id}",
            "order": "drawn_at.desc,id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.post("/roulette/{id}/draws", response_model=RouletteDraw)
def draw(id: UUID, body: DrawRequest, store: Store):
    return store.rpc(
        "draw_roulette",
        {
            "p_wheel_id": str(id),
            **{f"p_{k}": v for k, v in body.model_dump(mode="json").items()},
        },
    )[0]
