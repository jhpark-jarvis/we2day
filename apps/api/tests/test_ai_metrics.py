import json
import logging

from we2day_api.ai_metrics import aggregate
from we2day_api.ai_runtime import RunStats

VERSION = "we2-ai-2026-10-27-v8"


def line(**values):
    return "INFO ai_run " + json.dumps({"version": VERSION, "status": "ok", **values})


def test_aggregate_mixed_versions_percentiles_and_missing_counters():
    result = aggregate(
        [
            line(total_ms=100, model_calls=0),
            line(
                total_ms=300,
                model_calls=2,
                prompt_tokens=100,
                search_calls=2,
                search_successes=1,
                search_errors=1,
            ),
            line(status=429, total_ms=200, error_category="ai_provider_limited"),
            line(version="we2-ai-2026-10-27-v7", total_ms=500),
        ]
    )
    value = result["versions"][VERSION]
    assert value["latency_ms"] == {"observations": 3, "p50": 200, "p95": 300}
    assert value["search_success_rate"] == 0.5 and value["counts"]["model_calls"] == 2
    assert value["counter_observations"]["prompt_tokens"] == 1
    assert "completion_tokens" not in value["counts"]
    assert value["error_categories"] == {"ai_provider_limited": 1}


def test_untrusted_log_fields_cannot_escape_in_summary():
    records = [
        "broken",
        "ai_run {",
        "x" * 65537,
        line(status=["sensitive"]),
        line(version="private-user-name"),
        line(
            prompt="secret",
            address="private",
            total_ms=float("nan"),
            error_category="sensitive",
            model_calls=True,
            tool_calls=-1,
        ),
    ]
    value = aggregate(records)
    output = json.dumps(value)
    assert value["accepted"] == 1 and value["ignored"] == 5
    assert all(text not in output for text in ["secret", "private", "sensitive", "NaN"])
    assert value["versions"][VERSION]["latency_ms"]["p50"] is None
    assert value["versions"][VERSION]["counts"] == {}
    assert aggregate([line()] * 5, limit=2)["truncated"]


def test_runtime_error_categories_are_fixed_and_never_reflect_details(caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        stats = RunStats(VERSION)
        stats.error({"private": "secret"})
        stats.error("sensitive-user-error")
        stats.emit(503)
        stats.error("ai_provider_limited")
        stats.emit(429)
    assert "secret" not in caplog.text and "sensitive-user" not in caplog.text
    assert aggregate(caplog.text.splitlines())["versions"][VERSION]["error_categories"] == {
        "ai_provider_limited": 1
    }
