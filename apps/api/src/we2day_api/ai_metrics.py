"""Bounded aggregation of numeric ai_run logs; never returns log contents."""

import argparse
import json
import math
import re
import sys
from collections import Counter

COUNTERS = {
    "model_calls",
    "tool_calls",
    "server_responses",
    "request_bytes",
    "response_bytes",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "search_calls",
    "search_errors",
    "search_successes",
    "search_empty",
    "search_candidates",
    "schema_repairs",
    "scope_blocks",
    "selected_count",
    "planned_tools",
    "executed_tools",
    "control_version",
    "optional_normalizations",
}
CATEGORIES = {
    "ai_timeout",
    "ai_provider_busy",
    "ai_provider_limited",
    "ai_rate_limited",
    "ai_unavailable",
    "ai_invalid_response",
    "ai_context_too_long",
    "version_conflict",
}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 1)


def aggregate(lines, *, limit=100_000):
    groups, ignored, accepted, truncated = {}, 0, 0, False
    for number, line in enumerate(lines):
        if number >= limit:
            truncated = True
            break
        if len(line) > 65536 or "ai_run " not in line:
            ignored += 1
            continue
        try:
            value = json.loads(line.split("ai_run ", 1)[1])
            if not isinstance(value, dict):
                raise ValueError
            version, status = value.get("version"), value.get("status")
            if not isinstance(version, str) or not re.fullmatch(
                r"we2-ai-\d{4}-\d{2}-\d{2}-v\d{1,4}", version
            ):
                raise ValueError
            if not (
                status in {"ok", "timeout", "cancelled"}
                if isinstance(status, str)
                else type(status) is int and 400 <= status <= 599
            ):
                raise ValueError
            if version not in groups and len(groups) >= 32:
                raise ValueError
            group = groups.setdefault(
                version,
                {
                    "statuses": Counter(),
                    "counts": Counter(),
                    "observations": Counter(),
                    "ms": [],
                    "errors": Counter(),
                },
            )
            group["statuses"][str(status)] += 1
            for key in COUNTERS:
                count = value.get(key)
                if type(count) is int and 0 <= count <= 2_147_483_647:
                    group["counts"][key] += count
                    group["observations"][key] += 1
            elapsed = value.get("total_ms")
            if type(elapsed) in {float, int} and math.isfinite(elapsed) and 0 <= elapsed <= 300_000:
                group["ms"].append(elapsed)
            category = value.get("error_category")
            if isinstance(category, str) and category in CATEGORIES:
                group["errors"][category] += 1
            accepted += 1
        except (ValueError, TypeError):
            ignored += 1
    result = {}
    for version, group in sorted(groups.items()):
        statuses, counts = dict(group["statuses"]), dict(group["counts"])
        requests = sum(statuses.values())
        searches = counts.get("search_calls", 0)
        result[version] = {
            "requests": requests,
            "statuses": statuses,
            "success_rate": round(statuses.get("ok", 0) / requests, 4),
            "latency_ms": {
                "observations": len(group["ms"]),
                "p50": percentile(group["ms"], 0.5),
                "p95": percentile(group["ms"], 0.95),
            },
            "counts": counts,
            "counter_observations": dict(group["observations"]),
            "error_categories": dict(group["errors"]),
            "search_success_rate": round(counts.get("search_successes", 0) / searches, 4)
            if searches
            else None,
        }
    return {"versions": result, "accepted": accepted, "ignored": ignored, "truncated": truncated}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(aggregate(iter(lambda: sys.stdin.readline(65537), "")), sort_keys=True))


if __name__ == "__main__":
    main()
