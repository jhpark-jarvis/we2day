"""Offline DB/Storage export bundles. Never connects to or restores a live project."""

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from cryptography.exceptions import InvalidTag

from we2day_api.local_archive import CHUNK, fingerprint, process, regular

FORMAT = "WE2DAY-BACKUP-2"
LEGACY_FORMAT = "WE2DAY-BACKUP-1"
DATABASE = ("roles.sql", "schema.sql", "data.sql")
INVENTORY = "storage-inventory.json"
MANIFEST = "manifest.json"
MAX_TOTAL = 8 * 1024**3
MAX_JSON = 8 * 1024**2
MAX_OBJECTS = 20_000


def linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def safe_directory(path: Path) -> Path:
    if any(linked(item) for item in (path, *path.parents)) or not path.is_dir():
        raise ValueError("regular_directory_required")
    resolved = path.resolve(strict=True)
    if any((item / ".git").exists() for item in (resolved, *resolved.parents)):
        raise ValueError("outside_repository_required")
    return resolved


def safe_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 600:
        raise ValueError("invalid_name")
    parts = PurePosixPath(value).parts
    if not parts or "/".join(parts) != value:
        raise ValueError("invalid_name")
    if any(
        part in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", part) for part in parts
    ):
        raise ValueError("invalid_name")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if any(part.endswith(".") or part.split(".")[0].upper() in reserved for part in parts):
        raise ValueError("nonportable_name")
    return value


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def json_value(data: bytes):
    if len(data) > MAX_JSON:
        raise ValueError("metadata_too_large")
    return json.loads(data, object_pairs_hook=unique_pairs)


