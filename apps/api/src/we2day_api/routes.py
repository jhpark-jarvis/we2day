from datetime import date as Date
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from we2day_api.anniversaries import seoul_today
from we2day_api.calendar import Store

router = APIRouter(tags=["meeting-routes"])


class RouteContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_name: str = Field(min_length=1, max_length=100)
    start_lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    start_lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    end_name: str = Field(min_length=1, max_length=100)
    end_lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    end_lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class RouteInput(RouteContent):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class MeetingRoute(RouteContent):
    model_config = ConfigDict(extra="ignore", strict=False)
    date: Date
    version: int
    updated_by: UUID
    updated_at: datetime


@router.get("/routes", response_model=list[MeetingRoute])
def read_route(date: Date, store: Store):
    return store.call(
        "GET",
        "meeting_routes",
        params={
            "select": (
                "date,start_name,start_lat,start_lng,end_name,end_lat,end_lng,"
                "version,updated_by,updated_at"
            ),
            "date": f"eq.{date}",
            "limit": "1",
        },
    )


@router.post("/routes/{date}", response_model=MeetingRoute)
def save_route(date: Date, body: RouteInput, store: Store):
    if not Date(2000, 1, 1) <= date <= min(seoul_today(), Date(2100, 12, 31)):
        raise HTTPException(422, "invalid_route")
    values = body.model_dump(mode="json")
    return store.rpc(
        "save_meeting_route",
        {"p_date": str(date), **{f"p_{key}": value for key, value in values.items()}},
    )[0]
