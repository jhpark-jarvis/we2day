"""One daily backup under an explicit operator review gate. Never deletes backups."""

import argparse
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from we2day_api.backup_bundle import closed_bytes, encrypted, json_value, linked, safe_directory
from we2day_api.backup_collect import collect, configuration
from we2day_api.backup_retention import KST, inspect
from we2day_api.local_archive import key_bytes

STATUS = ".we2day-backup-status.json"
PROFILE = ".we2day-backup-profile.json"


def identities(config, key):
    source = config["WE2DAY_SUPABASE_URL"] + "\n" + config["PGHOST"] + "\n" + config["PGUSER"]
    return {
        "source_id": hashlib.sha256(source.encode()).hexdigest(),
        "key_id": hashlib.sha256(key_bytes(key)).hexdigest(),
    }


def read_private(path):
    if linked(path) or not path.is_file():
        raise ValueError("private_file_required")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("private_mode_required")
    data = closed_bytes(path)
    if len(data) > 8192:
        raise ValueError("state_size_limit")
    value = json_value(data)
    if not isinstance(value, dict) or value.get("format") != 1:
        raise ValueError("state_format")
    return value


def write_private(path, value, *, new=False):
    safe_directory(path.parent)
    if linked(path) or (path.exists() and (new or not path.is_file())):
        raise ValueError("state_output")
    if path.exists():
        read_private(path)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".we2day-state-", delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        if new:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def prepare(config, key, gate):
    value = {
        "format": 1,
        **identities(config, key),
        "enabled": False,
        "restore_reviewed": False,
        "key_recovery_reviewed": False,
        "approval_reference": "",
    }
    write_private(gate, value, new=True)
    return {"state": "pending_review", "enabled": False}


def approved(config, key, gate):
    value = read_private(gate)
    expected = identities(config, key)
    if any(value.get(field) != digest for field, digest in expected.items()):
        raise ValueError("review_identity_mismatch")
    return (
        value.get("enabled") is True
        and value.get("restore_reviewed") is True
        and value.get("key_recovery_reviewed") is True
        and isinstance(value.get("approval_reference"), str)
        and bool(value["approval_reference"].strip())
    )


@contextmanager
def locked(directory):
    path = directory / ".we2day-backup.lock"
    if linked(path):
        raise ValueError("linked_lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("regular_lock_required")
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run(config, key, gate, directory, *, now=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    directory = safe_directory(directory)
    if os.name != "nt" and directory.stat().st_mode & 0o077:
        raise ValueError("private_directory_required")
    with locked(directory):
        status_file = directory / STATUS
        previous = read_private(status_file) if status_file.exists() else {"format": 1}
        state = {
            "format": 1,
            "attempted_at": now.isoformat(),
            "last_success": previous.get("last_success"),
            "state": "failed",
        }
        try:
            if not approved(config, key, gate):
                state["state"] = "pending_review"
                write_private(status_file, state)
                return state
            identity = identities(config, key)
            profile_file = directory / PROFILE
            if profile_file.exists():
                profile = read_private(profile_file)
                if profile != {"format": 1, **identity}:
                    raise ValueError("profile_mismatch")
            else:
                if list(directory.glob("we2day-auto-*.enc")):
                    raise ValueError("profile_missing")
                write_private(profile_file, {"format": 1, **identity}, new=True)
            day = now.astimezone(KST).date().isoformat()
            destination = directory / f"we2day-auto-{day}.enc"
            existing = destination.exists() or linked(destination)
            result = (
                encrypted("verify-encrypted", destination, key, None)
                if existing
                else collect(config, destination, key)
            )
            created = datetime.fromisoformat(result["created_at"])
            if created.astimezone(KST).date().isoformat() != day:
                raise ValueError("backup_date_mismatch")
            retention = inspect(directory, key, max(now, datetime.now(UTC)))
            state.update(
                state="already_completed" if existing else "completed",
                last_success=created.isoformat(),
                retention=retention,
            )
            write_private(status_file, state)
            return state
        except Exception:
            # Preserve the last successful timestamp and every existing backup on failure.
            write_private(status_file, state)
            raise


def status(directory, now=None):
    now = now or datetime.now(UTC)
    value = read_private(safe_directory(directory) / STATUS)
    if value.get("state") not in {"completed", "already_completed", "failed", "pending_review"}:
        raise ValueError("status_state")
    stamp = value.get("last_success")
    success = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    if success and (success.tzinfo is None or success > now):
        raise ValueError("status_timestamp")
    return {
        "state": value.get("state"),
        "last_success": stamp,
        "older_than_36_hours": success is None or now - success > timedelta(hours=36),
        "deletion_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "check", "run", "status"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "status":
            if args.directory is None:
                raise ValueError("directory_required")
            value = status(args.directory)
        else:
            if None in (args.config, args.key, args.gate):
                raise ValueError("configuration_required")
            config = configuration(args.config)
            if args.action == "prepare":
                value = prepare(config, args.key, args.gate)
            elif args.action == "check":
                value = {"enabled": approved(config, args.key, args.gate)}
            elif args.directory is not None:
                value = run(config, args.key, args.gate, args.directory)
            else:
                raise ValueError("directory_required")
        print(json.dumps(value))
        return 2 if args.action == "run" and value.get("state") == "pending_review" else 0
    except (BlockingIOError, PermissionError):
        print("FAIL: backup busy or private file access unavailable")
        return 1
    except Exception:
        print("FAIL: backup review, integrity, configuration or collection")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
