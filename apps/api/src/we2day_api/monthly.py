from datetime import date
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from we2day_api.calendar import Store
from we2day_api.calendar_export import Month

router = APIRouter(tags=["monthly-memories"])


class MemoryDay(BaseModel):
    date: date
    met: bool
    photo_count: int = Field(ge=0)
    route_recorded: bool


class MemoryPhoto(BaseModel):
    id: UUID
    date: date
    caption: str


class MonthlyMemories(BaseModel):
    month: str
    meeting_count: int = Field(ge=0, le=31)
    photo_count: int = Field(ge=0)
    route_count: int = Field(ge=0, le=31)
    days: list[MemoryDay] = Field(max_length=31)
    photos: list[MemoryPhoto] = Field(max_length=6)


@router.get("/memories/month", response_model=MonthlyMemories)
def monthly_memories(store: Store, month: Month):
    return store.rpc("get_monthly_memories", {"p_month": f"{month}-01"})
