"""Lossless validation constraints with compact, static model-facing schema metadata."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

MAPS = {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
SCHEMAS = {
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "propertyNames",
    "contains",
    "not",
    "if",
    "then",
    "else",
}
LISTS = {"anyOf", "oneOf", "allOf", "prefixItems"}


def compact_schema(schema):
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key == "default" and (
            value in (None, "", []) or "const" in schema and value == schema["const"]
        ):
            continue
        if key in MAPS and isinstance(value, dict):
            # Property names such as title/description are data, not schema metadata.
            result[key] = {name: compact_schema(child) for name, child in value.items()}
        elif key in SCHEMAS:
            result[key] = compact_schema(value)
        elif key in LISTS and isinstance(value, list):
            result[key] = [compact_schema(child) for child in value]
        else:
            result[key] = deepcopy(value)
    return result


def inline_schema(schema):
    """Expand local refs for providers whose tool renderer cannot resolve $defs.

    Only application-authored, acyclic schemas are accepted. Validation remains
    in the original Pydantic models; this changes representation, not constraints.
    """
    definitions = schema.get("$defs", {})

    def expand(value, stack=()):
        if isinstance(value, list):
            return [expand(v, stack) for v in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/$defs/") or ref in stack:
                raise ValueError("Unsupported schema reference")
            target = definitions[ref.removeprefix("#/$defs/")]
            return expand(
                {**target, **{k: v for k, v in value.items() if k != "$ref"}}, (*stack, ref)
            )
        return {k: expand(v, stack) for k, v in value.items() if k != "$defs"}

    return compact_schema(expand(schema))


def workers_ai_inputs(inputs):
    """Use native Workers AI's bare JSON Schema at the inference boundary.

    Internal immutable schema templates retain their descriptive envelope. No
    request values are cached, and schema/type/effect validation stays on server.
    """
    result = deepcopy(inputs)
    fmt = result.get("response_format")
    if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
        packed = fmt.get("json_schema")
        if isinstance(packed, dict) and "schema" in packed:
            schema = packed["schema"]
            if not isinstance(schema, dict):
                raise ValueError("Invalid application response schema")
            name = packed.get("name")
            if name and "title" not in schema:
                schema["title"] = name
            if packed.get("description") and "description" not in schema:
                schema["description"] = packed["description"]
            fmt["json_schema"] = schema
    return result


def responses_inputs(inputs, *, constrained=True):
    """Fixed-provider structured inference with separate reasoning and final output.

    No remote conversation or background job is created. Tool execution stays
    in the application, and the caller's inference/deadline budget is unchanged.
    """
    result = deepcopy(inputs)
    fmt = result.pop("response_format", {})
    packed = fmt.get("json_schema", {})
    if fmt.get("type") != "json_schema" or not isinstance(packed.get("schema"), dict):
        raise ValueError("Structured response schema required")
    if result.get("tools") or result.get("tool_choice"):
        raise ValueError("Structured inference cannot execute provider tools")
    result["input"] = result.pop("messages")
    # Decoding constraints are not a substitute for explaining the field
    # contract to the model. Use the SAME schema, never a second handwritten DTO.
    contract = json.dumps(
        presentation_schema(packed["schema"]), ensure_ascii=False, separators=(",", ":")
    )
    guidance = "\nOutput field contract (application schema; return JSON only):\n" + contract
    if result["input"] and result["input"][0].get("role") == "system":
        result["input"][0]["content"] += guidance
    else:
        result["input"].insert(0, {"role": "system", "content": guidance.strip()})
    result["max_output_tokens"] = result.pop("max_tokens")
    result["reasoning"] = {"effort": result.pop("reasoning_effort")}
    result["text"] = {
        "format": {"type": "json_schema", **packed} if constrained else {"type": "text"}
    }
    result["store"], result["stream"] = False, False
    return result


def presentation_schema(schema):
    """Small model-readable field semantics; full constraints remain in text.format."""
    retained = {
        "type",
        "description",
        "$ref",
        "const",
        "enum",
        "required",
        "additionalProperties",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "uniqueItems",
        "multipleOf",
    }
    if isinstance(schema, list):
        return [presentation_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key in MAPS and isinstance(value, dict):
            result[key] = {name: presentation_schema(child) for name, child in value.items()}
        elif key in retained:
            result[key] = deepcopy(value)
        elif key in SCHEMAS or key in LISTS:
            result[key] = presentation_schema(value)
    return result


def validate_json_schema(value, schema):
    """Enforce the complete application-generated contract before any effects.

    Local references only: inference output cannot supply a schema or cause a
    reference fetch. Pydantic and source/effect checks still run afterwards.
    """
    pending = [schema]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if "$ref" in item and not item["$ref"].startswith("#/"):
                raise ValueError("External schema references are not allowed")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise ValueError("Invalid structured response schema")


def inference_usage(result):
    """Keep measured token accounting across both fixed-provider protocols."""
    usage = result.get("usage") or {}
    if "input_tokens" in usage or "output_tokens" in usage:
        return {
            "usage": {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            }
        }
    return result


def responses_result(result):
    """Only one completed assistant message may supply the final JSON.

    Reasoning items are discarded, never interpreted as text or model actions.
    Incomplete/refused/tool/unknown outputs cannot mutate application state.
    """
    if result.get("status") != "completed" or result.get("incomplete_details"):
        raise ValueError("Incomplete structured response")
    output = result.get("output")
    if not isinstance(output, list):
        raise ValueError("Missing structured outputs")
    messages = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError("Invalid structured output item")
        if item.get("type") == "reasoning":
            continue
        if (
            item.get("type") != "message"
            or item.get("role") != "assistant"
            or item.get("status") != "completed"
        ):
            raise ValueError("Unexpected structured output")
        content = item.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("Missing structured output text")
        if any(
            not isinstance(c, dict)
            or c.get("type") != "output_text"
            or not isinstance(c.get("text"), str)
            for c in content
        ):
            raise ValueError("Refused or invalid structured output")
        messages.append("".join(c["text"] for c in content))
    if len(messages) != 1 or not messages[0].strip():
        raise ValueError("One final structured message required")
    return {
        "usage": inference_usage(result).get("usage", {}),
        "choices": [{"message": {"content": messages[0]}, "finish_reason": "stop"}],
    }
