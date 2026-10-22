"""Gregorian originals stay in SQL; derived dates use the shared Seoul day."""

import calendar
from datetime import date as Date
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from we2day_api.calendar import Store

router = APIRouter(tags=["anniversaries"])


def seoul_today() -> Date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


class AnniversaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["relationship", "birthday", "custom"]
    title: str = Field(min_length=1, max_length=100)
    date: Date | None = Field(default=None, ge=Date(1900, 1, 1), le=Date(2100, 12, 31))
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    annual: bool = True

    @model_validator(mode="after")
    def validate_original(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("A title is required")
        if self.kind == "birthday":
            if self.date is not None or self.month is None or self.day is None or not self.annual:
                raise ValueError("Birthdays use month/day only and repeat annually")
            Date(2000, self.month, self.day)  # Validates Feb 29 without collecting a birth year.
        elif self.date is None or self.month is not None or self.day is not None:
            raise ValueError("Use an original date for relationships and custom anniversaries")
        if self.kind == "relationship" and not self.annual:
            raise ValueError("Relationship anniversaries repeat annually")
        return self

    def rpc_fields(self) -> dict:
        return {
            f"p_{key}": value
            for key, value in self.model_dump(mode="json").items()
            if key not in {"request_id", "expected_version"}
        }


class CreateAnniversary(AnniversaryInput):
    request_id: UUID


class UpdateAnniversary(AnniversaryInput):
    expected_version: int = Field(ge=1, le=2_147_483_646)


class Anniversary(BaseModel):
    id: UUID
    kind: Literal["relationship", "birthday", "custom"]
    title: str
    date: Date | None
    month: int | None
    day: int | None
    annual: bool
    version: int
    next_date: Date
    days_until: int
    together_days: int | None


class AnniversaryList(BaseModel):
    as_of: Date
    items: list[Anniversary]


def project(row: dict, today: Date) -> dict:
    original = Date.fromisoformat(row["date"]) if row["date"] else None
    month, day = (original.month, original.day) if original else (row["month"], row["day"])
    occurrence = original
    if row["annual"]:
        year = max(today.year, original.year if original else today.year)

        def in_year(value):
            return Date(value, month, min(day, calendar.monthrange(value, month)[1]))

        occurrence = in_year(year)
        if occurrence < today:
            occurrence = in_year(year + 1)
    return {
        **row,
        "next_date": occurrence,
        "days_until": (occurrence - today).days,
        "together_days": (today - original).days + 1
        if row["kind"] == "relationship" and original <= today
        else None,
    }


@router.get("/anniversaries", response_model=AnniversaryList)
def list_anniversaries(store: Store):
    # Page through the caller's RLS-filtered rows instead of silently truncating at 1000.
    rows = []
    offset = 0
    while True:
        page = store.call(
            "GET",
            "anniversaries",
            params={
                "select": "id,kind,title,date,month,day,annual,version",
                "order": "id.asc",
                "limit": "100",
                "offset": str(offset),
            },
        )
        rows.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    today = seoul_today()
    items = [project(row, today) for row in rows]
    items.sort(
        key=lambda row: (row["days_until"] < 0, abs(row["days_until"]), row["title"], row["id"])
    )
    return {"as_of": today, "items": items}


@router.post("/anniversaries", response_model=Anniversary, status_code=201)
def create_anniversary(body: CreateAnniversary, store: Store):
    row = store.rpc(
        "create_anniversary", {**body.rpc_fields(), "p_request_id": str(body.request_id)}
    )[0]
    return project(row, seoul_today())


@router.patch("/anniversaries/{anniversary_id}", response_model=Anniversary)
def update_anniversary(anniversary_id: UUID, body: UpdateAnniversary, store: Store):
    row = store.rpc(
        "update_anniversary",
        {
            **body.rpc_fields(),
            "p_id": str(anniversary_id),
            "p_expected_version": body.expected_version,
        },
    )[0]
    return project(row, seoul_today())
