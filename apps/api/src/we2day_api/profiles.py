from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.auth import CurrentUser, require_user
from we2day_api.calendar import Store

router = APIRouter(tags=["profiles"])
User = Annotated[CurrentUser, Depends(require_user)]
FIELDS = "user_id,display_name,version,updated_at"


class Profile(BaseModel):
    user_id: UUID
    display_name: str
    version: int
    updated_at: datetime


class ProfileView(BaseModel):
    mine: Profile | None
    partner: Profile | None


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=40)
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        if (
            not value.strip()
            or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Invalid name")
        return value


@router.get("/profiles", response_model=ProfileView)
def read_profiles(store: Store, user: User):
    rows = store.call(
        "GET", "user_profiles", params={"select": FIELDS, "order": "user_id.asc", "limit": "2"}
    )
    return {
        "mine": next((p for p in rows if p["user_id"] == str(user.id)), None),
        "partner": next((p for p in rows if p["user_id"] != str(user.id)), None),
    }


@router.post("/profiles", response_model=Profile)
def save_profile(body: ProfileChange, store: Store):
    return store.rpc(
        "save_profile", {f"p_{k}": v for k, v in body.model_dump(mode="json").items()}
    )[0]
