import hashlib
import json
import os
import stat
import subprocess
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from cryptography.exceptions import InvalidTag

from we2day_api import backup_bundle as backup
from we2day_api.backup_retention import inspect as retention_plan
from we2day_api.local_archive import create_key


@pytest.fixture
def export(tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    for name in backup.DATABASE:
        (root / name).write_bytes(b"-- synthetic SQL, never executed by bundle CLI\n")
    photo = root / "storage/couple/photo.webp"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"synthetic-photo-content")
    (root / backup.INVENTORY).write_text(
        json.dumps(
            {
                "bucket": "we2day-photos",
                "objects": [{"name": "couple/photo.webp", "size": photo.stat().st_size}],
            }
        ),
        encoding="utf-8",
    )
    return root


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_bundle_encryption_recovery_preserves_all_bytes(export, tmp_path):
    keys, copies = tmp_path / "keys", tmp_path / "copies"
    keys.mkdir()
    copies.mkdir()
    key = keys / "key.bin"
    create_key(key)
    archive = copies / "we2day-snapshot.enc"
    expected = files(export)
    result = backup.encrypted("snapshot", export, key, archive)
    assert result["photos"] == 1
    assert backup.encrypted("verify-encrypted", archive, key, None) == result
    destination = tmp_path / "recovered"
    assert backup.encrypted("restore", archive, key, destination) == result
    assert files(destination) == expected
    assert files(export) == expected
    assert list(copies.iterdir()) == [archive]
    plan = retention_plan(copies, key, datetime.now(UTC))
    assert plan["verified"] == plan["keep"] == 1
    assert plan["review_candidates"] == 0 and not plan["deletion_enabled"]
    assert list(copies.iterdir()) == [archive]
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o700
        assert stat.S_IMODE((destination / "data.sql").stat().st_mode) == 0o600


@pytest.mark.parametrize("problem", ["missing-photo", "extra-photo", "wrong-size", "empty-sql"])
def test_incomplete_or_extra_export_is_not_published(export, tmp_path, problem):
    photo = export / "storage/couple/photo.webp"
    if problem == "missing-photo":
        photo.unlink()
    elif problem == "extra-photo":
        (photo.parent / "unknown.webp").write_bytes(b"unknown")
    elif problem == "wrong-size":
        photo.write_bytes(b"short")
    else:
        (export / "data.sql").write_bytes(b"")
    destination = tmp_path / "bundle.zip"
    with pytest.raises(ValueError):
        backup.pack(export, destination)
    assert not destination.exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/etc/passwd",
        "a\\b",
        "C:secret",
        "a/./b",
        "a//b",
        "NUL",
        "a/CON.txt",
        "a/trailing.",
    ],
)
def test_storage_paths_must_be_portable_and_stay_in_root(name):
    with pytest.raises(ValueError):
        backup.inventory_value(
            json.dumps({"bucket": "we2day-photos", "objects": [{"name": name, "size": 1}]}).encode()
        )


def test_case_collisions_and_duplicate_json_rejected():
    with pytest.raises(ValueError):
        backup.inventory_value(b'{"bucket":"we2day-photos","objects":[],"objects":[]}')
    with pytest.raises(ValueError):
        backup.inventory_value(
            json.dumps(
                {
                    "bucket": "we2day-photos",
                    "objects": [{"name": "A.webp", "size": 1}, {"name": "a.webp", "size": 1}],
                }
            ).encode()
        )


def rewrite_bundle(source, destination, mutate):
    with ZipFile(source) as bundle:
        entries = [(item, bundle.read(item)) for item in bundle.infolist()]
    mutate(entries)
    with ZipFile(destination, "w") as bundle:
        for info, content in entries:
            bundle.writestr(info, content)


def test_new_format_writes_v2_and_legacy_v1_remains_readable(export, tmp_path):
    current, legacy = tmp_path / "v2.zip", tmp_path / "v1.zip"
    backup.pack(export, current)
    with ZipFile(current) as archive:
        assert json.loads(archive.read(backup.MANIFEST))["format"] == "WE2DAY-BACKUP-2"

    def legacy_format(entries):
        for index, (entry, content) in enumerate(entries):
            if entry.filename == backup.MANIFEST:
                manifest = json.loads(content)
                manifest["format"] = backup.LEGACY_FORMAT
                entries[index] = entry, json.dumps(manifest).encode()

    rewrite_bundle(current, legacy, legacy_format)
    assert backup.verify(current) == backup.verify(legacy)
    backup.unpack(legacy, tmp_path / "recovered-v1")
    assert files(tmp_path / "recovered-v1") == files(export)


def test_inventory_version_is_optional_only_in_new_format():
    data = json.dumps(
        {
            "bucket": "we2day-photos",
            "objects": [{"name": "pair/photo.webp", "size": 4, "version": "a" * 64}],
        }
    ).encode()
    assert backup.inventory_value(data) == {"storage/pair/photo.webp": 4}
    with pytest.raises(ValueError):
        backup.inventory_value(data, allow_version=False)
    for version in (None, 123, "bad"):
        bad = json.loads(data)
        bad["objects"][0]["version"] = version
        with pytest.raises(ValueError):
            backup.inventory_value(json.dumps(bad).encode())


