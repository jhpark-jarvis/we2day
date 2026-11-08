"""One bounded native tool-selection call, before any shared-business read."""

import json
from dataclasses import dataclass, field
from datetime import date

import httpx
from fastapi import HTTPException
from pydantic import Field, ValidationError

from we2day_api.ai_capabilities import (
    BY_NAME,
    CalendarReadArguments,
    ClarifyArguments,
    CourseProposalArguments,
    PlanReadArguments,
    definitions,
)
from we2day_api.ai_control import Action, apply_action
from we2day_api.ai_control import prepare as prepare_control
from we2day_api.ai_location import pending_location
from we2day_api.ai_model import model_parameters
from we2day_api.ai_place_policy import SearchArguments, norm
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_saved_schedule import schedule_date
from we2day_api.ai_tools import EmptyArguments, WeatherArguments
from we2day_api.prompt_bundle import PROMPT


class PlaceSelectionArguments(SearchArguments):
    query: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "검색할 장소·음식·시설 이름의 짧은 명사구. 먹을/마실/갈 만한 곳·요청 동사·지역 제외."
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
}


@dataclass
class Selection:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    invalid: bool = False
    invalid_reason: str = ""


def direct_request(body, context, proposal, today):
    """Reuse typed current-task answers and complete edits before free-form selection."""
    location = pending_location(context, body.version)
    if (not proposal and not location) or body.brief:
        return None
    decision = prepare_control(body, context, proposal, today)
    directive = decision.directive
    if location and decision.reason == "conditions" and not decision.interpret:
        return decision
    if (
        directive.intent == "edit"
        and directive.plan
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
        "current_proposal": {
            "title": proposal.title,
            "date": proposal.date,
            "budget": proposal.budget,
            "activities": [
                {"title": a.title, "time": a.time, "place": a.place} for a in proposal.activities
            ],
        }
        if proposal
        else None,
    }
    return [
        {"role": "system", "content": PROMPT.route},
        {"role": "user", "content": json.dumps(value, ensure_ascii=False)},
    ]


async def select(body, context, proposal, today, settings, client, budget, stats):
    inputs = {
        **model_parameters(settings),
        "messages": selection_messages(body, context, proposal, today),
        "tools": definitions(MODELS, selected=bool(body.selected_places)),
        "tool_choice": "required",
        "temperature": 0,
        "max_tokens": 768,
    }
    encoded = json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 48000 or stats.counts.get("model_calls", 0) >= 3:
        raise HTTPException(422, "ai_context_too_long")
    stats.counts["model_calls"] += 1
    stats.counts["request_bytes"] += len(encoded)
    try:
        with stats.span("model"):
            status, raw = await bounded_response(
                client,
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/chat/completions",
                budget,
                limit=16000,
                seconds=18,
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
        stats.usage(result)
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Incomplete capability selection")
        calls = choice["message"].get("tool_calls") or []
        if not 1 <= len(calls) <= 4:
            raise ValueError("A typed tool selection is required")
        selected = Selection()
        seen = set()
        for call in calls:
            fn = call["function"]
            name, arguments = fn["name"], fn.get("arguments", {})
            if name not in MODELS or (BY_NAME[name].selected_required and not body.selected_places):
                raise ValueError("Capability unavailable")
            args = (
                MODELS[name].model_validate_json(arguments)
                if isinstance(arguments, str)
                else MODELS[name].model_validate(arguments)
            ).model_dump()
            key = name, json.dumps(args, sort_keys=True)
            if key not in seen:
                seen.add(key)
                selected.calls.append((name, args))
        # A route cannot both ask/continue and silently execute unrelated work.
        if len(selected.calls) > 1 and any(
            n in {"ask_user", "continue_planning", "propose_course"} for n, _ in selected.calls
        ):
            raise ValueError("Conflicting task selection")
        return selected
    except ValidationError:
        stats.counts["selection_invalid"] = 1
        return Selection(invalid=True, invalid_reason="arguments")
    except (ValueError, TypeError, KeyError, IndexError):
        stats.counts["selection_invalid"] = 1
        return Selection(invalid=True, invalid_reason="shape")


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
        targets, area = [], ""
        for args in searches:
            query = (
                (args["name"] or args["query"]) if args["mode"] == "exact_name" else args["query"]
            )
            if args["mode"] == "exact_name" and args["area"]:
                # A city's syllables inside a venue name are not a user-supplied region.
                outside_name = latest.replace(query, "") + " " + decision.context.get("region", "")
                if norm(args["area"]) not in norm(outside_name):
                    args = {**args, "area": ""}
            if args["area"]:
                if area and norm(area) != norm(args["area"]):
                    raise ValueError("Conflicting areas")
                area = args["area"]
                query = query.replace(area, "").strip()
            if not query or len(query) > 50:
                raise ValueError("Invalid target")
            targets.append(query)
        action = Action(operation="search", area=area, targets=targets)
    apply_action(decision, latest, action)
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
