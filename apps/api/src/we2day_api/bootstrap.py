"""Small page read bundles with one verified caller and independent section errors."""

from collections.abc import Callable
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError

from we2day_api.auth import CurrentUser, require_user, unauthenticated
from we2day_api.calendar import Appointment, Couple, Store, list_appointments, my_couple
from we2day_api.calendar_export import Month
from we2day_api.profiles import ProfileView, read_profiles
from we2day_api.timezones import TimezoneView, read_timezones
from we2day_api.upcoming import NextAppointment, next_appointment

router = APIRouter(tags=["page-reads"])
User = Annotated[CurrentUser, Depends(require_user)]


class ReadResult[T](BaseModel):
    data: T | None = None
    status: int = 200
    detail: str = ""


def capture(function: Callable, model, *args):
    try:
        return {"data": TypeAdapter(model).validate_python(function(*args)), "status": 200}
    except HTTPException as error:
        if error.status_code == 401:
            raise
        return {"data": None, "status": error.status_code, "detail": error.detail}
    except ValidationError:
        return {"data": None, "status": 503, "detail": "Data service unavailable"}


async def parallel(**reads):
    results = {}

    async def run(name, read):
        try:
            results[name] = await anyio.to_thread.run_sync(lambda: capture(*read))
        except HTTPException:
            results[name] = {"data": None, "status": 401}

    # Uses the existing bounded AnyIO worker pool; no per-request executors.
    async with anyio.create_task_group() as group:
        for name, read in reads.items():
            group.start_soon(run, name, read)
    if any(result["status"] == 401 for result in results.values()):
        raise unauthenticated()
    return results


class AccountRead(BaseModel):
    user_id: str
    profiles: ReadResult[ProfileView]


class ContextRead(AccountRead):
    couple: ReadResult[Couple | None]


@router.get("/bootstrap/account", response_model=AccountRead)
def account(store: Store, user: User):
    return {"user_id": str(user.id), "profiles": capture(read_profiles, ProfileView, store, user)}


@router.get("/bootstrap/context", response_model=ContextRead)
async def context(store: Store, user: User):
    result = await parallel(
        couple=(my_couple, Couple | None, store),
        profiles=(read_profiles, ProfileView, store, user),
    )
    return {"user_id": str(user.id), **result}


class HomeRead(BaseModel):
    couple: ReadResult[Couple | None]
    appointments: ReadResult[list[Appointment]]
    zones: ReadResult[TimezoneView]
    profiles: ReadResult[ProfileView]
    next: ReadResult[NextAppointment]


@router.get("/bootstrap/home", response_model=HomeRead)
async def home(store: Store, user: User, month: Month):
    couple = await anyio.to_thread.run_sync(lambda: capture(my_couple, Couple | None, store))
    if not couple["data"]:
        empty = {"data": None, "status": 200}
        return {
            "couple": couple,
            "appointments": empty,
            "zones": empty,
            "profiles": empty,
            "next": empty,
        }
    result = await parallel(
        appointments=(list_appointments, list[Appointment], store, month),
        zones=(read_timezones, TimezoneView, store, user),
        profiles=(read_profiles, ProfileView, store, user),
        next=(next_appointment, NextAppointment, store),
    )
    return {"couple": couple, **result}
