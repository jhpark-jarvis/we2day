import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from we2day_api import backup_bundle as bundle
from we2day_api import backup_worker as worker
from we2day_api.local_archive import create_key


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = {
        "WE2DAY_SUPABASE_URL": "https://fixture.invalid",
        "PGHOST": "fixture",
        "PGUSER": "fixture",
    }
    keys, copies, settings, export = [
        tmp_path / name for name in ("keys", "copies", "settings", "export")
    ]
    for path in (keys, copies, settings, export):
        path.mkdir(mode=0o700)
    key, gate = keys / "archive.key", settings / "review.json"
    create_key(key)
    worker.prepare(config, key, gate)
    for name in bundle.DATABASE:
        (export / name).write_bytes(b"-- synthetic SQL\n")
    (export / bundle.INVENTORY).write_text('{"bucket":"we2day-photos","objects":[]}')
    calls = []

    def collect(config, destination, key):
        calls.append(destination)
        return bundle.encrypted("snapshot", export, key, destination)

    monkeypatch.setattr(worker, "collect", collect)
    return config, key, gate, copies, calls


def enable(gate):
    value = worker.read_private(gate)
    value.update(
        enabled=True,
        restore_reviewed=True,
        key_recovery_reviewed=True,
        approval_reference="synthetic test only",
    )
    worker.write_private(gate, value)


def test_pending_review_never_collects_and_gate_never_auto_enables(setup):
    config, key, gate, copies, calls = setup
    before = gate.read_bytes()
    result = worker.run(config, key, gate, copies)
    assert result["state"] == "pending_review" and not calls
    assert before == gate.read_bytes()
    assert not list(copies.glob("*.enc"))
    assert worker.status(copies)["older_than_36_hours"]


@pytest.mark.parametrize(
    "field", ["restore_reviewed", "key_recovery_reviewed", "approval_reference"]
)
def test_each_missing_review_prevents_collection(setup, field):
    config, key, gate, copies, calls = setup
    enable(gate)
    value = worker.read_private(gate)
    value[field] = "" if field == "approval_reference" else False
    worker.write_private(gate, value)
    assert worker.run(config, key, gate, copies)["state"] == "pending_review"
    assert not calls


def test_success_real_encryption_and_same_day_retry_is_idempotent(setup):
    config, key, gate, copies, calls = setup
    enable(gate)
    first = worker.run(config, key, gate, copies)
    archive = calls[0]
    before = archive.read_bytes()
    second = worker.run(config, key, gate, copies)
    assert first["state"] == "completed" and second["state"] == "already_completed"
    assert len(calls) == 1 and before == archive.read_bytes()
    assert second["retention"]["verified"] == 1 and not second["retention"]["deletion_enabled"]
    assert not worker.status(copies)["older_than_36_hours"]
    if os.name != "nt":
        assert (copies / worker.STATUS).stat().st_mode & 0o077 == 0
    assert not list(copies.glob(".we2day-state-*"))


def test_failure_preserves_prior_success_and_every_backup(setup, monkeypatch):
    config, key, gate, copies, calls = setup
    enable(gate)
    success = worker.run(config, key, gate, copies)
    before = calls[0].read_bytes()

    def fail(*args, **kwargs):
        raise ValueError("simulated failure with private values")

    monkeypatch.setattr(worker, "collect", fail)
    with pytest.raises(ValueError):
        worker.run(config, key, gate, copies, now=datetime.now(UTC) + timedelta(days=1))
    state = worker.read_private(copies / worker.STATUS)
    assert state["state"] == "failed" and state["last_success"] == success["last_success"]
    assert calls[0].read_bytes() == before
    assert "private values" not in json.dumps(state)


def test_next_day_uses_latest_prior_archive_only(setup, monkeypatch):
    config, key, gate, copies, calls = setup
    enable(gate)
    worker.run(config, key, gate, copies)
    prior = calls[0]
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    seen = []

    def collect(config, destination, key, *, previous):
        seen.append(previous)
        raise ValueError("stop after selecting prior")

    monkeypatch.setattr(worker, "collect", collect)
    # Noncanonical names are not eligible for reuse, even if they sort last.
    (copies / "we2day-auto-zzzz.enc").write_bytes(b"unrelated fixture")
    with pytest.raises(ValueError, match="stop after selecting prior"):
        worker.run(config, key, gate, copies, now=tomorrow)
    assert seen == [prior] and prior.is_file()


def test_corrupt_existing_copy_is_never_replaced(setup):
    config, key, gate, copies, calls = setup
    enable(gate)
    worker.run(config, key, gate, copies)
    archive = calls[0]
    archive.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        worker.run(config, key, gate, copies)
    assert len(calls) == 1 and archive.read_bytes() == b"corrupt"
    assert worker.status(copies)["state"] == "failed"


def test_key_or_source_change_invalidates_prior_review(setup):
    config, key, gate, copies, calls = setup
    enable(gate)
    changed = config | {"PGUSER": "different"}
    with pytest.raises(ValueError, match="review_identity_mismatch"):
        worker.run(changed, key, gate, copies)
    other = key.parent / "different.key"
    create_key(other)
    with pytest.raises(ValueError, match="review_identity_mismatch"):
        worker.run(config, other, gate, copies)
    assert not calls


def test_profile_mismatch_and_lost_profile_refuse_adoption(setup):
    config, key, gate, copies, calls = setup
    enable(gate)
    worker.run(config, key, gate, copies)
    profile = copies / worker.PROFILE
    value = worker.read_private(profile)
    value["source_id"] = "wrong"
    worker.write_private(profile, value)
    with pytest.raises(ValueError, match="profile_mismatch"):
        worker.run(config, key, gate, copies)
    profile.unlink()
    with pytest.raises(ValueError, match="profile_missing"):
        worker.run(config, key, gate, copies)
    assert len(calls) == 1 and calls[0].is_file()


def test_concurrent_runner_does_not_overwrite_active_state(setup):
    config, key, gate, copies, calls = setup
    enable(gate)
    worker.run(config, key, gate, copies)
    before = (copies / worker.STATUS).read_bytes()
    with worker.locked(copies):
        with pytest.raises(OSError):
            worker.run(config, key, gate, copies)
    assert before == (copies / worker.STATUS).read_bytes() and len(calls) == 1


def test_duplicate_or_public_gate_rejected_and_prepare_never_overwrites(setup):
    config, key, gate, copies, calls = setup
    before = gate.read_bytes()
    with pytest.raises(ValueError):
        worker.prepare(config, key, gate)
    assert before == gate.read_bytes()
    gate.write_text('{"format":1,"enabled":false,"enabled":true}')
    with pytest.raises(ValueError):
        worker.approved(config, key, gate)
    if os.name != "nt":
        gate.write_bytes(before)
        gate.chmod(0o644)
        with pytest.raises(ValueError, match="private_mode_required"):
            worker.approved(config, key, gate)
    assert not calls
