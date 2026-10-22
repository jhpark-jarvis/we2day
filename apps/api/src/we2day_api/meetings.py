import calendar
from datetime import date as Date
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from we2day_api.anniversaries import seoul_today
from we2day_api.calendar import Store

router = APIRouter(tags=["meeting-days"])


class MeetingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    met: bool
    note: str = Field(default="", max_length=2000)
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class MeetingDay(BaseModel):
    date: Date
    met: bool
    note: str
    version: int
    updated_by: UUID
    updated_at: datetime


@router.get("/meetings", response_model=list[MeetingDay])
def list_meetings(
    store: Store,
    month: Annotated[str, Query(pattern=r"^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$")],
):
    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    return store.call(
        "GET",
        "meeting_days",
        params={
            "select": "date,met,note,version,updated_by,updated_at",
            "and": f"(date.gte.{month}-01,date.lte.{month}-{last_day:02})",
            "order": "date.asc",
            "limit": "31",
        },
    )


@router.post("/meetings/{date}", response_model=MeetingDay)
def save_meeting(date: Date, body: MeetingInput, store: Store):
    if not Date(2000, 1, 1) <= date <= min(seoul_today(), Date(2100, 12, 31)):
        raise HTTPException(422, "invalid_meeting_day")
    return store.rpc(
        "save_meeting_day",
        {
            "p_date": str(date),
            "p_met": body.met,
            "p_note": body.note,
            "p_expected_version": body.expected_version,
            "p_request_id": body.request_id,
        },
    )[0]
