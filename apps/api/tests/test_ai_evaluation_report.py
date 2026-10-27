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
