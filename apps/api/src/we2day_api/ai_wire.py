"""Lossless validation constraints with compact, static model-facing schema metadata."""

from copy import deepcopy

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
