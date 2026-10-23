"""Host-side health checks with aggregate, credential-free output and bounded calls."""

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15, stderr=subprocess.DEVNULL)


def backup_health(value, now):
    success = datetime.fromisoformat(value["last_success"])
    return (
        value["state"] in {"completed", "already_completed"}
        and success.tzinfo is not None
        and timedelta(0) <= now - success <= timedelta(hours=36)
    )


def inspect(config, now=None):
    now = now or datetime.now(UTC)
    checks = {}

    def check(name, operation):
        try:
            checks[name] = operation() is True
        except Exception:
            checks[name] = False

    for container in config["containers"]:

        def healthy(name=container):
            value = json.loads(command("docker", "inspect", name))[0]
            return (
                value["State"]["Running"] is True
                and value["State"].get("Health", {}).get("Status") == "healthy"
                and not value["State"]["OOMKilled"]
            )

        check(container, healthy)
    for timer in config["timers"]:
        check(timer, lambda name=timer: command("systemctl", "is-active", name).strip() == "active")
    for service in config["services"]:
        check(
            service,
            lambda name=service: (
                command("systemctl", "show", name, "--property=Result", "--value").strip()
                == "success"
            ),
        )
    usage = shutil.disk_usage(config["disk"])
    check("disk", lambda: usage.free >= 2 * 1024**3 and usage.used / usage.total < 0.8)
    check(
        "daily_backup",
        lambda: backup_health(json.loads(Path(config["backup_status"]).read_text()), now),
    )

    def certificate():
        domain = config["domain"]
        with socket.create_connection((domain, 443), timeout=10) as connection:
            with ssl.create_default_context().wrap_socket(
                connection, server_hostname=domain
            ) as tls:
                expires = datetime.strptime(tls.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z")
        return expires.replace(tzinfo=UTC) - now > timedelta(days=21)

    check("https_certificate", certificate)
    check("web_response", lambda: urlopen("http://127.0.0.1:3200/login", timeout=10).status == 200)
    # Files from the daily read-only audits; never include original paths or personal rows.
    for field in ["photo_audit", "integrity_audit"]:

        def fresh_report(key=field):
            path = Path(config[key])
            result = json.loads(path.read_text())
            return (
                timedelta(0)
                <= now - datetime.fromtimestamp(path.stat().st_mtime, UTC)
                <= timedelta(hours=36)
                and result["status"] == "ok"
            )

        check(field, fresh_report)
    return {
        "format": 1,
        "checked_at": now.isoformat(),
        "status": "ok" if all(checks.values()) else "attention",
        "checks": checks,
        "disk_used_percent": round(usage.used / usage.total * 100, 1),
    }


def write_report(path, result):
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("private_report_required")
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            os.chmod(temporary, 0o600)
            json.dump(result, file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect(json.loads(args.config.read_text()))
        write_report(args.output, result)
        print(json.dumps(result))
        return 0 if result["status"] == "ok" else 1
    except Exception:
        print(json.dumps({"status": "failed", "format": 1}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
