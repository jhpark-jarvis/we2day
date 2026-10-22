from datetime import UTC, datetime, timedelta

import pytest

from we2day_api import backup_retention as retention


def test_daily_and_weekly_union_keeps_latest_and_old_weekly():
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    copies = {f"copy-{i}": now - timedelta(days=i) for i in range(40)}
    copies["older-same-day"] = now - timedelta(hours=1)
    keep = retention.select_copies(copies, now)
    assert {f"copy-{i}" for i in range(7)} <= keep
    assert keep == {*(f"copy-{i}" for i in range(7)), "copy-11", "copy-18"}
    assert "older-same-day" not in keep


def test_korean_day_and_iso_year_boundaries():
    before = datetime(2026, 12, 31, 14, 59, tzinfo=UTC)
    after = before + timedelta(minutes=2)
    assert len(retention.select_copies({"a": before, "b": after}, after)) == 2
    assert retention.select_copies({}, after) == set()


def test_future_or_naive_dates_refuse_plan():
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        retention.select_copies({"future": now + timedelta(seconds=1)}, now)
    with pytest.raises(ValueError):
        retention.select_copies({"naive": now.replace(tzinfo=None)}, now)


def test_corrupt_copy_aborts_without_deleting_anything(tmp_path):
    (tmp_path / "we2day-broken.enc").write_bytes(b"broken")
    (tmp_path / "unmanaged.txt").write_bytes(b"preserved")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises((ValueError, OSError)):
        retention.inspect(tmp_path, tmp_path / "missing-key", datetime.now(UTC))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_only_managed_copies_verified_and_no_paths_reported(tmp_path, monkeypatch):
    timestamp = datetime.now(UTC)
    (tmp_path / "we2day-one.enc").write_bytes(b"fixture")
    (tmp_path / "unmanaged.enc").write_bytes(b"unknown")
    monkeypatch.setattr(retention, "encrypted", lambda *args: {"created_at": timestamp.isoformat()})
    result = retention.inspect(tmp_path, tmp_path / "key", timestamp)
    assert result["verified"] == result["keep"] == 1
    assert result["review_candidates"] == 0
    assert result["deletion_enabled"] is result["schedule_enabled"] is False
