"""Review-gated automatic-backup retention. Preview never deletes any archive."""

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from we2day_api.backup_bundle import encrypted, linked, safe_directory
from we2day_api.backup_collect import configuration
from we2day_api.backup_retention import KST, MAX_COPIES, select_copies
from we2day_api.backup_worker import (
    PROFILE,
    identities,
    locked,
    read_private,
    write_private,
)

POLICY = "automatic-daily7-weekly4-v1"
AUTO = re.compile(r"we2day-auto-\d{4}-\d{2}-\d{2}\.enc")
STATUS = ".we2day-cleanup-status.json"


def stamp(path):
    if linked(path) or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("regular_single_link_archive_required")
    info = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    before = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if before != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("archive_changed")
    return {"identity": list(before), "sha256": digest}


def inventory(directory):
    files = sorted(directory.glob("we2day-*.enc"))
    if len(files) > MAX_COPIES:
        raise ValueError("copy_limit")
    return {p.name: stamp(p) for p in files}


def prepare(config, key, gate):
    value = {
        "format": 1,
        **identities(config, key),
        "policy": POLICY,
        "enabled": False,
        "full_restore_reviewed": False,
        "offsite_copy_reviewed": False,
        "approval_reference": "",
    }
    write_private(gate, value, new=True)
    return {"state": "pending_review", "deletion_enabled": False}


def plan(config, key, directory, now):
    directory = safe_directory(directory)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    if os.name != "nt" and directory.stat().st_mode & 0o077:
        raise ValueError("private_directory_required")
    expected = identities(config, key)
    if read_private(directory / PROFILE) != {"format": 1, **expected}:
        raise ValueError("profile_mismatch")
    before = inventory(directory)
    automatic = {}
    for name in before:
        result = encrypted("verify-encrypted", directory / name, key, None)
        created = datetime.fromisoformat(result["created_at"])
        if created.tzinfo is None or created > now:
            raise ValueError("invalid_timestamp")
        if AUTO.fullmatch(name):
            if created.astimezone(KST).date().isoformat() != name[12:-4]:
                raise ValueError("automatic_date_mismatch")
            automatic[name] = created
    if inventory(directory) != before:
        raise ValueError("archive_set_changed")
    if not automatic or now - max(automatic.values()) > timedelta(hours=36):
        raise ValueError("recent_success_required")
    keep = select_copies(automatic, now)
    candidates = sorted(set(automatic) - keep)
    # A short history is never a reason to reduce the only available restore points.
    if candidates and len({v.astimezone(KST).date() for v in automatic.values()}) < 7:
        raise ValueError("minimum_daily_history_required")
    value = {
        "format": 1,
        "policy": POLICY,
        **expected,
        "automatic": len(automatic),
        "keep": sorted(keep),
        "preserved_manual": sorted(set(before) - set(automatic)),
        "candidates": candidates,
        "inventory": before,
    }
    value["plan_id"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


def run(config, key, gate, directory, *, apply=False, now=None):
    directory = safe_directory(directory)
    if gate.resolve() == directory or directory in gate.resolve().parents:
        raise ValueError("separate_gate_required")
    with locked(directory):
        value = plan(config, key, directory, now or datetime.now(UTC))
        result = {
            "format": 1,
            "state": "preview",
            "plan_id": value["plan_id"],
            "verified": len(value["inventory"]),
            "automatic": value["automatic"],
            "keep": len(value["keep"]),
            "preserved_manual": len(value["preserved_manual"]),
            "candidates": len(value["candidates"]),
            "deleted": 0,
            "deletion_enabled": False,
        }
        if not apply:
            return result
        review = read_private(gate)
        identity = identities(config, key)
        if any(review.get(k) != v for k, v in identity.items()) or review.get("policy") != POLICY:
            raise ValueError("cleanup_review_mismatch")
        if not (
            review.get("enabled") is True
            and review.get("full_restore_reviewed") is True
            and review.get("offsite_copy_reviewed") is True
            and isinstance(review.get("approval_reference"), str)
            and review["approval_reference"].strip()
        ):
            result["state"] = "pending_review"
            return result
        # Re-read gate and complete inventory before the first irreversible operation.
        if read_private(gate) != review or inventory(directory) != value["inventory"]:
            raise ValueError("cleanup_inputs_changed")
        result.update(state="running", deletion_enabled=True)
        write_private(directory / STATUS, result)
        remaining = dict(value["inventory"])
        try:
            for name in value["candidates"]:
                if read_private(gate) != review or inventory(directory) != remaining:
                    raise ValueError("cleanup_inputs_changed")
                if not AUTO.fullmatch(name) or name in value["keep"]:
                    raise ValueError("candidate_boundary")
                (directory / name).unlink()
                del remaining[name]
                result["deleted"] += 1
                write_private(directory / STATUS, result)
            result["state"] = "completed"
        except Exception:
            result["state"] = "interrupted"
            write_private(directory / STATUS, result)
            raise
        write_private(directory / STATUS, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "preview", "run"])
    for field in ["config", "key", "gate", "directory"]:
        parser.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args()
    try:
        config = configuration(args.config)
        result = (
            prepare(config, args.key, args.gate)
            if args.action == "prepare"
            else run(config, args.key, args.gate, args.directory, apply=args.action == "run")
        )
        print(json.dumps(result))
        return 2 if args.action == "run" and result["state"] == "pending_review" else 0
    except Exception:
        print("FAIL: cleanup review, lock, recent backup or integrity; values suppressed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
