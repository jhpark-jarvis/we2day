from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError
from supabase import ClientOptions, create_client
from supabase_auth.errors import AuthApiError, AuthRetryableError

from we2day_api.upstream import upstream_transport

bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    id: UUID
    email: str | None = None


def require_user(
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    response.headers["Cache-Control"] = "private, no-store"
    if not credentials:
        raise unauthenticated()
    config = request.app.state.settings
    if not config.supabase_url or not config.supabase_publishable_key:
        raise HTTPException(
            503, "Authentication is not configured", headers={"Cache-Control": "private, no-store"}
        )
    # Never share a stateful SDK client/session across users or use an admin key.
    with httpx.Client(timeout=8.0, transport=upstream_transport(request)) as transport:
        client = create_client(
            config.supabase_url,
            config.supabase_publishable_key,
            options=ClientOptions(
                auto_refresh_token=False, persist_session=False, httpx_client=transport
            ),
        )
        try:
            result = client.auth.get_user(credentials.credentials)
        except AuthRetryableError as error:
            raise unavailable() from error
        except AuthApiError as error:
            if error.status in (400, 401, 403, 404):
                raise unauthenticated() from error
            raise unavailable() from error
        except (httpx.HTTPError, ValidationError) as error:
            raise unavailable() from error
    if not result or not result.user:
        raise unauthenticated()
    return CurrentUser(id=result.user.id, email=result.user.email)


def unauthenticated() -> HTTPException:
    return HTTPException(
        401,
        "A valid access token is required",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "private, no-store"},
    )


def unavailable() -> HTTPException:
    return HTTPException(
        503, "Authentication service unavailable", headers={"Cache-Control": "private, no-store"}
    )