@pytest.mark.parametrize(
    "problem",
    [
        "same-size-corruption",
        "traversal",
        "duplicate",
        "symlink",
        "compression",
        "manifest-record",
        "inventory",
    ],
)
def test_untrusted_bundle_rejected_before_recovery(export, tmp_path, problem):
    original, broken = tmp_path / "original.zip", tmp_path / "broken.zip"
    backup.pack(export, original)

    def mutate(entries):
        if problem == "same-size-corruption":
            info, data = entries[0]
            entries[0] = info, bytes([data[0] ^ 1]) + data[1:]
        elif problem == "traversal":
            entries.append((ZipInfo("../escape"), b"bad"))
        elif problem == "duplicate":
            entries.append(entries[0])
        elif problem == "symlink":
            entries[0][0].external_attr = (stat.S_IFLNK | 0o777) << 16
        elif problem == "compression":
            entries[0][0].compress_type = ZIP_DEFLATED
        elif problem == "manifest-record":
            index = next(
                i for i, (entry, _) in enumerate(entries) if entry.filename == backup.MANIFEST
            )
            info, data = entries[index]
            manifest = json.loads(data)
            manifest["files"][0]["size"] = True
            entries[index] = info, json.dumps(manifest).encode()
        else:
            index = next(
                i for i, (entry, _) in enumerate(entries) if entry.filename == backup.INVENTORY
            )
            info, _ = entries[index]
            data = b'{"bucket":"we2day-photos","objects":[]}'
            entries[index] = info, data
            # Rehash forged inventory: object-set agreement must still be enforced.
            for j, (entry, content) in enumerate(entries):
                if entry.filename == backup.MANIFEST:
                    manifest = json.loads(content)
                    record = next(r for r in manifest["files"] if r["path"] == backup.INVENTORY)
                    record.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
                    entries[j] = entry, json.dumps(manifest).encode()

    with pytest.warns(UserWarning) if problem == "duplicate" else nullcontext():
        rewrite_bundle(original, broken, mutate)
    destination = tmp_path / "recovered"
    with pytest.raises(ValueError):
        backup.unpack(broken, destination)
    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


def test_outputs_never_overwrite_and_key_failure_leaves_no_plaintext(export, tmp_path):
    archive = tmp_path / "bundle.zip"
    backup.pack(export, archive)
    before = archive.read_bytes()
    with pytest.raises(ValueError):
        backup.pack(export, archive)
    assert archive.read_bytes() == before
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_bytes(b"keep")
    with pytest.raises(ValueError):
        backup.unpack(archive, existing)
    assert (existing / "keep").read_bytes() == b"keep"
    keys = tmp_path / "keys"
    keys.mkdir()
    key, wrong = keys / "key", keys / "wrong"
    create_key(key)
    create_key(wrong)
    encrypted = tmp_path / "bundle.enc"
    backup.encrypted("snapshot", export, key, encrypted)
    saved = files(tmp_path)
    with pytest.raises(InvalidTag):
        backup.encrypted("restore", encrypted, wrong, tmp_path / "recovery")
    assert files(tmp_path) == saved


def test_size_limit_and_repository_directory_rejected(export, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    with pytest.raises(ValueError):
        backup.pack(export, tmp_path / "large.zip")
    (export / ".git").mkdir()
    with pytest.raises(ValueError, match="outside_repository"):
        backup.source_files(export)


def test_cli_errors_do_not_disclose_paths_or_object_names(tmp_path):
    source = tmp_path / "private-user-photo-name.zip"
    source.write_bytes(b"not a zip")
    result = subprocess.run(
        [sys.executable, "-m", "we2day_api.backup_bundle", "verify", "--input", str(source)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "private-user" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_original_and_preview_share_inventory_and_restore(export, tmp_path):
    preview = export / "storage/couple/photo.preview.webp"
    preview.write_bytes(b"synthetic-private-preview")
    inventory = json.loads((export / backup.INVENTORY).read_text())
    inventory["objects"].append(
        {"name": "couple/photo.preview.webp", "size": preview.stat().st_size}
    )
    (export / backup.INVENTORY).write_text(json.dumps(inventory))
    (tmp_path / "keys").mkdir()
    key = tmp_path / "keys/key.bin"
    create_key(key)
    archive = tmp_path / "both.enc"
    expected = files(export)
    result = backup.encrypted("snapshot", export, key, archive)
    assert result["photos"] == 2
    assert backup.encrypted("verify-encrypted", archive, key, None) == result
    recovered = tmp_path / "recovered"
    backup.encrypted("restore", archive, key, recovered)
    assert files(recovered) == expected
