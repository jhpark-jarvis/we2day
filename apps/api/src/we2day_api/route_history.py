"""Read manually recorded pairs without inferring trips between dates."""

import json
from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from we2day_api.calendar import Store
from we2day_api.record_search import SearchInput, read_search_input
from we2day_api.routes import RouteContent

router = APIRouter(tags=["meeting-routes"])
FIELDS = "date,start_name,start_lat,start_lng,end_name,end_lat,end_lng,version,updated_at"


class RouteRange(SearchInput):
    query: Literal[""] = ""


class RouteHit(RouteContent):
    model_config = ConfigDict(strict=False, extra="ignore")
    date: Date
    version: int
    updated_at: datetime


class RoutePage(BaseModel):
    items: list[RouteHit]
    next_offset: int | None


async def read_range(request: Request) -> RouteRange:
    return await read_search_input(request, RouteRange, "invalid_route_history")


def read_rows(body: RouteRange, store, export=False):
    return store.call(
        "GET",
        "meeting_routes",
        params={
            "select": FIELDS,
            "and": f"(date.gte.{body.start_date},date.lte.{body.end_date})",
            "order": "date.asc" if export else "date.desc",
            "limit": "367" if export else "51",
            "offset": "0" if export else str(body.offset),
        },
    )


@router.post("/routes/history", response_model=RoutePage)
def route_history(body: Annotated[RouteRange, Depends(read_range)], store: Store):
    if not store.rpc("get_my_couple"):
        raise HTTPException(409, "couple_required")
    rows = read_rows(body, store)
    return {
        "items": rows[:50],
        "next_offset": body.offset + 50 if len(rows) > 50 and body.offset + 50 <= 100000 else None,
    }


@router.post("/routes/export")
def export_routes(body: Annotated[RouteRange, Depends(read_range)], store: Store):
    if body.offset != 0:
        raise HTTPException(422, "invalid_route_history")
    if not store.rpc("get_my_couple"):
        raise HTTPException(409, "couple_required")
    rows = read_rows(body, store, True)
    if len(rows) > 366:
        raise HTTPException(413, "record_export_too_large")
    features = []
    for row in rows:
        item = RouteHit.model_validate(row)
        features.append(
            {
                "type": "Feature",
                "id": item.date.isoformat(),
                "properties": {
                    "date": item.date.isoformat(),
                    "start_name": item.start_name,
                    "end_name": item.end_name,
                    "record_version": item.version,
                    "recorded_at": item.updated_at.isoformat(),
                    "route_type": "manual_pair",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[item.start_lng, item.start_lat], [item.end_lng, item.end_lat]],
                },
            }
        )
    return Response(
        json.dumps(
            {"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False
        ),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": 'attachment; filename="we2day-routes.geojson"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
