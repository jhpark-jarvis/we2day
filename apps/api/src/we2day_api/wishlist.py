import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["wishlist"])


class WishContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["place", "activity"]
    note: str = Field(default="", max_length=1000)
    place: str = Field(default="", max_length=200)
    map_url: str = Field(default="", max_length=200)
    done: bool = False
    archived: bool = False

    @field_validator("map_url")
    @classmethod
    def map_link(cls, value):
        if value and not re.fullmatch(r"https://naver\.me/[A-Za-z0-9_-]{1,80}", value):
            raise ValueError("A NAVER map share link is required")
        return value

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value


class WishChange(WishContent):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class Wish(WishContent):
    model_config = ConfigDict(extra="ignore", strict=False)
    id: UUID
    version: int
    updated_by: UUID
    updated_at: datetime


SELECT = "id,title,kind,note,place,map_url,done,archived,version,updated_by,updated_at"


@router.get("/wishlist", response_model=list[Wish])
def list_wishes(store: Store, archived: bool = False, offset: int = Query(0, ge=0, le=100000)):
    return store.call(
        "GET",
        "wishes",
        params={
            "select": SELECT,
            "archived": f"eq.{str(archived).lower()}",
            "order": "updated_at.desc,id.asc",
            "offset": str(offset),
            "limit": "50",
        },
    )


@router.get("/wishlist/{id}", response_model=Wish)
def read_wish(id: UUID, store: Store):
    rows = store.call("GET", "wishes", params={"select": SELECT, "id": f"eq.{id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "wish_not_found")
    return rows[0]


@router.post("/wishlist/{id}", response_model=Wish)
def save_wish(id: UUID, body: WishChange, store: Store):
    located = bool({"place", "map_url"} & body.model_fields_set)
    content = body.model_dump(mode="json")
    if not located:
        content.pop("place")
        content.pop("map_url")
    return store.rpc(
        "save_wish_location" if located else "save_wish",
        {
            "p_id": str(id),
            **{f"p_{key}": value for key, value in content.items()},
        },
    )[0]
