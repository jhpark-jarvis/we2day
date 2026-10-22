from datetime import UTC, date, datetime, time
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from we2day_api.calendar import Store

router = APIRouter(tags=["calendar"])


class NextItem(BaseModel):
    id: UUID
    title: str
    date: date
    time: time | None
    place: str


class NextAppointment(BaseModel):
    as_of: datetime
    item: NextItem | None


@router.get("/appointments/next", response_model=NextAppointment)
def next_appointment(store: Store):
    rows = store.rpc("get_next_appointment")
    return {"as_of": datetime.now(UTC), "item": rows[0] if rows else None}
