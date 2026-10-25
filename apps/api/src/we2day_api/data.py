import logging
from collections.abc import Iterator
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from we2day_api.auth import CurrentUser, bearer, require_user, unauthenticated
from we2day_api.timing import timed
from we2day_api.upstream import upstream_transport

logger = logging.getLogger(__name__)


class DataAPI:
    def __init__(self, transport: httpx.Client):
        self.transport = transport

    @timed("data")
    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.transport.request(method, path, **kwargs)
            payload = response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(503, "Data service unavailable") from error
        if response.is_success:
            return payload
        if response.status_code == 401:
            raise unauthenticated()
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        # Fixed diagnostic categories only; never log URL, body, SQL text, tokens or user data.
        category = (
            "schema_not_ready"
            if code in {"PGRST202", "PGRST205", "42P01", "42883"}
            else "permission_denied"
            if code == "42501"
            else "upstream_error"
        )
        if response.status_code >= 500 or code not in {"PT400", "PT404", "PT409", "PT413", "PT422"}:
            logger.warning(
                "Data service failure: status=%s category=%s", response.status_code, category
            )
        safe_errors = {
            "invalid_agent_connection",
            "agent_connection_limit",
            "agent_connection_not_found",
            "invalid_push_subscription",
            "push_device_limit",
            "push_test_limited",
            "push_registration_required",
            "already_connected",
            "couple_required",
            "couple_full",
            "invalid_invite",
            "invalid_appointment",
            "invalid_anniversary",
            "anniversary_not_found",
            "relationship_exists",
            "invalid_request",
            "appointment_not_found",
            "version_conflict",
            "request_conflict",
            "invalid_photo",
            "invalid_photo_metadata",
            "invalid_photo_search",
            "invalid_meeting_day",
            "invalid_route",
            "invalid_plan",
            "plan_not_found",
            "plan_archived",
            "invalid_report",
            "report_not_ready",
            "invalid_wish",
            "invalid_favorite_place",
            "favorite_place_not_found",
            "wish_not_found",
            "invalid_checklist",
            "checklist_not_found",
            "checklist_items_retained",
            "invalid_goal",
            "goal_not_found",
            "goal_steps_retained",
            "invalid_question",
            "invalid_question_search",
            "invalid_record_search",
            "invalid_record_export",
            "record_export_too_large",
            "invalid_visit_progress",
            "publication_changed",
            "question_not_found",
            "invalid_answer",
            "invalid_timezone",
            "invalid_profile",
            "invalid_roulette",
            "roulette_not_found",
            "roulette_archived",
            "photo_not_found",
            "photo_upload_incomplete",
            "invalid_photo_action",
            "photo_confirmation_required",
            "photo_deleting",
            "photo_state_conflict",
            "photo_retention_active",
            "photo_delete_incomplete",
        }
        if code in {"PT400", "PT404", "PT409", "PT413", "PT422"} and message in safe_errors:
            raise HTTPException(int(code[2:]), message)
        # Never reflect SQL errors, query details, tokens, or upstream configuration.
        if code in {"PGRST202", "PGRST205", "42P01", "42883"}:
            raise HTTPException(503, "Database setup required")
        raise HTTPException(503, "Data service unavailable")

    def rpc(self, name: str, body: dict | None = None) -> Any:
        return self.call("POST", f"rpc/{name}", json=body or {})


def require_data(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_user)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> Iterator[DataAPI]:
    config = request.app.state.settings
    # require_user has already verified this caller against the same project.
    with httpx.Client(
        transport=upstream_transport(request),
        base_url=f"{config.supabase_url.rstrip('/')}/rest/v1/",
        headers={
            "apikey": config.supabase_publishable_key,
            "Authorization": f"Bearer {credentials.credentials}",
        },
        timeout=8.0,
    ) as transport:
        yield DataAPI(transport)
