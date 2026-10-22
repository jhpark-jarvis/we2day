from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Store
from we2day_api.plans import PlanContent

router = APIRouter(tags=["date-reports"])


class ReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=2000)
    visits: list[str] = Field(default_factory=list, max_length=20)
    actual_cost: int | None = Field(default=None, ge=0, le=1_000_000_000)
    highlights: str = Field(default="", max_length=2000)
    next_time: str = Field(default="", max_length=2000)
    revisit: bool | None = None

    @field_validator("summary")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A summary is required")
        return value

    @field_validator("visits")
    @classmethod
    def valid_visits(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Invalid visit")
        return values


class ReportChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: ReportContent
    shared: bool = False
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class Report(BaseModel):
    plan_id: UUID
    author_id: UUID
    observed_plan_version: int
    plan_snapshot: PlanContent
    content: ReportContent
    shared: bool
    version: int
    updated_at: datetime


SELECT = "plan_id,author_id,observed_plan_version,plan_snapshot,content,shared,version,updated_at"


@router.get("/reports/{plan_id}", response_model=list[Report])
def read_reports(plan_id: UUID, store: Store):
    return store.call(
        "GET",
        "date_reports",
        params={
            "select": SELECT,
            "plan_id": f"eq.{plan_id}",
            "order": "author_id.asc",
            "limit": "2",
        },
    )


@router.post("/reports/{plan_id}", response_model=Report)
def save_report(plan_id: UUID, body: ReportChange, store: Store):
    rows = store.rpc(
        "save_date_report",
        {
            "p_plan_id": str(plan_id),
            **{f"p_{key}": value for key, value in body.model_dump(mode="json").items()},
        },
    )
    return rows[0]
