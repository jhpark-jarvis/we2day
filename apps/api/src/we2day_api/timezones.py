from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from we2day_api.auth import CurrentUser, require_user
from we2day_api.calendar import Store

User = Annotated[CurrentUser, Depends(require_user)]

router = APIRouter(tags=["timezones"])


class TimezonePreference(BaseModel):
    user_id: UUID
    timezone: str | None
    version: int
    updated_at: datetime


class TimezoneView(BaseModel):
    mine: TimezonePreference | None
    partner: TimezonePreference | None


class TimezoneChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    timezone: str | None = Field(max_length=64)
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


@router.get("/timezones", response_model=TimezoneView)
def read_timezones(store: Store, user: User):
    rows = store.call(
        "GET",
        "timezone_preferences",
        params={
            "select": "user_id,timezone,version,updated_at",
            "order": "user_id.asc",
            "limit": "2",
        },
    )
    return {
        "mine": next((p for p in rows if p["user_id"] == str(user.id)), None),
        "partner": next((p for p in rows if p["user_id"] != str(user.id)), None),
    }


@router.post("/timezones", response_model=TimezonePreference)
def save_timezone(body: TimezoneChange, store: Store):
    return store.rpc(
        "save_timezone", {f"p_{k}": v for k, v in body.model_dump(mode="json").items()}
    )[0]
