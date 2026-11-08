"""Bounded native selection validation and fixed, content-free diagnostics."""

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

ERRORS = frozenset(
    {
        "invalid_json",
        "invalid_shape",
        "truncated",
        "missing_calls",
        "too_many_calls",
        "unknown_tool",
        "selection_required",
        "invalid_arguments",
        "conflicting_calls",
    }
)
REPAIRABLE = ERRORS - {"unknown_tool", "selection_required", "too_many_calls"}
FIELDS = frozenset(
    {
        "query",
        "mode",
        "name",
        "kind",
        "area",
        "anchor_ref",
        "date",
        "plan_id",
        "title",
        "field",
        "targets",
        "operation",
        "city",
    }
)


@dataclass
class Selection:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    invalid: bool = False
    invalid_reason: str = ""
    invalid_fields: tuple[str, ...] = ()


def failure(reason, fields=()):
    assert reason in ERRORS
    return Selection(
        invalid=True, invalid_reason=reason, invalid_fields=tuple(sorted(set(fields) & FIELDS))
    )


def parse_selection(raw, models, capabilities, *, selected):
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return failure("invalid_json")
    try:
        result = payload.get("result", payload)
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            return failure("truncated")
        calls = choice["message"].get("tool_calls") or []
        if not isinstance(calls, list):
            return failure("invalid_shape")
        if not calls:
            return failure("missing_calls")
        if len(calls) > 4:
            return failure("too_many_calls")
        parsed, seen = Selection(), set()
        for call in calls:
            fn = call["function"]
            name = fn["name"]
            if not isinstance(name, str) or name not in models:
                return failure("unknown_tool")
            if capabilities[name].selected_required and not selected:
                return failure("selection_required")
            arguments = fn.get("arguments", {})
            try:
                args = (
                    models[name].model_validate_json(arguments)
                    if isinstance(arguments, str)
                    else models[name].model_validate(arguments)
                ).model_dump()
            except ValidationError as error:
                errors = error.errors(include_url=False, include_input=False, include_context=False)
                reason = (
                    "invalid_json"
                    if any(e["type"] == "json_invalid" for e in errors)
                    else "invalid_arguments"
                )
                fields = [e["loc"][0] for e in errors if e["loc"] and isinstance(e["loc"][0], str)]
                return failure(reason, fields)
            key = name, json.dumps(args, sort_keys=True)
            if key not in seen:
                seen.add(key)
                parsed.calls.append((name, args))
        if len(parsed.calls) > 1 and any(
            name in {"ask_user", "continue_planning", "propose_course"} for name, _ in parsed.calls
        ):
            return failure("conflicting_calls")
        return parsed
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return failure("invalid_shape")


def record_selection(stats, selection, *, attempt, names):
    """Never record model-owned strings, exception messages, arguments or values."""
    counts = stats.counts
    counts["selection_attempts"] = counts.get("selection_attempts", 0) + 1
    if selection.invalid:
        if attempt == 0:
            counts["selection_first_invalid"] = 1
        counts["selection_invalid"] = counts.get("selection_invalid", 0) + 1
        key = "selection_error_" + selection.invalid_reason
        counts[key] = counts.get(key, 0) + 1
        for name in selection.invalid_fields:
            key = "selection_field_" + name
            counts[key] = counts.get(key, 0) + 1
    else:
        counts["selection_valid"] = 1
        counts["selection_first_valid" if attempt == 0 else "selection_repaired"] = 1
        for name, _ in selection.calls:
            if name in names:
                counts["selection_tool_" + name] = 1
