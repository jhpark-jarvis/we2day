"""Inspect encrypted bundles and calculate retention; never delete or schedule files."""

import argparse
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zipfile import BadZipFile

from cryptography.exceptions import InvalidTag

from we2day_api.backup_bundle import encrypted, safe_directory

KST = timezone(timedelta(hours=9))
MAX_COPIES = 256


def select_copies(copies: dict[str, datetime], now: datetime) -> set[str]:
    """Keep the newest per day/week, then seven distinct days and four ISO weeks."""
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    if any(timestamp.tzinfo is None or timestamp > now for timestamp in copies.values()):
        raise ValueError("invalid_timestamp")
    days, weeks = {}, {}
    for name, timestamp in sorted(
        copies.items(), key=lambda pair: (pair[1], pair[0]), reverse=True
    ):
        local = timestamp.astimezone(KST)
        days.setdefault(local.date(), name)
        weeks.setdefault(local.isocalendar()[:2], name)
    return set(list(days.values())[:7]) | set(list(weeks.values())[:4])


def inspect(directory: Path, key: Path, now: datetime) -> dict:
    directory = safe_directory(directory)
    # Only this explicit namespace participates; every other entry remains untouched.
    files = sorted(directory.glob("we2day-*.enc"))
    if len(files) > MAX_COPIES:
        raise ValueError("copy_limit")
    copies = {}
    for file in files:
        result = encrypted("verify-encrypted", file, key, None)
        copies[file.name] = datetime.fromisoformat(result["created_at"])
    keep = select_copies(copies, now)
    return {
        "verified": len(copies),
        "keep": len(keep),
        "review_candidates": len(copies) - len(keep),
        "timezone": "Asia/Seoul",
        "deletion_enabled": False,
        "schedule_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.directory, args.key, datetime.now(UTC))))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, InvalidTag, BadZipFile):
        print("FAIL: backup verification or retention prerequisites")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
