"""Explicitly scoped agent keys. Never accept them as the normal user's JWT."""

import re
from datetime import date
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from we2day_api.auth import bearer, unauthenticated
from we2day_api.data import DataAPI, require_data
from we2day_api.plans import PlanContent
from we2day_api.upstream import upstream_transport

router = APIRouter(tags=["agent-connections"])
Store = Annotated[DataAPI, Depends(require_data)]
KEY = re.compile(r"w2d_agent_[0-9a-f]{64}")
FIELDS = "id,label,created_at,expires_at,revoked_at,last_used_at"


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)


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
    return store.rpc("create_agent_connection", {"p_label": body.label})


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
        if response.status_code in {404, 409, 422, 429}:
            codes = {
                404: "not_found",
                409: "request_conflict",
                422: "invalid_request",
                429: "agent_limit",
            }
            raise HTTPException(response.status_code, codes[response.status_code])
        if not response.is_success:
            raise HTTPException(503, "Agent gateway unavailable")
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, "Agent gateway unavailable") from error


Credential = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


@router.get("/agent/v1/calendar")
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


@router.get("/agent/v1/plans/{plan_id}")
def agent_plan(plan_id: UUID, request: Request, credentials: Credential):
    return agent_rpc(request, credentials, "agent_plan", {"p_id": str(plan_id)})


@router.post("/agent/v1/drafts")
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
