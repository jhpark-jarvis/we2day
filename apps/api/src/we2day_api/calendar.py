import calendar
from datetime import date as Date
from datetime import datetime
from datetime import time as Time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from we2day_api.data import DataAPI, require_data

router = APIRouter(tags=["shared-calendar"])
Store = Annotated[DataAPI, Depends(require_data)]


class Couple(BaseModel):
    id: UUID
    member_count: int = Field(ge=1, le=2)


class Invitation(BaseModel):
    token: str
    expires_at: datetime


class AcceptInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[0-9a-f]{64}$")


class AppointmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    time: Time | None = None
    place: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A title is required")
        return value.strip()

    @field_validator("time")
    @classmethod
    def local_minutes(cls, value: Time | None) -> Time | None:
        if value and (value.tzinfo or value.second or value.microsecond):
            raise ValueError("Use local HH:mm in Asia/Seoul")
        return value

    def rpc_fields(self) -> dict:
        return {
            f"p_{key}": value
            for key, value in self.model_dump(mode="json").items()
            if key not in {"request_id", "expected_version", "kind"}
        }


class CreateAppointment(AppointmentInput):
    kind: Literal["shared", "personal"] = "shared"
    request_id: UUID


class UpdateAppointment(AppointmentInput):
    expected_version: int = Field(ge=1, le=2_147_483_646)


class Appointment(BaseModel):
    kind: Literal["shared", "personal"] = "shared"
    id: UUID
    title: str
    date: Date
    time: Time | None
    place: str
    note: str
    version: int
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


@router.get("/couple", response_model=Couple | None)
def my_couple(store: Store):
    return store.rpc("get_my_couple")


@router.post("/couple", response_model=Couple, status_code=201)
def create_couple(store: Store):
    return store.rpc("create_couple")


@router.post("/couple/invites", response_model=Invitation, status_code=201)
def create_invite(store: Store):
    return store.rpc("create_couple_invite")


@router.post("/couple/accept", response_model=Couple)
def accept_invite(body: AcceptInvite, store: Store):
    return store.rpc("accept_couple_invite", {"p_token": body.token})


@router.get("/appointments", response_model=list[Appointment])
def list_appointments(
    store: Store,
    month: Annotated[str, Query(pattern=r"^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$")],
):
    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    return store.call(
        "GET",
        "appointments",
        params={
            "select": (
                "id,title,date,time,place,note,version,created_by,updated_by,created_at,updated_at,kind"
            ),
            "and": f"(date.gte.{month}-01,date.lte.{month}-{last_day:02})",
            "order": "date.asc,time.asc.nullslast,id.asc",
        },
    )


@router.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(body: CreateAppointment, store: Store):
    if body.kind == "personal" and body.place:
        raise HTTPException(422, "invalid_appointment")
    rows = store.rpc(
        "create_personal_appointment" if body.kind == "personal" else "create_appointment",
        {
            **body.rpc_fields(),
            "p_request_id": str(body.request_id),
        },
    )
    return rows[0]


@router.patch("/appointments/{appointment_id}", response_model=Appointment)
def update_appointment(appointment_id: UUID, body: UpdateAppointment, store: Store):
    rows = store.rpc(
        "update_appointment",
        {
            **body.rpc_fields(),
            "p_id": str(appointment_id),
            "p_expected_version": body.expected_version,
        },
    )
    return rows[0]


class DeletePersonalAppointment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, le=2_147_483_646)


@router.delete("/appointments/{appointment_id}", status_code=204)
def delete_personal_appointment(
    appointment_id: UUID, body: DeletePersonalAppointment, store: Store
):
    try:
        store.rpc(
            "delete_personal_appointment",
            {"p_id": str(appointment_id), "p_expected_version": body.expected_version},
        )
    except HTTPException as error:
        if error.status_code != 404 or error.detail != "appointment_not_found":
            raise
    return Response(status_code=204)
