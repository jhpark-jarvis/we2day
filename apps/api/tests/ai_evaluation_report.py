"""Compare bounded synthetic evaluation reports without printing conversation contents."""

import argparse
import json
from pathlib import Path

from we2day_api.ai_metrics import percentile


def compare(before, after, *, min_input_reduction=None):
    if before["halted"] or after["halted"]:
        raise ValueError("Incomplete evaluation")
    if (before["corpus_sha256"], before["model"]) != (after["corpus_sha256"], after["model"]):
        raise ValueError("Different corpus or model")
    identifiers = [
        [(c["id"], c["split"], len(c["turns"])) for c in r["cases"]] for r in (before, after)
    ]
    if not identifiers[0] or identifiers[0] != identifiers[1]:
        raise ValueError("Cases or turns changed")
    values = []
    for report in (before, after):
        if len(report["cases"]) > 1000:
            raise ValueError("Too many cases")
        passed = sum(
            bool(c["turns"]) and all(not t["failures"] for t in c["turns"]) for c in report["cases"]
        )
        turns = [t for c in report["cases"] for t in c["turns"]]
        counts = {}
        for key in (
            "model_calls",
            "tool_calls",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "request_bytes",
        ):
            observations = [t["counts"][key] for t in turns if key in t.get("counts", {})]
            if observations:
                counts[key] = sum(observations)
        elapsed = [t["ms"] for t in turns if "ms" in t]
        values.append(
            {
                "passed": passed,
                "cases": len(report["cases"]),
                "turns": len(turns),
                "counts": counts,
                "p50_ms": percentile(elapsed, 0.5),
                "p95_ms": percentile(elapsed, 0.95),
                "model_p50_ms": percentile(
                    [
                        t["ms"]
                        for t in turns
                        if t.get("counts", {}).get("model_calls", 0) > 0 and "ms" in t
                    ],
                    0.5,
                ),
                "model_p95_ms": percentile(
                    [
                        t["ms"]
                        for t in turns
                        if t.get("counts", {}).get("model_calls", 0) > 0 and "ms" in t
                    ],
                    0.95,
                ),
            }
        )
    # Every specified field/permission regression must pass, not only the percentage gate.
    ok = values[1]["passed"] == values[1]["cases"]
    pairs = [
        (a, b)
        for ca, cb in zip(before["cases"], after["cases"], strict=True)
        for a, b in zip(ca["turns"], cb["turns"], strict=True)
    ]
    eligible = [
        (a, b)
        for a, b in pairs
        if not a["failures"]
        and not b["failures"]
        and a.get("counts", {}).get("model_calls", 0) > 0
        and b.get("counts", {}).get("model_calls", 0) > 0
    ]
    measured = [
        (a["counts"]["prompt_tokens"], b["counts"]["prompt_tokens"])
        for a, b in eligible
        if all(
            type(v.get("counts", {}).get("prompt_tokens")) is int
            and v["counts"]["prompt_tokens"] > 0
            for v in [a, b]
        )
    ]
    total_before, total_after = (sum(v[i] for v in measured) for i in [0, 1])
    reduction = round((1 - total_after / total_before) * 100, 2) if total_before else None
    efficiency = {
        "paired_successful_model_turns": len(eligible),
        "measured_usage_pairs": len(measured),
        "input_tokens_before": total_before if measured else None,
        "input_tokens_after": total_after if measured else None,
        "input_reduction_percent": reduction,
        "no_model_call_increase": all(
            b.get("counts", {}).get("model_calls", 0) <= a.get("counts", {}).get("model_calls", 0)
            for a, b in pairs
        ),
        "no_tool_call_increase": all(
            b.get("counts", {}).get("tool_calls", 0) <= a.get("counts", {}).get("tool_calls", 0)
            for a, b in pairs
        ),
    }
    if min_input_reduction is not None:
        if not 0 <= min_input_reduction <= 100:
            raise ValueError("Invalid reduction threshold")
        ok = (
            ok
            and bool(measured)
            and len(measured) == len(eligible)
            and reduction >= min_input_reduction
            and efficiency["no_model_call_increase"]
            and efficiency["no_tool_call_increase"]
        )
    return {"passed": ok, "before": values[0], "after": values[1], "efficiency": efficiency}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--min-input-reduction-percent", type=float)
    args = parser.parse_args()
    reports = []
    for path in (args.before, args.after):
        if path.stat().st_size > 4_000_000:
            parser.error("Report exceeds limit")
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    result = compare(*reports, min_input_reduction=args.min_input_reduction_percent)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
