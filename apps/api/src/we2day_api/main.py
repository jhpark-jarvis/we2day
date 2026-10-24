from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from we2day_api.agents import router as agents_router
from we2day_api.anniversaries import router as anniversaries_router
from we2day_api.auth import CurrentUser, require_user
from we2day_api.calendar import router as calendar_router
from we2day_api.calendar_export import router as calendar_export_router
from we2day_api.checklists import router as checklists_router
from we2day_api.config import Settings, get_settings
from we2day_api.favorite_places import router as favorite_places_router
from we2day_api.goals import router as goals_router
from we2day_api.meetings import router as meetings_router
from we2day_api.monthly import router as monthly_router
from we2day_api.notification_preview import router as notification_preview_router
from we2day_api.photo_export import router as photo_export_router
from we2day_api.photo_search import router as photo_search_router
from we2day_api.photos import router as photos_router
from we2day_api.places import router as places_router
from we2day_api.plans import router as plans_router
from we2day_api.profiles import router as profiles_router
from we2day_api.push import router as push_router
from we2day_api.questions import router as questions_router
from we2day_api.record_search import router as record_search_router
from we2day_api.record_snapshots import router as record_snapshots_router
from we2day_api.reminders import router as reminders_router
from we2day_api.reports import router as reports_router
from we2day_api.roulette import router as roulette_router
from we2day_api.route_history import router as route_history_router
from we2day_api.routes import router as routes_router
from we2day_api.timezones import router as timezones_router
from we2day_api.upcoming import router as upcoming_router
from we2day_api.visits import router as visits_router
from we2day_api.wishlist import router as wishlist_router


class HealthResponse(BaseModel):
    status: str
    service: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        pool = httpx.HTTPTransport(
            limits=httpx.Limits(
                max_connections=20, max_keepalive_connections=10, keepalive_expiry=30
            )
        )
        try:
            application.state.upstream_pool = pool
            yield
        finally:
            pool.close()

    application = FastAPI(title="WE2DAY API", version="0.1.0", lifespan=lifespan)
    application.state.settings = config
    application.include_router(agents_router)
    application.include_router(push_router)
    application.include_router(upcoming_router)
    application.include_router(calendar_router)
    application.include_router(calendar_export_router)
    application.include_router(reminders_router)
    application.include_router(notification_preview_router)
    application.include_router(anniversaries_router)
    application.include_router(photos_router)
    application.include_router(photo_export_router)
    application.include_router(photo_search_router)
    application.include_router(meetings_router)
    application.include_router(monthly_router)
    application.include_router(places_router)
    application.include_router(favorite_places_router)
    application.include_router(plans_router)
    application.include_router(profiles_router)
    application.include_router(visits_router)
    application.include_router(reports_router)
    application.include_router(route_history_router)
    application.include_router(routes_router)
    application.include_router(wishlist_router)
    application.include_router(checklists_router)
    application.include_router(goals_router)
    application.include_router(record_snapshots_router)
    application.include_router(record_search_router)
    application.include_router(questions_router)
    application.include_router(timezones_router)
    application.include_router(roulette_router)

    @application.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        """Process liveness only; this does not assert database or auth readiness."""
        return HealthResponse(status="ok", service="we2day-api")

    @application.get("/auth/me", response_model=CurrentUser, tags=["auth"])
    def me(user: Annotated[CurrentUser, Depends(require_user)]) -> CurrentUser:
        return user

    return application


app = create_app()
