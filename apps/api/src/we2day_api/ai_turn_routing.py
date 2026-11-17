"""Small semantic router; argument extraction cannot change its chosen operation."""

import json
import re
import time
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import Field

from we2day_api.ai_dialogue import date_value
from we2day_api.ai_model import structured_parameters
from we2day_api.ai_place_policy import norm, relational_area
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_turn_contract import DateSpec, Strict, TurnPlan
from we2day_api.ai_wire import inference_usage, responses_inputs, responses_result
from we2day_api.prompt_bundle import PROMPT


class Route(Strict):
    kind: Literal[
        "date",
        "status",
        "help",
        "chat",
        "read",
        "search",
        "plan",
        "edit",
        "resume",
        "clarify",
        "cancel",
    ]
    continuation: bool = False
    value: str | None = Field(default=None, max_length=200)


async def classify(
    body, context, today, settings, client, budget, stats, deadline, proposal_exists=None
):
    pending = (context.get("turn_engine") or {}).get("pending") or (
        context.get("dialogue") or {}
    ).get("pending")
    state = {
        "today": today.isoformat(),
        "open_field": pending.get("field") if pending else None,
        "open_operation": pending.get("resume") if pending else None,
        "has_selected_places": bool(body.selected_places),
        "has_form": bool(body.brief),
        "has_plan_date": bool(context.get("date")),
        "has_region": bool(context.get("region")),
        "has_activity_goals": bool(context.get("activities")),
        "has_current_proposal": bool(body.proposal) if proposal_exists is None else proposal_exists,
    }
    latest = body.brief.message() if body.brief else body.messages[-1].content
    schema = Route.model_json_schema()
    schema["required"] = ["kind", "continuation", "value"]
    if not pending:
        # Resuming a nonexistent task is unavailable, not a second interpretation.
        schema["properties"]["continuation"] = {"type": "boolean", "enum": [False]}
        schema["properties"]["value"] = {"type": "null"}
        schema["properties"]["kind"]["enum"].remove("resume")
    request = {
        **structured_parameters(settings),
        "messages": [
            {"role": "system", "content": PROMPT.turn_route},
            {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
            {"role": "user", "content": latest},
        ],
        "max_tokens": 1536,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "we2day_route",
                "strict": True,
                "schema": schema,
            },
        },
    }
    request = responses_inputs(request, constrained=False)
    for attempt in range(2):
        if attempt:
            if (
                stats.counts.get("selection_repair_attempts")
                or stats.counts.get("model_calls", 0) >= 3
                or deadline - time.monotonic() < 2
                or budget.remaining() < 30
            ):
                break
            stats.counts["selection_repair_attempts"] = 1
            stats.stage("selection_repair")
            request["input"][0]["content"] += (
                "\nThe prior generation did not produce a valid completed routing object. "
                "Return ONLY kind, continuation and value for the SAME latest request/state. "
                "Do not answer the request, infer missing values or output analysis."
            )
        role = "selection_repair" if attempt else "selection"
        raw_input = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        stats.counts["model_calls"] += 1
        stats.counts["request_bytes"] += len(raw_input)
        try:
            with stats.inference(role):
                status, raw = await bounded_response(
                    client,
                    "POST",
                    f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/responses",
                    budget,
                    limit=12000,
                    seconds=min(25, max(1, deadline - time.monotonic())),
                    content=raw_input,
                    headers={
                        "Authorization": f"Bearer {settings.cloudflare_api_token}",
                        "Content-Type": "application/json",
                    },
                )
        except (httpx.HTTPError, TimeoutError) as error:
            raise HTTPException(503, "ai_unavailable") from error
        stats.counts["response_bytes"] += len(raw)
        if status == 429:
            raise HTTPException(429, "ai_provider_limited")
        if status != 200:
            raise HTTPException(503, "ai_unavailable")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Invalid provider envelope")
            if payload.get("success") is False:
                raise HTTPException(503, "ai_unavailable")
            result = payload.get("result", payload)
            if not isinstance(result, dict):
                raise ValueError("Invalid provider envelope")
            stats.usage(inference_usage(result), role=role)
            result = responses_result(result)
            choice = result["choices"][0]
            message = choice["message"]
            if choice.get("finish_reason") == "length" or message.get("tool_calls"):
                raise ValueError("Invalid route")
            route = Route.model_validate(json.loads(message["content"]))
            if route.continuation:
                if not pending or route.kind in {
                    "date",
                    "status",
                    "help",
                    "read",
                    "chat",
                    "cancel",
                }:
                    raise ValueError("Information cannot fulfill an open field")
                route = route.model_copy(update={"kind": "resume"})
            return route
        except (ValueError, KeyError, TypeError, IndexError) as error:
            stats.counts["selection_invalid"] = stats.counts.get("selection_invalid", 0) + 1
            if attempt:
                raise HTTPException(502, "ai_selection_failed") from error
    raise HTTPException(502, "ai_selection_failed")


def quoted_money(value):
    """Numeric units only, after the model chose a budget answer. No intent parsing."""
    compact = value.replace(",", "").replace(" ", "")
    if re.fullmatch(r"[0-9]+", compact):
        return int(compact)
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?[만천]?)+원?", compact):
        return None
    total = Decimal(0)
    previous = 10001
    for number, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)([만천]?)", compact.removesuffix("원")):
        scale = {"만": 10000, "천": 1000, "": 1}[unit]
        if scale >= previous:
            return None
        previous = scale
        total += Decimal(number) * scale
    return int(total) if total == int(total) else None


def ready_route(route, body, context, today):
    latest = body.brief.message() if body.brief else body.messages[-1].content
    if route.kind in {"status", "help"}:
        return TurnPlan(act="information", operation="answer", answer=route.kind)
    if route.kind == "cancel":
        return TurnPlan(act="request", operation="cancel", pending="resolve")
    if route.kind == "date":
        parsed, question = date_value(latest, today)
        if parsed and not question:
            return TurnPlan(
                act="information",
                operation="answer",
                answer="date",
                query_date=DateSpec(mode="absolute", value=parsed, source=latest),
            )
    pending = (context.get("turn_engine") or {}).get("pending") or (
        context.get("dialogue") or {}
    ).get("pending")
    if route.kind != "resume" or not pending:
        return None
    field = pending["field"]
    value = route.value
    if field == "region" and (body.selected_places or body.chosen_places) and not value:
        return TurnPlan(act="slot_answer", operation="resume", selected=bool(body.selected_places))
    if not value or norm(value) not in norm(latest):
        return None
    values = {}
    if field == "region" and len(value) <= 100 and not relational_area(value):
        values["region"] = value
    elif field == "budget":
        amount = quoted_money(value)
        if amount is None or amount > 1_000_000_000:
            return None
        values["budget"] = amount
    elif field == "date":
        parsed, question = date_value(value, today)
        if not parsed or question:
            return None
        values["date"] = {"mode": "absolute", "value": parsed, "source": value}
    elif field == "transport" and value in {"자동차", "대중교통", "도보"}:
        values["transport"] = value
    else:
        return None
    return TurnPlan.model_validate(
        {"act": "slot_answer", "operation": "resume", "delta": {"evidence": latest, **values}}
    )
