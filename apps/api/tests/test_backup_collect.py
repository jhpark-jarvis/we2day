import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest

from we2day_api import backup_bundle as bundle
from we2day_api import backup_collect as collect
from we2day_api.local_archive import create_key, process


def test_configuration_rejects_wrong_project_host_and_permissions(tmp_path):
    path = tmp_path / "credentials.env"
    path.write_text("WE2DAY_BACKUP_DB_PASSWORD='fixture'\n")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="configuration_missing"):
        collect.configuration(path)
    certificate = tmp_path / "ca.crt"
    certificate.write_text("fixture")
    fields = {
        "WE2DAY_BACKUP_DB_PASSWORD": "fixture",
        "WE2DAY_BACKUP_STORAGE_SECRET_KEY": "sb_secret_fixture",
        "WE2DAY_SUPABASE_URL": "https://" + "a" * 20 + ".supabase.co",
        "PGHOST": "aws-0-test-1.pooler.supabase.com",
        "PGUSER": "postgres." + "a" * 20,
        "PGPORT": "5432",
        "PGDATABASE": "postgres",
        "PGSSLROOTCERT": str(certificate),
    }
    path.write_text("\n".join(f"{key}='{value}'" for key, value in fields.items()))
    assert collect.configuration(path) == fields
    fields["PGUSER"] = "postgres." + "b" * 20
    path.write_text("\n".join(f"{key}='{value}'" for key, value in fields.items()))
    with pytest.raises(ValueError, match="configuration_boundary"):
        collect.configuration(path)
    if os.name != "nt":
        path.chmod(0o644)
        with pytest.raises(ValueError, match="private_configuration_required"):
            collect.configuration(path)


@pytest.mark.parametrize("status,content", [(200, b"123"), (200, b"12345"), (302, b""), (404, b"")])
def test_download_bounds_and_redirect_refusal(tmp_path, status, content):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            status, content=content, headers={"Location": "https://other.invalid"}
        )

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client:
        with pytest.raises(ValueError):
            collect.download(
                client,
                {
                    "WE2DAY_SUPABASE_URL": "https://fixture.invalid",
                    "WE2DAY_BACKUP_STORAGE_SECRET_KEY": "fixture",
                },
                {"pair/photo.webp": {"size": 4}},
                tmp_path,
            )
    assert len(requests) == 1 and requests[0].method == "GET"


def test_successful_download_is_exact_and_never_overwrites(tmp_path):
    config = {
        "WE2DAY_SUPABASE_URL": "https://fixture.invalid",
        "WE2DAY_BACKUP_STORAGE_SECRET_KEY": "fixture",
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"1234"))
    ) as c:
        collect.download(c, config, {"pair/photo.webp": {"size": 4}}, tmp_path)
        with pytest.raises(FileExistsError):
            collect.download(c, config, {"pair/photo.webp": {"size": 4}}, tmp_path)
    assert (tmp_path / "storage/pair/photo.webp").read_bytes() == b"1234"


