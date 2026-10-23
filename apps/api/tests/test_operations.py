import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "ops_monitor", Path(__file__).parents[1] / "deployment/operations/monitor.py"
)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def test_backup_status_boundaries_and_failed_attempt():
    now = datetime.now(UTC)
    good = {"last_success": (now - timedelta(hours=36)).isoformat(), "state": "completed"}
    assert monitor.backup_health(good, now)
    assert not monitor.backup_health(good, now + timedelta(seconds=1))
    assert not monitor.backup_health({**good, "state": "failed"}, now)
    assert not monitor.backup_health(
        {**good, "last_success": (now + timedelta(seconds=1)).isoformat()}, now
    )


def test_monitor_collects_failures_without_printing_exception_or_skipping_other_checks(
    tmp_path, monkeypatch
):
    now = datetime.now(UTC)
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({"last_success": now.isoformat(), "state": "completed"}))
    photo = tmp_path / "photo.json"
    photo.write_text('{"status":"ok"}')
    config = {
        "containers": ["web"],
        "timers": ["timer"],
        "services": ["service"],
        "disk": str(tmp_path),
        "backup_status": str(backup),
        "domain": "fixture.invalid",
        "photo_audit": str(photo),
        "integrity_audit": str(photo),
    }
    monkeypatch.setattr(
        monitor, "command", lambda *args: (_ for _ in ()).throw(ValueError("private"))
    )
    monkeypatch.setattr(
        monitor.socket,
        "create_connection",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("secret")),
    )
    monkeypatch.setattr(monitor, "urlopen", lambda *a, **kw: SimpleNamespace(status=200))
    monkeypatch.setattr(
        monitor.shutil,
        "disk_usage",
        lambda *a: SimpleNamespace(total=100 * 1024**3, used=81 * 1024**3, free=19 * 1024**3),
    )
    result = monitor.inspect(config, now)
    assert result["status"] == "attention"
    assert not result["checks"]["web"] and not result["checks"]["disk"]
    assert result["checks"]["daily_backup"] and result["checks"]["web_response"]
    assert "secret" not in json.dumps(result) and "private" not in json.dumps(result)
    monitor.write_report(tmp_path / "report.json", result)
    assert json.loads((tmp_path / "report.json").read_text()) == result
    photo.write_text('{"status":"failed"}')
    assert not monitor.inspect(config, now)["checks"]["photo_audit"]


def test_report_rejects_link(tmp_path):
    source = tmp_path / "source"
    source.write_text("keep")
    try:
        (tmp_path / "link").symlink_to(source)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        monitor.write_report(tmp_path / "link", {})
    assert source.read_text() == "keep"
