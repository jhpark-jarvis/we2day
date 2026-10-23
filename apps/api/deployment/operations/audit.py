"""Daily integrity and photo inventory through the existing read-only backup context."""

import argparse
import json
import subprocess
from pathlib import Path

from monitor import write_report


def run(config, module, *arguments):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "backup",
            "-m",
            "we2day_api." + module,
            *arguments,
        ],
        cwd=config["backup_scheduler"],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    if result.returncode:
        raise ValueError("audit_failed")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        results = {}
        for name, operation in [
            (
                "photo_audit",
                lambda: run(config, "photo_audit", "--config", "/run/config/runtime.env"),
            ),
            (
                "integrity_audit",
                lambda: run(
                    config,
                    "backup_retention",
                    "--directory",
                    "/copies",
                    "--key",
                    "/run/keys/archive.key",
                ),
            ),
        ]:
            try:
                value = operation()
                value["status"] = value.get("status", "ok")
                if name == "integrity_audit" and value.get("verified", 0) < 1:
                    value["status"] = "attention"
            except Exception:
                value = {"format": 1, "status": "failed"}
            write_report(Path(config[name]), value)
            results[name] = value["status"]
        print(json.dumps(results))
        return 0 if all(value == "ok" for value in results.values()) else 1
    except Exception:
        print(json.dumps({"status": "failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
