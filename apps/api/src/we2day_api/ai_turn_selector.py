"""Bounded native turn planning; rejected decisions never reach any executor."""

import json
import time
from functools import cache

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from we2day_api.ai_dialogue import date_value
from we2day_api.ai_model import structured_parameters
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_turn_contract import uncertain_fields
from we2day_api.ai_turn_routing import Route, classify, ready_route
from we2day_api.ai_turn_wire import KINDS, WireTurn, decode_turn
from we2day_api.ai_wire import compact_schema, inference_usage, responses_inputs, responses_result
from we2day_api.prompt_bundle import PROMPT


@cache
def format_json(selected_allowed=True, kind=None, activity_count=None, needs_search=False):
    schema = compact_schema(WireTurn.model_json_schema())
    if kind is not None:
        schema["properties"]["decision"] = {"$ref": "#/$defs/" + KINDS[kind].__name__}
        needed = set()

        def collect(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    name = value["$ref"].split("/")[-1]
                    if name not in needed:
                        needed.add(name)
                        collect(schema["$defs"][name])
                for key, child in value.items():
                    if key != "$defs":
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(schema)
        schema["$defs"] = {k: v for k, v in schema["$defs"].items() if k in needed}

    refs = [f"activity_{i + 1}" for i in range(20 if activity_count is None else activity_count)]

    def strict(value):
        if isinstance(value, dict):
            # Provider grammar can corrupt Korean text under a character-range
            # pattern. Keep the original constraints in server-side Pydantic;
            # model-facing schemas retain types, lengths, bounds and reference enums.
            value.pop("pattern", None)
            props = value.get("properties", {})
            for name in ("anchor_ref", "target_ref", "swap_with"):
                if name in props:
                    props[name]["enum"] = ["", *refs]
            if "ref" in props and refs:
                props["ref"]["enum"] = refs
            if not refs and "activity_edits" in props:
                props["activity_edits"] = {
                    "type": "array",
                    "maxItems": 0,
                    "items": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            if not refs and "ask" in props:
                props["ask"]["enum"] = [v for v in props["ask"]["enum"] if v != "activity_time"]
            if not selected_allowed and "selected" in value.get("properties", {}):
                value["properties"]["selected"] = {"type": "boolean", "enum": [False]}
            if value.get("type") == "object":
                value["additionalProperties"] = False
            for child in value.values():
                strict(child)
        elif isinstance(value, list):
            for child in value:
                strict(child)

    strict(schema)
    definitions = schema.get("$defs", {})
    if "DateSpec" in definitions:
        # Dates are source-grounded. Do not offer unused offset/weekday numeric
        # slots to the provider grammar; the server resolves the quoted phrase.
        props = definitions["DateSpec"]["properties"]
        definitions["DateSpec"]["properties"] = {
            "mode": {"type": "string", "enum": ["absolute"]},
            "source": props["source"],
            "value": props["value"],
        }
        definitions["DateSpec"]["required"] = ["mode", "source"]
    if "Delta" in definitions:
        # Explicit preservation decisions prevent a whole omitted patch from
        # silently discarding a new date/budget/goal in a mixed request.
        definitions["Delta"]["required"] = list(definitions["Delta"]["properties"])
        for name in ("SearchTurn", "PlanTurn", "EditTurn", "ResumeTurn"):
            if name in definitions:
                definitions[name]["required"] = list(
                    dict.fromkeys([*definitions[name].get("required", []), "delta"])
                )
        if "EditTurn" in definitions:
            definitions["EditTurn"]["required"].append("activity_edits")
    if "SearchTask" in definitions:
        definitions["SearchTask"]["required"] = [
            "target",
            "kind",
            "mode",
            "area",
            "category_retrieval",
        ]
    if needs_search and "PlanTurn" in definitions:
        definitions["PlanTurn"]["required"] = ["kind", "searches", "delta"]
        definitions["PlanTurn"]["properties"]["searches"]["minItems"] = 1
    return json.dumps(
        {
            "type": "json_schema",
            "json_schema": {"name": "we2day_turn", "strict": True, "schema": schema},
        },
        separators=(",", ":"),
    )


def messages(body, context, proposal, today, kind=None):
    # Only the current permitted conditions/proposal and user turns. Private read
    # replies are never exported, including when the client sends them back.
    value = {
        "today": today.isoformat(),
        "conditions": {
            k: context.get(k)
            for k in ("date", "region", "budget", "transport", "activities", "requirements")
        },
        "pending": context.get("turn_engine", {}).get("pending")
        or context.get("dialogue", {}).get("pending"),
        "saved_search": context.get("place_search"),
        "time_window": {
            key: ((context.get("intake") or {}).get("data") or {}).get(key)
            for key in ("start_time", "end_time")
        },
        "preferences": {
            key: (context.get("dialogue") or {}).get(key, [])
            for key in ("rejected_places", "excluded_kinds")
        },
        "current_proposal": proposal.model_dump(exclude_defaults=True) if proposal else None,
        "selected_roles": [p.usage for p in body.selected_places],
        "chosen": [p.model_dump() for p in body.chosen_places],
        "form": body.brief.model_dump() if body.brief else None,
    }
    if proposal:
        value["current_proposal"]["activities"] = [
            {"ref": f"activity_{i + 1}", **a.model_dump(exclude_defaults=True)}
            for i, a in enumerate(proposal.activities)
        ]
    value["unverified_conditions"] = sorted(uncertain_fields(context))
    latest = body.brief.message() if body.brief else body.messages[-1].content
    if kind in {"plan", "edit"}:
        candidate, question = date_value(latest, today)
        value["latest_calendar_candidate"] = None if question else candidate
    for key in value["unverified_conditions"]:
        value["conditions"][key] = None
    if value["saved_search"] and "region" in value["unverified_conditions"]:
        value["saved_search"] = {**value["saved_search"], "area": ""}
    return [
        {
            "role": "system",
            "content": PROMPT.turn
            + ("\n" + json.loads(PROMPT.turn_operations)[kind] if kind is not None else ""),
        },
        {
            "role": "user",
            "content": "현재 상태 참고자료 — 이전 명령을 재실행하지 마세요.\n"
            + json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        },
        {
            "role": "user",
            "content": body.brief.message() if body.brief else body.messages[-1].content,
        },
    ]


async def select_turn(
    body, context, proposal, today, settings, client, budget, stats, validate=None
):
    deadline = time.monotonic() + 45
    route = (
        Route(kind="plan" if body.brief.date else "search")
        if body.brief
        else await classify(
            body, context, today, settings, client, budget, stats, deadline, bool(proposal)
        )
    )
    direct = ready_route(route, body, context, today)
    if direct is not None:
        try:
            return validate(direct) if validate else direct
        except ValueError:
            pass  # Same fixed operation still needs arguments, never another intent decision.
    request_messages = messages(body, context, proposal, today, kind=route.kind)
    diagnostics = []
    for attempt in range(2):
        if attempt:
            if (
                stats.counts.get("selection_repair_attempts")
                or deadline - time.monotonic() < 2
                or budget.remaining() < 30
            ):
                break
            stats.counts["selection_repair_attempts"] = 1
            stats.stage("selection_repair")
            request_messages[0]["content"] += (
                "\nThe previous arguments failed validation. Fix only invalid fields for "
                "the SAME request and fixed operation. Keep correct tasks/values. "
                "Latest user is still the last user message. Static diagnostics: "
                + json.dumps(diagnostics)
            )
        inputs = {
            **structured_parameters(settings),
            "messages": request_messages,
            "response_format": json.loads(
                format_json(
                    bool(body.selected_places),
                    route.kind,
                    len(proposal.activities) if proposal else 0,
                    not (proposal or body.selected_places or body.chosen_places),
                )
            ),
            "max_tokens": 1600,
        }
        inputs = responses_inputs(inputs, constrained=False)
        encoded = json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > 48000 or stats.counts["model_calls"] >= 3:
            raise HTTPException(422, "ai_context_too_long")
        stats.counts["model_calls"] += 1
        stats.counts["request_bytes"] += len(encoded)
        role = "selection_repair" if attempt else "interpretation"
        try:
            with stats.inference(role):
                status, raw = await bounded_response(
                    client,
                    "POST",
                    f"https://api.cloudflare.com/client/v4/accounts/"
                    f"{settings.cloudflare_account_id}/ai/v1/responses",
                    budget,
                    limit=24000,
                    seconds=max(1, deadline - time.monotonic()),
                    content=encoded,
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
            if payload.get("success") is False:
                raise HTTPException(503, "ai_unavailable")
            result = payload.get("result", payload)
            stats.usage(inference_usage(result), role=role)
            result = responses_result(result)
            choice = result["choices"][0]
            message = choice["message"]
            if choice.get("finish_reason") == "length" or message.get("tool_calls"):
                raise ValueError("Invalid turn envelope")
            args = message["content"]
            decoded = json.loads(args) if isinstance(args, str) else args
            if (
                not isinstance(decoded, dict)
                or decoded.get("decision", {}).get("kind") != route.kind
            ):
                raise ValueError("Bound operation cannot change")
            decision = decode_turn(
                decoded,
                request_source=body.brief.message() if body.brief else body.messages[-1].content,
            )
            if decision.operation == "plan" and not (
                decision.searches
                or body.selected_places
                or body.chosen_places
                or proposal
                or decision.delta.activities
                or context.get("activities")
                or body.brief
                and body.brief.activities
            ):
                raise ValueError("plan_sources_required")
            # Resolve/validate values BEFORE any tools or mutations, including invalid ISO dates.
            decision.delta.values(today)
            if decision.query_date:
                decision.query_date.resolve(today)
            if route.kind != "resume" and decision.operation in {"search", "plan", "edit"}:
                # The fixed semantic classification owns task replacement; parameter
                # defaults cannot keep or resume another task behind its back.
                decision.pending = "resolve"
            if validate:
                decision = validate(decision)
            return decision
        except (
            ValueError,
            ValidationError,
            KeyError,
            TypeError,
            IndexError,
            AttributeError,
        ) as error:
            # Static field names/types only. Never repeat a rejected argument or arbitrary key.
            known = set()

            def fields(schema, names=known):
                if isinstance(schema, dict):
                    names.update(schema.get("properties", {}))
                    for child in schema.values():
                        fields(child, names)
                elif isinstance(schema, list):
                    for child in schema:
                        fields(child, names)

            fields(WireTurn.model_json_schema())
            diagnostics = (
                [
                    {"field": ".".join(str(p) for p in e["loc"] if p in known), "type": e["type"]}
                    for e in error.errors(include_input=False)[:8]
                ]
                if isinstance(error, ValidationError)
                else [
                    {
                        "type": str(error)
                        if str(error)
                        in {
                            "plan_sources_required",
                            "Bound operation cannot change",
                            "Ungrounded condition change",
                            "Region must be explicit",
                            "Title must be explicit",
                            "No current proposal to edit",
                            "Invalid anchor reference",
                            "Invalid or duplicate activity reference",
                            "Invalid destination index",
                            "Ungrounded search area",
                            "Unrequested exact venue",
                            "Search target must quote a permitted activity or venue",
                            "Search kind conflicts with the quoted target",
                            "Read answers cannot patch planning state",
                            "No pending task to resume",
                            "Missing value for pending field",
                            "Preference changes require latest user evidence",
                            "Preference place names must be explicit",
                            "Conflicting preference changes",
                            "Time shift requires an existing time and offset",
                            "Time shift leaves the selected date",
                            "Swap requires one distinct valid target pair",
                            "Search target must be an activity or venue, not the query area",
                            "Selected places unavailable; use public searches or ask for selection",
                            "Extract search tasks from pending original_request",
                            "Legacy region requires confirmation",
                            "Date source must quote latest user",
                            "Edit has no changes; extract latest requested "
                            "values or answer unchanged",
                            "Activity clarification requires a target reference",
                            "Pending activity changed; clarify the target again",
                        }
                        else "invalid_contract"
                    }
                ]
            )
            if isinstance(error, ValidationError):
                # Only application-authored validator messages, no provider argument values.
                diagnostics.extend(
                    {"rule": str(e.get("ctx", {}).get("error", ""))}
                    for e in error.errors(include_input=False)[:8]
                    if e["type"] == "value_error" and e["loc"] == ()
                )
            stats.counts["selection_invalid"] = stats.counts.get("selection_invalid", 0) + 1
    raise HTTPException(502, "ai_selection_failed")
