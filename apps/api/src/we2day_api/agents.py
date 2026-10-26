"""Explicitly scoped agent keys. Never accept them as the normal user's JWT."""

import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, model_validator

from we2day_api.auth import bearer, unauthenticated
from we2day_api.calendar import AppointmentInput
from we2day_api.data import DataAPI, require_data
from we2day_api.plans import PlanContent
from we2day_api.upstream import upstream_transport

router = APIRouter(tags=["agent-connections"])
Store = Annotated[DataAPI, Depends(require_data)]
KEY = re.compile(r"w2d_agent_[0-9a-f]{64}")
FIELDS = "id,label,created_at,expires_at,revoked_at,last_used_at,can_manage"


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    can_manage: bool = Field(default=False, strict=True)


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    request_id: UUID
    content: PlanContent


@router.get("/agent-connections")
def list_connections(store: Store):
    return store.call(
        "GET",
        "agent_connections",
        params={
            "select": FIELDS,
            "order": "revoked_at.asc.nullsfirst,expires_at.desc",
            "limit": "100",
        },
    )


@router.post("/agent-connections")
def create_connection(body: ConnectionInput, store: Store):
    return store.rpc(
        "create_managed_agent_connection", {"p_label": body.label, "p_manage": body.can_manage}
    )


@router.delete("/agent-connections/{connection_id}")
def revoke_connection(connection_id: UUID, store: Store):
    return {"revoked": store.rpc("revoke_agent_connection", {"p_id": str(connection_id)})}


def agent_rpc(request: Request, credentials, function: str, parameters: dict):
    if not credentials or not KEY.fullmatch(credentials.credentials):
        raise unauthenticated()
    settings = request.app.state.settings
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, "Agent gateway unavailable")
    try:
        # No service key, user JWT, session cookies, redirects or environment proxies.
        with httpx.Client(
            transport=upstream_transport(request),
            timeout=8,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function}",
                headers={"apikey": settings.supabase_publishable_key},
                json={"p_key": credentials.credentials, **parameters},
            )
        if response.status_code == 401:
            raise unauthenticated()
        if response.status_code in {403, 404, 409, 422, 429}:
            codes = {
                403: "agent_manage_required",
                404: "not_found",
                409: "request_conflict",
                422: "invalid_request",
                429: "agent_limit",
            }
            code = codes[response.status_code]
            try:
                reason = response.json().get("message")
                if reason in {
                    "version_conflict",
                    "linked_plan_required",
                    "plan_archived",
                    "confirmation_required",
                    "agent_change_limit",
                    "agent_draft_limit",
                }:
                    code = reason
            except (ValueError, AttributeError):
                pass
            raise HTTPException(response.status_code, code)
        if not response.is_success:
            raise HTTPException(503, "Agent gateway unavailable")
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, "Agent gateway unavailable") from error


Credential = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


class AgentAppointmentView(AppointmentInput):
    id: UUID
    version: int
    plan_id: UUID | None = None


class AgentPlanView(BaseModel):
    id: UUID
    content: PlanContent
    published_content: PlanContent | None
    published_revision: int
    version: int
    archived: bool = False
    appointment_id: UUID | None = None
    appointment_version: int = 0


class AgentCalendarView(BaseModel):
    appointments: list[AgentAppointmentView] = Field(default_factory=list)
    plans: list[AgentPlanView] = Field(default_factory=list)
    next_offset: int | None = None


class AgentDraftResult(BaseModel):
    id: UUID
    created: bool


class AgentChangeResult(BaseModel):
    id: UUID
    version: int | None = None
    archived: bool | None = None
    published_revision: int | None = None
    appointment_id: UUID | None = None
    deleted: bool | None = None
    replayed: bool = False


@router.get("/agent/v1/calendar", operation_id="readCalendar", response_model=AgentCalendarView)
def agent_calendar(
    request: Request,
    credentials: Credential,
    start: date,
    end: date,
    offset: int = Query(default=0, ge=0, le=100000),
):
    if not 0 <= (end - start).days <= 30:
        raise HTTPException(422, "invalid_request")
    return agent_rpc(
        request,
        credentials,
        "agent_calendar",
        {"p_start": start.isoformat(), "p_end": end.isoformat(), "p_offset": offset},
    )


@router.get("/agent/v1/plans/{plan_id}", operation_id="readPlan", response_model=AgentPlanView)
def agent_plan(plan_id: UUID, request: Request, credentials: Credential):
    return agent_rpc(request, credentials, "agent_plan", {"p_id": str(plan_id)})


@router.post("/agent/v1/drafts", operation_id="createDraft", response_model=AgentDraftResult)
def create_draft(body: DraftInput, request: Request, credentials: Credential):
    return agent_rpc(
        request,
        credentials,
        "agent_create_draft",
        {
            "p_id": str(body.id),
            "p_request_id": str(body.request_id),
            "p_content": body.content.model_dump(mode="json"),
        },
    )


class AgentChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=0, le=2_147_483_646, strict=True)
    expected_appointment_version: int = Field(default=0, ge=0, le=2_147_483_646, strict=True)
    confirmed: bool = Field(default=False, strict=True)


class AgentPlanChange(AgentChange):
    action: Literal["save", "confirm", "archive", "restore"]
    content: PlanContent | None = None

    @model_validator(mode="after")
    def valid_action(self):
        if (self.action == "save") != (self.content is not None):
            raise ValueError("Content is required only for save")
        if self.action in {"confirm", "archive"} and not self.confirmed:
            raise ValueError("Explicit confirmation required")
        return self


class AgentAppointmentChange(AgentChange):
    action: Literal["create", "update", "delete"]
    content: AppointmentInput | None = None

    @model_validator(mode="after")
    def valid_action(self):
        if (self.action != "delete") != (self.content is not None):
            raise ValueError("Content is required for create/update")
        if self.action == "delete" and not self.confirmed:
            raise ValueError("Explicit confirmation required")
        if self.action == "create" and self.expected_version != 0:
            raise ValueError("New appointment version must be zero")
        return self


def mutate(entity, id, body, request, credentials):
    fields = body.model_dump(mode="json")
    if entity == "appointment" and body.content is not None and body.content.time is not None:
        fields["content"]["time"] = body.content.time.strftime("%H:%M")
    return agent_rpc(
        request,
        credentials,
        "agent_change",
        {
            "p_entity": entity,
            "p_id": str(id),
            **{f"p_{k}": v for k, v in fields.items()},
        },
    )


@router.get(
    "/agent/v1/appointments/{appointment_id}",
    operation_id="readAppointment",
    response_model=AgentAppointmentView,
)
def agent_appointment(appointment_id: UUID, request: Request, credentials: Credential):
    return agent_rpc(request, credentials, "agent_appointment", {"p_id": str(appointment_id)})


@router.post(
    "/agent/v1/plans/{plan_id}/changes",
    operation_id="changePlan",
    response_model=AgentChangeResult,
    response_model_exclude_none=True,
)
def agent_change_plan(
    plan_id: UUID, body: AgentPlanChange, request: Request, credentials: Credential
):
    return mutate("plan", plan_id, body, request, credentials)


@router.post(
    "/agent/v1/appointments/{appointment_id}/changes",
    operation_id="changeAppointment",
    response_model=AgentChangeResult,
    response_model_exclude_none=True,
)
def agent_change_appointment(
    appointment_id: UUID, body: AgentAppointmentChange, request: Request, credentials: Credential
):
    return mutate("appointment", appointment_id, body, request, credentials)


@router.get("/agent/openapi.json", include_in_schema=False)
def agent_openapi():
    from we2day_api.agent_contract import schema

    return schema()