def test_dump_shares_snapshot_and_keeps_password_out_of_arguments(tmp_path, monkeypatch):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs["env"]))
        kwargs["stdout"].write(b"-- synthetic dump\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(collect.subprocess, "run", run)
    config = {
        key: "fixture" for key in ("PGHOST", "PGUSER", "PGPORT", "PGDATABASE", "PGSSLROOTCERT")
    }
    config["WE2DAY_BACKUP_DB_PASSWORD"] = "private-test-password"
    collect.dump(config, "0001-0002-1", tmp_path)
    assert len(calls) == 3
    for arguments, environment in calls:
        assert "private-test-password" not in " ".join(arguments)
        assert environment["PGSSLMODE"] == "verify-full"
        assert "default_transaction_read_only=on" in environment["PGOPTIONS"]
    assert "--no-role-passwords" in calls[0][0]
    assert all("--snapshot=0001-0002-1" in item[0] for item in calls[1:])
    # Auth/Storage service principals need their original object ownership on recovery.
    assert all("--no-owner" not in item[0] for item in calls[1:])
    assert {p.name for p in tmp_path.iterdir()} == {"roles.sql", "schema.sql", "data.sql"}


def test_failed_dump_never_looks_successful(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    config = {
        key: "fixture"
        for key in (
            "PGHOST",
            "PGUSER",
            "PGPORT",
            "PGDATABASE",
            "PGSSLROOTCERT",
            "WE2DAY_BACKUP_DB_PASSWORD",
        )
    }
    with pytest.raises(ValueError, match="database_dump_failed"):
        collect.dump(config, "snapshot", tmp_path)


def test_inventory_rejects_bad_metadata_and_path():
    class Connection:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, *args):
            return self

        def fetchall(self):
            return self.rows

    for name, size in [("../escape", 1), ("pair/photo.webp", True), ("pair/photo.webp", -1)]:
        with pytest.raises(ValueError):
            collect.objects(Connection([(name, {"size": size}, None)]))


def test_changed_inventory_never_publishes_and_cleans_plaintext(tmp_path, monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, *args):
            return SimpleNamespace(fetchone=lambda: ("snapshot",))

    keys, copies = tmp_path / "keys", tmp_path / "copies"
    keys.mkdir()
    copies.mkdir()
    key = keys / "archive.key"
    create_key(key)
    inventories = iter([{}, {"new.webp": {"size": 1}}])
    monkeypatch.setattr(collect, "connection_options", lambda _: {})
    monkeypatch.setattr(collect.psycopg, "connect", lambda **kwargs: Connection())
    monkeypatch.setattr(collect, "objects", lambda _: next(inventories))
    monkeypatch.setattr(collect, "dump", lambda *args: None)
    monkeypatch.setattr(collect, "download", lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match="storage_changed_retry"):
        collect.collect({}, copies / "new.enc", key)
    assert list(copies.iterdir()) == []


def test_existing_output_rejected_before_any_connection(tmp_path, monkeypatch):
    existing = tmp_path / "existing.enc"
    existing.write_bytes(b"preserve")
    monkeypatch.setattr(
        collect.psycopg, "connect", lambda **kwargs: pytest.fail("network attempted")
    )
    with pytest.raises(ValueError, match="new_output_required"):
        collect.collect({}, existing, tmp_path / "missing-key")
    assert existing.read_bytes() == b"preserve"


def test_verified_previous_photo_reused_only_with_same_server_version(tmp_path, monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, *args):
            return SimpleNamespace(fetchone=lambda: ("snapshot",))

    keys, copies = tmp_path / "keys", tmp_path / "copies"
    keys.mkdir()
    copies.mkdir()
    key = keys / "key"
    create_key(key)
    inventory = {"pair/photo.webp": {"size": 4, "metadata": {"eTag": "v1"}, "updated": "v1"}}
    monkeypatch.setattr(collect, "connection_options", lambda _: {})
    monkeypatch.setattr(collect.psycopg, "connect", lambda **kwargs: Connection())
    monkeypatch.setattr(collect, "objects", lambda _: inventory)

    def dump(config, snapshot, export):
        for name in bundle.DATABASE:
            (export / name).write_bytes(b"-- fixture\n")

    monkeypatch.setattr(collect, "dump", dump)
    requests = []
    client_class = httpx.Client
    body = [b"1234"]

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=body[0])

    monkeypatch.setattr(
        collect.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handle)),
    )
    config = {
        "WE2DAY_SUPABASE_URL": "https://fixture.invalid",
        "WE2DAY_BACKUP_STORAGE_SECRET_KEY": "fixture",
    }
    first, second, third = [copies / name for name in ("first.enc", "second.enc", "third.enc")]
    cold = collect.collect(config, first, key)
    saved = first.read_bytes()
    warm = collect.collect(config, second, key, previous=first)
    assert cold["photos_downloaded"] == 1 and warm["photos_reused"] == 1
    assert warm["photos_downloaded"] == 0 and len(requests) == 1
    recovered = tmp_path / "recovered"
    bundle.encrypted("restore", second, key, recovered)
    assert (recovered / "storage/pair/photo.webp").read_bytes() == b"1234"
    inventory["pair/photo.webp"]["updated"] = "changed"
    body[0] = b"5678"
    changed = collect.collect(config, third, key, previous=second)
    assert changed["photos_downloaded"] == 1 and changed["photos_reused"] == 0
    assert len(requests) == 2 and first.read_bytes() == saved
    inventory["pair/photo.webp"]["updated"] = "None"
    unknown = collect.collect(config, copies / "unknown.enc", key, previous=third)
    assert unknown["photos_reused"] == 0 and len(requests) == 3
    # A genuine v1 encrypted bundle has no version hint and must use GET.
    legacy_inventory = json.loads((recovered / bundle.INVENTORY).read_text())
    legacy_inventory["objects"][0].pop("version")
    (recovered / bundle.INVENTORY).write_text(json.dumps(legacy_inventory))
    current_zip, legacy_zip = tmp_path / "current.zip", tmp_path / "legacy.zip"
    bundle.pack(recovered, current_zip)
    with ZipFile(current_zip) as source, ZipFile(legacy_zip, "w") as output:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == bundle.MANIFEST:
                manifest = json.loads(content)
                manifest["format"] = bundle.LEGACY_FORMAT
                content = json.dumps(manifest).encode()
            output.writestr(info, content)
    legacy = copies / "legacy.enc"
    process(legacy_zip, key, legacy)
    inventory["pair/photo.webp"]["updated"] = "v1"
    body[0] = b"1234"
    fallback = collect.collect(config, copies / "fallback.enc", key, previous=legacy)
    assert fallback["photos_reused"] == 0 and len(requests) == 4
    assert not list(copies.glob(".we2day-*"))
    assert first.read_bytes() == saved


def test_corrupt_previous_archive_fails_before_source_access(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    keys.mkdir()
    key = keys / "key"
    create_key(key)
    previous = tmp_path / "previous.enc"
    previous.write_bytes(b"corrupt")
    monkeypatch.setattr(collect.psycopg, "connect", lambda **kwargs: pytest.fail("source accessed"))
    with pytest.raises(ValueError):
        collect.collect({}, tmp_path / "new.enc", key, previous=previous)
    assert previous.read_bytes() == b"corrupt" and not (tmp_path / "new.enc").exists()
    assert not list(tmp_path.glob(".we2day-*"))


def test_low_disk_reserve_stops_before_source_or_output(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    keys.mkdir()
    key = keys / "key"
    create_key(key)
    monkeypatch.setattr(collect.shutil, "disk_usage", lambda _: SimpleNamespace(free=100))
    monkeypatch.setattr(collect.psycopg, "connect", lambda **kwargs: pytest.fail("source accessed"))
    with pytest.raises(ValueError, match="backup_disk_reserve"):
        collect.collect({}, tmp_path / "new.enc", key)
    assert not (tmp_path / "new.enc").exists()
