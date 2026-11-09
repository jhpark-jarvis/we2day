"""One bounded native tool-selection call, before any shared-business read."""

import json
import time
from datetime import date
from typing import Annotated

import httpx
from fastapi import HTTPException
from pydantic import ConfigDict, Field

from we2day_api.ai_capabilities import (
    BY_NAME,
    CalendarReadArguments,
    ClarifyArguments,
    CourseProposalArguments,
    PlanReadArguments,
    batch_definition,
)
from we2day_api.ai_control import Action, apply_action
from we2day_api.ai_control import prepare as prepare_control
from we2day_api.ai_dialogue import new_task, social_turn
from we2day_api.ai_location import pending_location
from we2day_api.ai_model import model_parameters
from we2day_api.ai_place_policy import SearchArguments, norm, relational_area
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_saved_schedule import schedule_date
from we2day_api.ai_search_spec import place_name, referenced_anchor
from we2day_api.ai_selection import REPAIRABLE, Selection, parse_selection, record_selection
from we2day_api.ai_tools import EmptyArguments, WeatherArguments
from we2day_api.prompt_bundle import PROMPT


class PlaceSelectionArguments(SearchArguments):
    # Older stored/internal selections still parse query-only. New model requests
    # must supply all targets in one call, independent of parallel-call support.
    model_config = ConfigDict(
        extra="forbid", strict=True, json_schema_extra={"required": ["query", "targets"]}
    )
    query: str = Field(
        min_length=1,
        max_length=50,
        description=(
            "검색할 장소·음식·시설 이름의 짧은 명사구. 먹을/마실/갈 만한 곳·요청 동사·지역 제외."
        ),
    )
    anchor_ref: str = Field(
        default="",
        pattern=r"^(?:activity_[1-8])?$",
        description="현재 요청이 참조한 current_proposal 활동의 ref. 지역명 아님. 모호하면 빈 값.",
    )
    targets: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "현재 요청의 장소·음식·시설 명사구 전부. "
            "여러 목표는 각각 원소로, query는 첫 원소. 정확명은 이름 하나만."
        ),
    )


MODELS = {
    "read_shared_calendar": CalendarReadArguments,
    "read_shared_plan": PlanReadArguments,
    "search_places": PlaceSelectionArguments,
    "lookup_selected_places": EmptyArguments,
    "get_weather": WeatherArguments,
    "propose_course": CourseProposalArguments,
    "continue_planning": EmptyArguments,
    "ask_user": ClarifyArguments,
    "validate_course": EmptyArguments,
}


def direct_request(body, context, proposal, today):
    """Reuse typed current-task answers and complete edits before free-form selection."""
    location = pending_location(context, body.version)
    social = social_turn(body.messages[-1].content)
    if (not proposal and not location and not social) or body.brief:
        return None
    decision = prepare_control(body, context, proposal, today)
    directive = decision.directive
    if social and directive.reply and not decision.interpret and not directive.allowed_tools:
        return decision
    if location and decision.reason == "conditions" and not decision.interpret:
        return decision
    if (
        directive.intent == "edit"
        and (directive.plan or decision.reason == "conditions" and directive.reply)
        and not decision.interpret
        and not directive.allowed_tools
    ):
        return decision
    return None


def selection_messages(body, context, proposal, today):
    # Assistant replies may contain private server-rendered schedules. Only user
    # requests and the already-authorized current planning state enter this selector.
    requested = schedule_date(body.messages[-1].content, context, body.version, today)
    location = pending_location(context, body.version)
    current = None
    if proposal:
        current = {
            "title": proposal.title,
            "activities": [
                {
                    "ref": f"activity_{i + 1}",
                    "title": a.title,
                    "time": a.time,
                    "place": place_name(a),
                }
                for i, a in enumerate(proposal.activities)
            ],
        }
        for field in ("date", "budget"):
            if getattr(proposal, field) != context.get(field):
                current[field] = getattr(proposal, field)
    value = {
        "today": today.isoformat(),
        "resolved_request_date": requested.date,
        "request": body.messages[-1].content,
        "previous_requests": [m.content[:1000] for m in body.messages[:-1] if m.role == "user"][
            -5:
        ],
        "conditions": {
            k: context.get(k) for k in ("date", "region", "activities", "budget", "transport")
        },
        "pending": context.get("dialogue", {}).get("pending")
        if context.get("dialogue", {}).get("turn_version") == body.version
        else None,
        "saved_read_date": (context.get("schedule_read") or {}).get("date")
        if (context.get("schedule_read") or {}).get("basis") == body.version
        else None,
        "selected_count": len(body.selected_places),
        "pending_place_targets": [t.query for t in location.search.targets]
        if location and location.search
        else [],
        "current_proposal": current,
    }
    return [
        {"role": "system", "content": PROMPT.route},
        {"role": "user", "content": json.dumps(value, ensure_ascii=False, separators=(",", ":"))},
    ]


