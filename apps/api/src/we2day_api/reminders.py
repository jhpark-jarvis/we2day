from datetime import date as Date
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from we2day_api.anniversaries import project, seoul_today
from we2day_api.calendar import Store
from we2day_api.calendar_export import ANNIVERSARY_FIELDS, MAX_ITEMS, check_space, read_rows

router = APIRouter(tags=["reminders"])


class UpcomingItem(BaseModel):
    source: Literal["appointment", "anniversary"]
    id: str
    title: str
    date: Date
    time: str | None
    place: str
    days_until: int


class UpcomingList(BaseModel):
    as_of: Date
    until: Date
    items: list[UpcomingItem]


@router.get("/reminders", response_model=UpcomingList)
def upcoming(store: Store, days: int = 7):
    if days not in (7, 30):
        raise HTTPException(422, "invalid_request")
    space = check_space(store)
    today = seoul_today()
    end = today + timedelta(days=days)
    items = []
    for row in read_rows(
        store,
        "appointments",
        "id,title,date,time,place",
        {"and": f"(date.gte.{today},date.lte.{end})"},
    ):
        day = Date.fromisoformat(row["date"])
        items.append(
            {
                "source": "appointment",
                "id": row["id"],
                "title": row["title"],
                "date": day,
                "time": row["time"],
                "place": row["place"],
                "days_until": (day - today).days,
            }
        )
    for row in read_rows(store, "anniversaries", ANNIVERSARY_FIELDS):
        item = project(row, today)
        if 0 <= item["days_until"] <= days:
            items.append(
                {
                    "source": "anniversary",
                    "id": row["id"],
                    "title": row["title"],
                    "date": item["next_date"],
                    "time": None,
                    "place": "",
                    "days_until": item["days_until"],
                }
            )
    if len(items) > MAX_ITEMS:
        raise HTTPException(413, "calendar_export_too_large")
    if check_space(store) != space:
        raise HTTPException(409, "couple_required")
    items.sort(key=lambda item: (item["date"], item["time"] or "", item["source"], item["id"]))
    return {"as_of": today, "until": end, "items": items}
