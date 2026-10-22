"""Caller-scoped, read-only reminder times; never queue or send notifications."""

from datetime import datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from we2day_api.calendar import Store
from we2day_api.calendar_export import ANNIVERSARY_FIELDS, MAX_ITEMS, check_space, read_rows
from we2day_api.reminder_times import SEOUL, ScheduleLimitError, reminder_times

router = APIRouter(tags=["reminders"])


def seoul_now() -> datetime:
    return datetime.now(SEOUL)


class NotificationTime(BaseModel):
    anniversary_id: UUID
    title: str
    occurrence_date: str
    lead_days: int
    scheduled_at: datetime


class NotificationPreview(BaseModel):
    as_of: datetime
    through_date: str
    timezone: str = "Asia/Seoul"
    preview_only: bool = True
    items: list[NotificationTime]


def preview_times(rows: list[dict], now: datetime, days: int) -> dict:
    if days not in (7, 30) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("invalid_preview_window")
    now = now.astimezone(SEOUL)
    through = now.date() + timedelta(days=days)
    end = datetime.combine(through + timedelta(days=1), time.min, SEOUL)
    try:
        times = reminder_times(rows, now, end, max_items=MAX_ITEMS)
    except ScheduleLimitError:
        raise HTTPException(413, "calendar_export_too_large") from None
    items = [
        {
            "anniversary_id": str(item.anniversary_id),
            "title": item.title,
            "occurrence_date": item.occurrence_date.isoformat(),
            "lead_days": item.lead_days,
            "scheduled_at": item.scheduled_at,
        }
        for item in times
    ]
    return {"as_of": now, "through_date": through.isoformat(), "items": items}


@router.get("/reminders/anniversary-preview", response_model=NotificationPreview)
def anniversary_notification_preview(store: Store, days: int = 7):
    if days not in (7, 30):
        raise HTTPException(422, "invalid_request")
    space = check_space(store)
    rows = read_rows(store, "anniversaries", ANNIVERSARY_FIELDS)
    result = preview_times(rows, seoul_now(), days)
    if check_space(store) != space:
        raise HTTPException(409, "couple_required")
    return result
