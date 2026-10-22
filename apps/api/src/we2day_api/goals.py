from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["goals"])
UUID_PATTERN = r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$"


class GoalStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    title: str = Field(min_length=1, max_length=100)
    done: bool

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value


class GoalContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    target_date: date | None = None
    steps: list[GoalStep] = Field(max_length=50)
    completed: bool
    archived: bool

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        return GoalStep.nonblank(value)

    @field_validator("target_date", mode="before")
    @classmethod
    def valid_date(cls, value):
        if value is None:
            return value
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("Use YYYY-MM-DD")
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= date(2100, 12, 31):
            raise ValueError("Date outside supported range")
        return parsed

    @field_validator("steps")
    @classmethod
    def unique_ids(cls, value):
        if len({step.id.lower() for step in value}) != len(value):
            raise ValueError("Step IDs must be unique")
        return value


class GoalChange(GoalContent):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=UUID_PATTERN)


class Goal(GoalContent):
    model_config = ConfigDict(extra="ignore", strict=False)
    id: UUID
    version: int
    updated_by: UUID
    updated_at: datetime


SELECT = "id,title,target_date,steps,completed,archived,version,updated_by,updated_at"


@router.get("/goals", response_model=list[Goal])
def list_goals(store: Store, archived: bool = False, offset: int = Query(0, ge=0, le=100000)):
    return store.call(
        "GET",
        "shared_goals",
        params={
            "select": SELECT,
            "archived": f"eq.{str(archived).lower()}",
            "order": "updated_at.desc,id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.get("/goals/{id}", response_model=Goal)
def read_goal(id: UUID, store: Store):
    rows = store.call(
        "GET",
        "shared_goals",
        params={
            "select": SELECT,
            "id": f"eq.{id}",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(404, "goal_not_found")
    return rows[0]


@router.post("/goals/{id}", response_model=Goal)
def save_goal(id: UUID, body: GoalChange, store: Store):
    return store.rpc(
        "save_goal",
        {
            "p_id": str(id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )[0]
