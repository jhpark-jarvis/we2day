from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from we2day_api.calendar import Store
from we2day_api.record_search import SearchInput, read_search_input
from we2day_api.snapshot_format import encode_snapshot

router = APIRouter(tags=["record-export"])
Kind = Literal[
    "appointments",
    "anniversaries",
    "meeting_days",
    "meeting_routes",
    "date_plans",
    "date_reports",
    "photos",
    "wishes",
    "shared_checklists",
    "shared_goals",
    "couple_questions",
    "question_answers",
    "timezone_preferences",
    "roulette_wheels",
    "roulette_draws",
    "plan_visit_progress",
]


class SnapshotInput(SearchInput):
    kind: Kind
    include_private: bool = False
    query: Literal[""] = ""
    offset: int = Field(default=0, ge=0, le=0)


async def read_input(request: Request) -> SnapshotInput:
    return await read_search_input(request, SnapshotInput, "invalid_record_export")


@router.post("/records/export")
def record_snapshot(body: Annotated[SnapshotInput, Depends(read_input)], store: Store):
    rows = store.rpc(
        "export_record_snapshot",
        {
            "p_kind": body.kind,
            "p_start": str(body.start_date),
            "p_end": str(body.end_date),
            "p_private": body.include_private,
        },
    )
    try:
        content = encode_snapshot(
            body.kind, rows, body.start_date, body.end_date, body.include_private
        )
    except ValueError as error:
        raise HTTPException(413, "record_export_too_large") from error
    except (KeyError, TypeError) as error:
        raise HTTPException(503, "Data service unavailable") from error
    return Response(
        content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="we2day-{body.kind}.json"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