def inventory_value(data: bytes, *, allow_version=True) -> dict[str, int]:
    value = json_value(data)
    if not isinstance(value, dict) or set(value) != {"bucket", "objects"}:
        raise ValueError("invalid_inventory")
    objects = value["objects"]
    if value["bucket"] != "we2day-photos" or not isinstance(objects, list):
        raise ValueError("invalid_inventory")
    if len(objects) > MAX_OBJECTS:
        raise ValueError("too_many_objects")
    result = {}
    folded = set()
    for item in objects:
        if not isinstance(item, dict) or set(item) not in (
            {"name", "size"},
            {"name", "size", "version"} if allow_version else {"name", "size"},
        ):
            raise ValueError("invalid_inventory")
        if "version" in item and (
            not isinstance(item["version"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["version"])
        ):
            raise ValueError("invalid_inventory_version")
        name, size = safe_name(item["name"]), item["size"]
        if (
            type(size) is not int
            or not 0 <= size <= MAX_TOTAL
            or ("storage/" + name).casefold() in folded
        ):
            raise ValueError("invalid_inventory")
        result["storage/" + name] = size
        folded.add(("storage/" + name).casefold())
    return result


def closed_bytes(path: Path) -> bytes:
    with regular(path).open("rb") as stream:
        before = fingerprint(stream)
        data = stream.read(MAX_JSON + 1)
        if len(data) > MAX_JSON or fingerprint(stream) != before:
            raise ValueError("metadata_changed_or_large")
        return data


def source_files(source: Path) -> tuple[Path, list[str]]:
    source = safe_directory(source)
    objects = inventory_value(closed_bytes(source / INVENTORY))
    expected = set(DATABASE) | {INVENTORY} | objects.keys()
    found = set()
    total = 0
    for path in source.rglob("*"):
        if linked(path):
            raise ValueError("linked_source")
        if path.is_dir():
            continue
        relative = path.relative_to(source).as_posix()
        if relative not in expected or not path.is_file():
            raise ValueError("unexpected_source")
        size = path.stat().st_size
        if relative in objects and size != objects[relative]:
            raise ValueError("object_size_mismatch")
        if relative in DATABASE and size == 0:
            raise ValueError("empty_database_export")
        total += size
        if total > MAX_TOTAL:
            raise ValueError("bundle_too_large")
        found.add(relative)
    if found != expected:
        raise ValueError("missing_source")
    return source, sorted(found)


def copy_hash(source, output, expected: int) -> str:
    digest = hashlib.sha256()
    remaining = expected
    while remaining:
        chunk = source.read(min(CHUNK, remaining))
        if not chunk:
            raise ValueError("short_content")
        digest.update(chunk)
        if output:
            output.write(chunk)
        remaining -= len(chunk)
    if source.read(1):
        raise ValueError("extra_content")
    return digest.hexdigest()


def output_path(path: Path) -> Path:
    parent = safe_directory(path.parent)
    if path.exists() or linked(path) or path.name in {"", ".", ".."}:
        raise ValueError("new_output_required")
    return parent / path.name


def pack(source: Path, destination: Path):
    source, names = source_files(source)
    destination = output_path(destination)
    if destination.is_relative_to(source):
        raise ValueError("separate_output_required")
    records = []
    # A private staging directory keeps incomplete plaintext away from final names.
    with TemporaryDirectory(prefix=".we2day-bundle-", dir=destination.parent) as work:
        staged = Path(work) / "bundle.zip"
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output, ZipFile(output, "w", ZIP_STORED) as bundle:
            for name in names:
                item = source / name
                if any(linked(part) for part in (item, *item.parents)):
                    raise ValueError("linked_source")
                with item.open("rb") as stream:
                    before = fingerprint(stream)
                    entry = ZipInfo(name)
                    entry.external_attr = (stat.S_IFREG | 0o600) << 16
                    with bundle.open(entry, "w", force_zip64=True) as writer:
                        digest = copy_hash(stream, writer, before[0])
                    if fingerprint(stream) != before:
                        raise ValueError("source_changed")
                records.append({"path": name, "size": before[0], "sha256": digest})
            manifest = {
                "format": FORMAT,
                "created_at": datetime.now(UTC).isoformat(),
                "source": "operator_supplied_export",
                "files": records,
            }
            bundle.writestr(MANIFEST, json.dumps(manifest, sort_keys=True).encode())
        verify(staged)
        os.link(staged, destination)


def inspect_bundle(bundle: ZipFile) -> tuple[dict, dict[str, dict]]:
    entries = bundle.infolist()
    if not 5 <= len(entries) <= MAX_OBJECTS + 5:
        raise ValueError("invalid_entry_count")
    names = set()
    folded = set()
    total = 0
    for item in entries:
        name = safe_name(item.filename)
        mode = item.external_attr >> 16
        if (
            name.casefold() in folded
            or item.is_dir()
            or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
            or item.flag_bits & 1
        ):
            raise ValueError("invalid_entry")
        if item.compress_type != ZIP_STORED or item.file_size > MAX_TOTAL:
            raise ValueError("invalid_compression_or_size")
        total += item.file_size
        names.add(name)
        folded.add(name.casefold())
    if total > MAX_TOTAL + MAX_JSON or MANIFEST not in names:
        raise ValueError("invalid_bundle")
    if bundle.getinfo(MANIFEST).file_size > MAX_JSON:
        raise ValueError("metadata_too_large")
    manifest = json_value(bundle.read(MANIFEST))
    if not isinstance(manifest, dict) or set(manifest) != {
        "format",
        "created_at",
        "source",
        "files",
    }:
        raise ValueError("invalid_manifest")
    if (
        manifest["format"] not in {FORMAT, LEGACY_FORMAT}
        or manifest["source"] != "operator_supplied_export"
    ):
        raise ValueError("invalid_manifest")
    if not isinstance(manifest["created_at"], str):
        raise ValueError("invalid_created_at")
    created = datetime.fromisoformat(manifest["created_at"])
    if created.tzinfo is None:
        raise ValueError("invalid_created_at")
    if not isinstance(manifest["files"], list) or len(manifest["files"]) != len(names) - 1:
        raise ValueError("invalid_manifest")
    records = {}
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ValueError("invalid_record")
        name = safe_name(item["path"])
        if (
            name == MANIFEST
            or name in records
            or type(item["size"]) is not int
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("invalid_record")
        records[name] = item
    if set(records) != names - {MANIFEST} or not (set(DATABASE) | {INVENTORY}) <= records.keys():
        raise ValueError("invalid_record_set")
    if bundle.getinfo(INVENTORY).file_size > MAX_JSON:
        raise ValueError("metadata_too_large")
    objects = inventory_value(bundle.read(INVENTORY), allow_version=manifest["format"] == FORMAT)
    if set(records) != set(DATABASE) | {INVENTORY} | objects.keys():
        raise ValueError("inventory_mismatch")
    for name, record in records.items():
        if record["size"] != bundle.getinfo(name).file_size:
            raise ValueError("size_mismatch")
        if name in objects and record["size"] != objects[name]:
            raise ValueError("inventory_mismatch")
        if name in DATABASE and record["size"] == 0:
            raise ValueError("empty_database_export")
    if sum(record["size"] for record in records.values()) > MAX_TOTAL:
        raise ValueError("bundle_too_large")
    return manifest, records


def verify(path: Path) -> dict:
    with regular(path).open("rb") as stream:
        before = fingerprint(stream)
        with ZipFile(stream) as bundle:
            manifest, records = inspect_bundle(bundle)
            for name, record in records.items():
                with bundle.open(name) as item:
                    if copy_hash(item, None, record["size"]) != record["sha256"]:
                        raise ValueError("content_mismatch")
            if fingerprint(stream) != before:
                raise ValueError("bundle_changed")
    return {
        "created_at": manifest["created_at"],
        "files": len(records),
        "photos": len(records) - 4,
        "bytes": sum(item["size"] for item in records.values()),
    }


def unpack(path: Path, destination: Path) -> dict:
    # Only recover files; SQL is never executed. The caller controls later DB restoration.
    source = regular(path)
    with source.open("rb") as before_stream:
        before_verify = fingerprint(before_stream)
    result = verify(source)
    destination = output_path(destination)
    destination.mkdir(mode=0o700)
    try:
        with source.open("rb") as stream:
            before = fingerprint(stream)
            if before_verify != before:
                raise ValueError("bundle_changed")
            with ZipFile(stream) as bundle:
                _, records = inspect_bundle(bundle)
                for name, record in records.items():
                    target = destination / name
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if any(linked(part) for part in (target, *target.parents)):
                        raise ValueError("linked_output")
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as writer, bundle.open(name) as item:
                        if copy_hash(item, writer, record["size"]) != record["sha256"]:
                            raise ValueError("content_mismatch")
                if fingerprint(stream) != before:
                    raise ValueError("bundle_changed")
    except BaseException:
        # Do not recursively delete a destination that another process could have changed.
        # A failed recovery is explicitly marked and never reported as complete.
        marker = destination / ".incomplete"
        try:
            with marker.open("x", encoding="utf-8") as file:
                file.write("Incomplete recovery; inspect and remove privately.\n")
        except OSError:
            pass
        raise
    return result


def encrypted(action: str, source: Path, key: Path, destination: Path | None):
    if action == "snapshot":
        if destination is None:
            raise ValueError("output_required")
        destination = output_path(destination)
        parent = destination.parent
    else:
        source = regular(source)
        parent = safe_directory(source.parent)
    with TemporaryDirectory(prefix=".we2day-backup-", dir=parent) as work:
        staged = Path(work) / "bundle.zip"
        if action == "snapshot":
            pack(source, staged)
            process(staged, key, destination)
            process(destination, key, None, decrypt=True, original=staged)
            return verify(staged)
        process(source, key, staged, decrypt=True)
        if action == "restore":
            if destination is None:
                raise ValueError("output_required")
            return unpack(staged, destination)
        return verify(staged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["pack", "verify", "unpack", "snapshot", "verify-encrypted", "restore"]
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--key", type=Path)
    args = parser.parse_args()
    try:
        needs_output = args.action not in {"verify", "verify-encrypted"}
        needs_key = args.action in {"snapshot", "verify-encrypted", "restore"}
        if bool(args.output) != needs_output or bool(args.key) != needs_key:
            raise ValueError("invalid_arguments")
        if needs_key:
            result = encrypted(args.action, args.input, args.key, args.output)
        elif args.action == "pack":
            pack(args.input, args.output)
            result = verify(args.output)
        elif args.action == "unpack":
            result = unpack(args.input, args.output)
        else:
            result = verify(args.input)
        print(json.dumps({"integrity": "PASS", **result, "live_restore": False}))
        return 0
    except (OSError, ValueError, TypeError, KeyError, BadZipFile, InvalidTag, RuntimeError):
        print("FAIL: backup input, integrity, key or new-output requirement")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
