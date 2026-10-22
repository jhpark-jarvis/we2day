"""User-initiated, bounded iCalendar snapshots; no subscriptions or outbound calendar API."""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Response

from we2day_api.anniversaries import project
from we2day_api.calendar import Store

router = APIRouter(tags=["calendar-export"])
Month = Annotated[str, Query(pattern=r"^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$")]
MAX_ITEMS = 2000
MAX_BYTES = 2 * 1024 * 1024
ANNIVERSARY_FIELDS = "id,kind,title,date,month,day,annual,version"


def month_bounds(month: str) -> tuple[date, date]:
    year, number = map(int, month.split("-"))
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])


def read_rows(store, table, fields, params=None):
    rows, cursor = [], None
    while True:
        query = {"select": fields, "order": "id.asc", "limit": "200", **(params or {})}
        if cursor:
            query["id"] = f"gt.{cursor}"
        page = store.call("GET", table, params=query)
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > MAX_ITEMS:
            raise HTTPException(413, "calendar_export_too_large")
        next_cursor = str(UUID(str(page[-1]["id"])))
        if cursor is not None and next_cursor <= cursor:
            raise HTTPException(503, "Data service unavailable")
        cursor = next_cursor


def check_space(store):
    space = store.rpc("get_my_couple")
    if not space:
        raise HTTPException(409, "couple_required")
    return space["id"]


def escape_text(value: str) -> str:
    value = value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")
    return "".join(c for c in value if ord(c) >= 32 and ord(c) != 127)


def fold_line(value: str) -> bytes:
    # RFC 5545: 75 octets per physical line, continuation space included, UTF-8 intact.
    output, line = [], bytearray()
    for char in value:
        encoded = char.encode("utf-8")
        if len(line) + len(encoded) > 75:
            output.append(bytes(line))
            line = bytearray(b" ")
        line.extend(encoded)
    output.append(bytes(line))
    return b"\r\n".join(output)


def render_calendar(appointments, anniversaries, stamp: datetime, include_notes=False) -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WE2DAY//Calendar Export//KO",
        "CALSCALE:GREGORIAN",
    ]
    timestamp = stamp.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    for row in appointments:
        day = date.fromisoformat(str(row["date"]))
        lines += [
            "BEGIN:VEVENT",
            f"UID:appointment-{UUID(str(row['id']))}@we2day.invalid",
            f"DTSTAMP:{timestamp}",
            f"SEQUENCE:{int(row['version'])}",
        ]
        if row["time"]:
            clock = time.fromisoformat(str(row["time"]))
            start = datetime.combine(day, clock, ZoneInfo("Asia/Seoul")).astimezone(UTC)
            lines.append(f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}")
        else:
            lines += [
                f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            ]
        lines += [f"SUMMARY:{escape_text(row['title'])}", "CLASS:PRIVATE"]
        if row["place"]:
            lines.append(f"LOCATION:{escape_text(row['place'])}")
        if include_notes and row.get("note"):
            lines.append(f"DESCRIPTION:{escape_text(row['note'])}")
        lines.append("END:VEVENT")
    for row in anniversaries:
        day = row["next_date"]
        lines += [
            "BEGIN:VEVENT",
            f"UID:anniversary-{UUID(str(row['id']))}-{day:%Y%m%d}@we2day.invalid",
            f"DTSTAMP:{timestamp}",
            f"SEQUENCE:{int(row['version'])}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{escape_text(row['title'])}",
            "CLASS:PRIVATE",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    content = b"\r\n".join(fold_line(line) for line in lines) + b"\r\n"
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "calendar_export_too_large")
    return content


@router.get("/calendar/export")
def export_calendar(store: Store, month: Month, anniversaries: bool = True, notes: bool = False):
    space = check_space(store)
    first, last = month_bounds(month)
    appointments = read_rows(
        store,
        "appointments",
        "id,title,date,time,place,version" + (",note" if notes else ""),
        {"and": f"(date.gte.{first},date.lte.{last})"},
    )
    occurrences = []
    if anniversaries:
        for row in read_rows(store, "anniversaries", ANNIVERSARY_FIELDS):
            item = project(row, first)
            if first <= item["next_date"] <= last:
                occurrences.append(item)
    if len(appointments) + len(occurrences) > MAX_ITEMS:
        raise HTTPException(413, "calendar_export_too_large")
    if check_space(store) != space:
        raise HTTPException(409, "couple_required")
    content = render_calendar(appointments, occurrences, datetime.now(UTC), notes)
    return Response(
        content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="we2day-calendar-{month}.ics"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
