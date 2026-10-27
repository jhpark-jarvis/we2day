import copy

import pytest
from ai_evaluation_report import compare


def report(failed=False):
    return {
        "halted": False,
        "corpus_sha256": "synthetic",
        "model": "same",
        "cases": [
            {
                "id": "N01",
                "split": "extension",
                "turns": [
                    {
                        "failures": ["wrong_field"] if failed else [],
                        "counts": {"model_calls": 0},
                        "ms": 2,
                    }
                ],
            }
        ],
    }


def test_automatic_comparison_cannot_pass_a_wrong_field_or_different_corpus():
    assert compare(report(True), report())["passed"]
    assert not compare(report(), report(True))["passed"]
    for key, value in [("halted", True), ("model", "changed"), ("corpus_sha256", "changed")]:
        changed = copy.deepcopy(report())
        changed[key] = value
        with pytest.raises(ValueError):
            compare(report(), changed)
    missing = report()
    missing["cases"] = []
    with pytest.raises(ValueError):
        compare(report(), missing)


def test_optional_efficiency_gate_requires_same_successful_turns_and_reported_usage():
    before, after = report(), report()
    before["cases"][0]["turns"][0]["counts"] = {
        "model_calls": 2,
        "tool_calls": 1,
        "prompt_tokens": 1000,
    }
    after["cases"][0]["turns"][0]["counts"] = {
        "model_calls": 2,
        "tool_calls": 1,
        "prompt_tokens": 800,
    }
    result = compare(before, after, min_input_reduction=10)
    assert result["passed"] and result["efficiency"]["input_reduction_percent"] == 20
    after["cases"][0]["turns"][0]["counts"]["model_calls"] = 3
    assert not compare(before, after, min_input_reduction=10)["passed"]
    after["cases"][0]["turns"][0]["counts"].pop("prompt_tokens")
    assert not compare(before, after, min_input_reduction=10)["passed"]
    assert compare(before, after)["passed"]  # Backward-compatible quality-only comparison.
