"""Caller-scoped private reads rendered locally, never returned to a model."""

from uuid import UUID

import httpx
from fastapi import HTTPException

from we2day_api.ai_capabilities import QUESTIONS
from we2day_api.ai_course_check import inspect_current_course
from we2day_api.ai_place_policy import norm
from we2day_api.ai_saved_schedule import (
    PLAN_SELECT,
    ScheduleRead,
    read_schedule,
    schedule_date,
    summarize_schedule,
)


def calendar_request(args, latest, context, version, today):
    request = schedule_date(latest, context, version, today)
    if request.question:
        known = context.get("date")
        if request.reason == "missing_date" and known and args.get("date", "") in {"", known}:
            return ScheduleRead(date=known)
        return request
    if not request or not request.date:
        return ScheduleRead(question=QUESTIONS["date"])
    # Dates resolved from the current user request/versioned followup are authoritative.
    # A model argument must not override them or cause a false missing-date question.
    return request


async def read_plan(args, latest, context, version, today, store, stats):
    plan_id, title = args["plan_id"], args["title"].strip()
    if plan_id:
        try:
            plan_id = str(UUID(plan_id))
        except ValueError:
            return "플랜 ID를 확인해 주세요.", []
        if plan_id.lower() not in latest.lower():
            return "조회할 플랜의 제목이나 ID를 직접 알려주세요.", []
    elif not title or len(norm(title)) < 2 or norm(title) not in norm(latest):
        return "조회할 플랜의 제목이나 ID를 직접 알려주세요.", []
    target = ""
    requested = schedule_date(latest, {}, version, today)
    if requested.reason not in {"missing_date"}:
        if requested.question:
            return requested.question, []
        request = calendar_request({}, latest, {}, version, today)
        if request.question:
            return request.question, []
        target = request.date
    try:
        rows = {}
        with stats.span("tools"):
            fields = ["id"] if plan_id else ["content->>title", "published_content->>title"]
            for column in fields:
                params = {
                    "select": PLAN_SELECT,
                    "archived": "eq.false",
                    "limit": "11",
                    "order": "id.asc",
                    column: (
                        "eq." + plan_id
                        if plan_id
                        else "like." + title + "*"
                        if all(c.isalnum() or c in " -" for c in title)
                        else "eq." + title
                    ),
                }
                if target:
                    params["or"] = (
                        f"(content->>date.eq.{target},published_content->>date.eq.{target})"
                    )
                values = await store.call("GET", "date_plans", params=params)
                if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                    raise ValueError("Invalid plan result")
                for row in values:
                    rows[str(row["id"])] = row
                if len(values) > 10:
                    return (
                        "저장 플랜 조회\n비슷한 제목이 많아요. "
                        "정확한 제목이나 플랜 ID를 알려주세요.",
                        [{"name": "read_shared_plan", "status": "ambiguous", "count": 0}],
                    )
        candidates = [
            r
            for r in rows.values()
            if (not target or target in {r.get("draft_date"), r.get("published_date")})
            and (
                plan_id
                or any(
                    norm(t) and norm(t) in norm(latest)
                    for t in [r.get("draft_title") or "", r.get("published_title") or ""]
                )
            )
        ]
        if not candidates:
            return "저장 플랜 조회\n해당하는 비보관 공동 플랜을 찾지 못했어요.", [
                {"name": "read_shared_plan", "status": "empty", "count": 0}
            ]
        if len(candidates) != 1:
            return "저장 플랜 조회\n같은 제목의 플랜이 여러 개예요. 날짜나 플랜 ID를 알려주세요.", [
                {"name": "read_shared_plan", "status": "ambiguous", "count": 0}
            ]
        row = candidates[0]
        dates = (
            [target]
            if target
            else sorted({d for d in [row.get("published_date"), row.get("draft_date")] if d})
        )
        summaries = [summarize_schedule(d, [], [row]) for d in dates]
        reply = "저장 플랜 조회\n" + "\n".join(s.reply for s in summaries)
        partial = any(s.partial for s in summaries) or len(reply) > 3900
        if len(reply) > 3900:
            reply = reply[:3800] + "\n일부 내용만 표시했어요. 플랜에서 나머지를 확인해 주세요."
        return reply, [
            {"name": "read_shared_plan", "status": "partial" if partial else "ok", "count": 1}
        ]
    except (HTTPException, httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
        return "저장 플랜 조회\n플랜을 불러오지 못했어요. 잠시 후 다시 확인해 주세요.", [
            {"name": "read_shared_plan", "status": "failed", "count": 0}
        ]


async def execute_reads(selection, latest, context, version, today, store, stats, *, proposal=None):
    replies, reports, pending = [], [], None
    for name, args in selection.calls:
        if name == "read_shared_calendar":
            request = calendar_request(args, latest, context, version, today)
            reply, tools = await read_schedule(request, store, stats)
            pending = {"basis": version + 1, "date": request.date}
        elif name == "read_shared_plan":
            reply, tools = await read_plan(args, latest, context, version, today, store, stats)
        elif name == "validate_course":
            with stats.span("tools"):
                reply, tools = inspect_current_course(proposal)
        else:
            continue
        replies.append(reply)
        reports.extend(tools)
    return replies, reports, pending