async def _select_once(
    body, context, proposal, today, settings, client, budget, stats, *, seconds, repair=None
):
    inputs = {
        **model_parameters(settings),
        "messages": selection_messages(body, context, proposal, today),
        "tools": [batch_definition(MODELS, selected=bool(body.selected_places))],
        "tool_choice": "required",
        "temperature": 0,
        "max_tokens": 768,
    }
    if repair:
        # Fixed categories/field names only; never feed rejected arguments back to the model.
        inputs["messages"].append(
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "selection_retry": repair.invalid_reason,
                        "invalid_fields": repair.invalid_fields,
                        "instruction": (
                            "Return a valid selection for the SAME current request. "
                            "Follow the supplied schemas and permitted combinations. "
                            "Do not invent missing user facts."
                        ),
                    }
                ),
            }
        )
    encoded = json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 48000 or stats.counts.get("model_calls", 0) >= 3:
        raise HTTPException(422, "ai_context_too_long")
    stats.counts["model_calls"] += 1
    stats.counts["request_bytes"] += len(encoded)
    try:
        with stats.inference("selection_repair" if repair else "selection"):
            if repair:
                stats.stage("selection_repair")
            status, raw = await bounded_response(
                client,
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/chat/completions",
                budget,
                limit=16000,
                seconds=seconds,
                content=encoded,
                headers={
                    "Authorization": f"Bearer {settings.cloudflare_api_token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as error:
        raise HTTPException(503, "ai_unavailable") from error
    stats.counts["response_bytes"] += len(raw)
    if status == 429:
        try:
            p = json.loads(raw)
            errors = p.get("errors", []) + (
                [p["error"]] if isinstance(p.get("error"), dict) else []
            )
            limited = any(str(e.get("code")) == "3036" for e in errors)
        except (ValueError, TypeError, AttributeError):
            limited = False
        raise HTTPException(429, "ai_provider_limited" if limited else "ai_provider_busy")
    if status != 200:
        raise HTTPException(503, "ai_unavailable")
    try:
        payload = json.loads(raw)
        result = payload.get("result", payload)
        if isinstance(result, dict):
            stats.usage(result, role="selection_repair" if repair else "selection")
    except (ValueError, TypeError, AttributeError):
        pass
    return parse_selection(raw, MODELS, BY_NAME, selected=bool(body.selected_places))


async def select(body, context, proposal, today, settings, client, budget, stats) -> Selection:
    deadline = time.monotonic() + 18
    selection = await _select_once(
        body, context, proposal, today, settings, client, budget, stats, seconds=18
    )
    record_selection(stats, selection, attempt=0, names=MODELS)
    # Leave one of the three calls and its normal completion time for the actual task.
    if (
        selection.invalid
        and selection.invalid_reason in REPAIRABLE
        and stats.counts.get("model_calls", 0) < 2
        and deadline - time.monotonic() >= 2
        and budget.remaining() >= 30
    ):
        stats.counts["selection_repair_attempts"] = 1
        stats.stage("selection_repair")
        selection = await _select_once(
            body,
            context,
            proposal,
            today,
            settings,
            client,
            budget,
            stats,
            seconds=deadline - time.monotonic(),
            repair=selection,
        )
        record_selection(stats, selection, attempt=1, names=MODELS)
    if selection.invalid:
        stats.counts["selection_failed"] = 1
    return selection


def apply_selection(selection, decision, latest):
    """Reuse existing grounded SearchSpec/state reducers, not a second interpreter."""
    searches = [a for n, a in selection.calls if n == "search_places"]
    proposal = [a for n, a in selection.calls if n == "propose_course"]
    if not searches and not proposal:
        return
    if proposal:
        action = Action.model_validate(proposal[0])
        if action.operation != "plan":
            raise ValueError("Only a current proposal may be requested")
    else:
        targets, area, anchor = [], "", ""
        for args in searches:
            ref = args.get("anchor_ref", "")
            if ref:
                index, required = referenced_anchor(latest, decision.proposal)
                if not required or index is None or ref != f"activity_{index + 1}":
                    raise ValueError("Ungrounded activity reference")
                if anchor and anchor != ref:
                    raise ValueError("Conflicting anchors")
                anchor = ref
            if relational_area(args["area"]):
                args = {**args, "area": ""}
            query = (
                (args["name"] or args["query"]) if args["mode"] == "exact_name" else args["query"]
            )
            if args["mode"] == "exact_name" and args["area"]:
                # A city's syllables inside a venue name are not a user-supplied region.
                outside_name = latest.replace(query, "") + " " + decision.context.get("region", "")
                if norm(args["area"]) not in norm(outside_name):
                    args = {**args, "area": ""}
            requested = args.get("targets") or [query]
            if args["mode"] == "exact_name":
                if len(requested) != 1:
                    raise ValueError("Exact name requires one target")
                requested = [query]
            if args["area"]:
                if area and norm(area) != norm(args["area"]):
                    raise ValueError("Conflicting areas")
                area = args["area"]
            for target in requested:
                target = target.replace(args["area"], "").strip() if args["area"] else target
                if not target or len(target) > 50:
                    raise ValueError("Invalid target")
                if target not in targets:
                    targets.append(target)
        pending = (decision.context.get("dialogue") or {}).get("pending") or {}
        resume_plan = (
            len(selection.calls) == 1
            and pending.get("field") == "target"
            and pending.get("resume") == "plan"
            and decision.directive.intent == "plan"
            and not new_task(latest)
        )
        # Tool selection identifies the target; a short answer must not replace
        # the server-owned purpose of the current, version-validated question.
        action = Action(
            operation="plan" if resume_plan else "search",
            area=area,
            targets=targets,
            anchor_ref=anchor,
        )
    apply_action(decision, latest, action)
    if (
        searches
        and action.operation == "plan"
        and decision.directive.intent == "plan"
        and decision.directive.slots.get("place_search")
    ):
        decision.directive.slots["activities"] = [
            t["query"] for t in decision.directive.slots["place_search"]["targets"]
        ]
    decision.interpret = False


def valid_weather(args, latest, context, today):
    from we2day_api.ai_dialogue import date_value

    city = norm(args["city"])
    known = norm(latest + " " + (context.get("region") or ""))
    expected, question = date_value(latest, today)
    target = expected or context.get("date") or today.isoformat()
    try:
        date.fromisoformat(args["date"])
    except ValueError:
        return False
    return bool(city and city in known and not question and args["date"] == target)
