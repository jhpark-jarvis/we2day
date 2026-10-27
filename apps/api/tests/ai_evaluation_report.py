"""Compare bounded synthetic evaluation reports without printing conversation contents."""

import argparse
import json
from pathlib import Path

from we2day_api.ai_metrics import percentile


def compare(before, after):
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
            }
        )
    # Every specified field/permission regression must pass, not only the percentage gate.
    ok = values[1]["passed"] == values[1]["cases"]
    return {"passed": ok, "before": values[0], "after": values[1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    reports = []
    for path in (args.before, args.after):
        if path.stat().st_size > 4_000_000:
            parser.error("Report exceeds limit")
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    result = compare(*reports)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
