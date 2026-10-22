"""Pure reminder times and identities. No credentials, queues, clock reads or delivery."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from we2day_api.anniversaries import project

SEOUL = ZoneInfo("Asia/Seoul")
LEAD_DAYS = (7, 1, 0)


class ScheduleLimitError(ValueError):
    """The complete result would exceed the caller's bound; never return a partial list."""


@dataclass(frozen=True, slots=True)
class ReminderTime:
    anniversary_id: UUID
    source_version: int
    title: str = field(repr=False)
    occurrence_date: date
    lead_days: int
    scheduled_at: datetime

    def delivery_key(self, owner_id: UUID, subscription_digest: str) -> str:
        """A deduplication identity only; never an authorization token or delivery guarantee."""
        if not isinstance(owner_id, UUID) or not re.fullmatch(r"[0-9a-f]{64}", subscription_digest):
            raise ValueError("invalid_delivery_identity")
        identity = [
            "we2day-anniversary-v1",
            str(self.anniversary_id),
            self.source_version,
            self.occurrence_date.isoformat(),
            self.lead_days,
            str(owner_id),
            subscription_digest,
        ]
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def reminder_times(
    rows: list[dict], start: datetime, end: datetime, *, max_items: int
) -> list[ReminderTime]:
    """Return Seoul 09:00 reminders in [start, end); adjacent windows do not overlap.

    Callers must separately check current membership, source version and device consent
    immediately before sending. This function neither authorizes nor sends anything.
    """
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or type(max_items) is not int
        or not 1 <= max_items <= 2000
    ):
        raise ValueError("invalid_schedule_window")
    start, end = start.astimezone(SEOUL), end.astimezone(SEOUL)
    if end < start or end - start > timedelta(days=366):
        raise ValueError("invalid_schedule_window")
    if len(rows) > max_items:
        raise ScheduleLimitError("schedule_too_large")
    if start == end:
        return []
    occurrence_end = end.date() + timedelta(days=max(LEAD_DAYS))
    items = []
    for row in rows:
        identifier = UUID(str(row["id"]))
        version = row["version"]
        if type(version) is not int or not 1 <= version <= 2_147_483_647:
            raise ValueError("invalid_source_version")
        cursor = start.date()
        while cursor <= occurrence_end:
            occasion = project(row, cursor)["next_date"]
            if occasion < cursor or occasion > occurrence_end:
                break
            for lead in LEAD_DAYS:
                scheduled = datetime.combine(occasion - timedelta(days=lead), time(9), SEOUL)
                if start <= scheduled < end:
                    items.append(
                        ReminderTime(identifier, version, row["title"], occasion, lead, scheduled)
                    )
                    if len(items) > max_items:
                        raise ScheduleLimitError("schedule_too_large")
            if not row["annual"]:
                break
            cursor = occasion + timedelta(days=1)
    items.sort(key=lambda item: (item.scheduled_at, item.occurrence_date, item.anniversary_id))
    return items
