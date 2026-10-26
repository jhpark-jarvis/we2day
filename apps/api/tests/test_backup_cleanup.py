import json
from datetime import UTC, datetime, timedelta

import pytest

from we2day_api import backup_bundle as bundle
from we2day_api import backup_cleanup as cleanup
from we2day_api.backup_worker import PROFILE, identities, locked, read_private, write_private
from we2day_api.local_archive import create_key


@pytest.fixture
def setup(tmp_path, monkeypatch):
    keys, copies, settings, export = [
        tmp_path / n for n in ["keys", "copies", "settings", "export"]
    ]
    for p in [keys, copies, settings, export]:
        p.mkdir(mode=0o700)
    key = keys / "archive.key"
    create_key(key)
    config = {"WE2DAY_SUPABASE_URL": "fixture", "PGHOST": "fixture", "PGUSER": "fixture"}
    write_private(copies / PROFILE, {"format": 1, **identities(config, key)}, new=True)
    gate = settings / "cleanup.json"
    cleanup.prepare(config, key, gate)
    now = datetime(2026, 10, 26, 5, tzinfo=UTC)
    clock = now - timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr(bundle, "datetime", Clock)
    for n in bundle.DATABASE:
        (export / n).write_text("-- synthetic only\n")
    (export / bundle.INVENTORY).write_text('{"bucket":"we2day-photos","objects":[]}')
    for day in range(20):
        clock = now - timedelta(days=day, minutes=1)
        name = f"we2day-auto-{clock.astimezone(cleanup.KST).date().isoformat()}.enc"
        bundle.encrypted("snapshot", export, key, copies / name)
    clock = now - timedelta(days=19)
    bundle.encrypted("snapshot", export, key, copies / "we2day-checkpoint-keep.enc")
    return config, key, gate, copies, now


def approved(gate):
    review = read_private(gate)
    review.update(
        enabled=True,
        full_restore_reviewed=True,
        offsite_copy_reviewed=True,
        approval_reference="disposable fixture approval",
    )
    write_private(gate, review)


def archives(copies):
    return {p.name: p.read_bytes() for p in copies.glob("*.enc")}


def test_preview_and_pending_gate_preserve_every_byte(setup):
    config, key, gate, copies, now = setup
    before = archives(copies)
    preview = cleanup.run(config, key, gate, copies, now=now)
    assert preview["candidates"] > 0 and preview["preserved_manual"] == 1
    assert not preview["deletion_enabled"] and preview["deleted"] == 0
    pending = cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert pending["state"] == "pending_review" and archives(copies) == before
    assert not read_private(gate)["enabled"]


def test_approved_cleanup_keeps_daily_weekly_and_manual_and_repeats_safely(setup):
    config, key, gate, copies, now = setup
    before = archives(copies)
    value = cleanup.plan(config, key, copies, now)
    approved(gate)
    result = cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert result["deleted"] == len(value["candidates"]) > 0
    expected = set(value["keep"]) | {"we2day-checkpoint-keep.enc"}
    assert archives(copies) == {n: data for n, data in before.items() if n in expected}
    assert cleanup.run(config, key, gate, copies, now=now, apply=True)["deleted"] == 0


@pytest.mark.parametrize(
    "field", ["enabled", "full_restore_reviewed", "offsite_copy_reviewed", "approval_reference"]
)
def test_each_missing_approval_blocks_deletion(setup, field):
    config, key, gate, copies, now = setup
    approved(gate)
    review = read_private(gate)
    review[field] = "" if field == "approval_reference" else False
    write_private(gate, review)
    before = archives(copies)
    assert cleanup.run(config, key, gate, copies, now=now, apply=True)["state"] == "pending_review"
    assert archives(copies) == before


@pytest.mark.parametrize("failure", ["corrupt", "profile", "stale", "linked", "date"])
def test_unsafe_inventory_aborts_before_any_delete(setup, failure):
    config, key, gate, copies, now = setup
    approved(gate)
    if failure == "corrupt":
        (copies / "we2day-broken.enc").write_bytes(b"bad")
    elif failure == "profile":
        (copies / PROFILE).write_text(json.dumps({"format": 1, "source_id": "other"}))
    elif failure == "stale":
        now += timedelta(days=2)
    elif failure == "linked":
        import os

        os.link(next(copies.glob("*.enc")), copies / "we2day-hardlink.enc")
    else:
        next(copies.glob("we2day-auto-*.enc")).rename(copies / "we2day-auto-2000-01-01.enc")
    before = archives(copies)
    with pytest.raises(ValueError):
        cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert archives(copies) == before


def test_changed_inventory_between_verification_and_apply_is_rejected(setup, monkeypatch):
    config, key, gate, copies, now = setup
    approved(gate)
    original = cleanup.plan

    def change(*args):
        value = original(*args)
        (copies / "we2day-new.enc").write_bytes(b"concurrent change")
        return value

    monkeypatch.setattr(cleanup, "plan", change)
    before = archives(copies)
    with pytest.raises(ValueError, match="cleanup_inputs_changed"):
        cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert all((copies / n).read_bytes() == data for n, data in before.items())


def test_shared_generator_lock_refuses_cleanup(setup):
    import os

    if os.name == "nt":
        pytest.skip("POSIX lock collision is exercised in Linux image")
    config, key, gate, copies, now = setup
    before = archives(copies)
    with locked(copies), pytest.raises(BlockingIOError):
        cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert archives(copies) == before


@pytest.mark.parametrize("field", ["source_id", "key_id", "policy"])
def test_other_source_key_or_policy_gate_is_rejected(setup, field):
    config, key, gate, copies, now = setup
    approved(gate)
    review = read_private(gate)
    review[field] = "other"
    write_private(gate, review)
    before = archives(copies)
    with pytest.raises(ValueError, match="cleanup_review_mismatch"):
        cleanup.run(config, key, gate, copies, now=now, apply=True)
    assert archives(copies) == before


def test_partial_io_failure_stops_and_records_exact_deleted_count(setup, monkeypatch):
    from pathlib import Path

    config, key, gate, copies, now = setup
    approved(gate)
    value = cleanup.plan(config, key, copies, now)
    before = archives(copies)
    original = Path.unlink
    calls = 0

    def fail_second(path, *args, **kwargs):
        nonlocal calls
        if path.parent == copies and path.name in value["candidates"]:
            calls += 1
            if calls == 2:
                raise OSError("synthetic removal failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    with pytest.raises(OSError):
        cleanup.run(config, key, gate, copies, now=now, apply=True)
    receipt = read_private(copies / cleanup.STATUS)
    assert receipt["state"] == "interrupted" and receipt["deleted"] == 1
    assert len(archives(copies)) == len(before) - 1
    assert all((copies / n).read_bytes() == before[n] for n in value["keep"])
