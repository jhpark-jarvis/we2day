from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from we2day_api.calendar import Store
from we2day_api.plans import PlanContent, read_plan

router = APIRouter(tags=["visit-progress"])


class VisitChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publication: int = Field(ge=1, le=2_147_483_647)
    activity: int = Field(ge=0, le=19)
    state: Literal["planned", "visited", "skipped"]
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class VisitProgress(BaseModel):
    plan_id: UUID
    publication: int
    snapshot: PlanContent
    states: list[Literal["planned", "visited", "skipped"]] = Field(min_length=1, max_length=20)
    version: int
    updated_by: UUID
    updated_at: datetime


SELECT = "plan_id,publication,snapshot,states,version,updated_by,updated_at"


@router.get("/plans/{id}/visits", response_model=list[VisitProgress])
def read_visits(id: UUID, store: Store, offset: int = Query(0, ge=0, le=100000)):
    read_plan(id, store)
    return store.call(
        "GET",
        "plan_visit_progress",
        params={
            "select": SELECT,
            "plan_id": f"eq.{id}",
            "order": "publication.desc",
            "offset": str(offset),
            "limit": "20",
        },
    )


@router.post("/plans/{id}/visits", response_model=VisitProgress)
def change_visit(id: UUID, body: VisitChange, store: Store):
    return store.rpc(
        "change_visit_progress",
        {
            "p_plan_id": str(id),
            **{f"p_{k}": v for k, v in body.model_dump(mode="json").items()},
        },
    )[0]
