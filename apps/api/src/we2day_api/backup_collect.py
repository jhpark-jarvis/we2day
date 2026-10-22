"""Read-only PostgreSQL/Storage collection. Credentials, SQL and photos never enter stdout."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

import httpx
import psycopg
from dotenv import dotenv_values

from we2day_api.backup_bundle import MAX_OBJECTS, MAX_TOTAL, encrypted, output_path, safe_name
from we2day_api.local_archive import key_bytes

BUCKET = "we2day-photos"


def configuration(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("configuration_file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("private_configuration_required")
    value = dotenv_values(path, encoding="utf-8-sig")
    fields = {
        "WE2DAY_BACKUP_DB_PASSWORD",
        "WE2DAY_BACKUP_STORAGE_SECRET_KEY",
        "PGHOST",
        "PGUSER",
        "PGPORT",
        "PGDATABASE",
        "PGSSLROOTCERT",
        "WE2DAY_SUPABASE_URL",
    }
    if any(not value.get(field) for field in fields):
        raise ValueError("configuration_missing")
    url = value["WE2DAY_SUPABASE_URL"].rstrip("/")
    if (
        not re.fullmatch(r"https://[a-z]{20}\.supabase\.co", url)
        or not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", value["PGHOST"])
        or value["PGUSER"] != "postgres." + url.split("//")[1].split(".")[0]
        or value["PGPORT"] != "5432"
        or value["PGDATABASE"] != "postgres"
        or not value["WE2DAY_BACKUP_STORAGE_SECRET_KEY"].startswith("sb_secret_")
        or not Path(value["PGSSLROOTCERT"]).is_file()
    ):
        raise ValueError("configuration_boundary")
    return {field: value[field] for field in fields} | {"WE2DAY_SUPABASE_URL": url}


def connection_options(config):
    return {
        "host": config["PGHOST"],
        "user": config["PGUSER"],
        "port": config["PGPORT"],
        "dbname": config["PGDATABASE"],
        "password": config["WE2DAY_BACKUP_DB_PASSWORD"],
        "sslmode": "verify-full",
        "sslrootcert": config["PGSSLROOTCERT"],
        "connect_timeout": 10,
        "options": "-c default_transaction_read_only=on",
    }


def objects(connection):
    rows = connection.execute(
        "select name, metadata, updated_at from storage.objects where bucket_id=%s "
        "order by name limit %s",
        (BUCKET, MAX_OBJECTS + 1),
    ).fetchall()
    if len(rows) > MAX_OBJECTS:
        raise ValueError("object_limit")
    result, total, folded = {}, 0, set()
    for name, metadata, updated in rows:
        name = safe_name(name)
        size = metadata.get("size") if isinstance(metadata, dict) else None
        if type(size) is not int or size < 0 or name.casefold() in folded:
            raise ValueError("object_metadata")
        total += size
        if total > MAX_TOTAL:
            raise ValueError("object_size_limit")
        result[name] = {"size": size, "metadata": metadata, "updated": str(updated)}
        folded.add(name.casefold())
    return result


def download(client, config, inventory, directory):
    for name, item in inventory.items():
        target = directory / "storage" / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        size = 0
        with client.stream(
            "GET",
            config["WE2DAY_SUPABASE_URL"]
            + "/storage/v1/object/"
            + BUCKET
            + "/"
            + quote(name, safe="/"),
            headers={
                "apikey": config["WE2DAY_BACKUP_STORAGE_SECRET_KEY"],
                "Accept-Encoding": "identity",
            },
        ) as response:
            if response.status_code != 200:
                raise ValueError("storage_download")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("storage_size")
                    output.write(chunk)
        if size != item["size"]:
            raise ValueError("storage_size")


def limit_output():
    import resource

    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TOTAL, MAX_TOTAL))


def dump(config, snapshot, directory):
    # The password is passed via the child environment, never argv or shell evaluation.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update(
        {key: config[key] for key in ("PGHOST", "PGUSER", "PGPORT", "PGDATABASE", "PGSSLROOTCERT")}
    )
    environment.update(
        PGPASSWORD=config["WE2DAY_BACKUP_DB_PASSWORD"],
        PGSSLMODE="verify-full",
        PGCONNECT_TIMEOUT="10",
        PGOPTIONS="-c default_transaction_read_only=on",
    )
    commands = {
        "roles.sql": ["pg_dumpall", "--roles-only", "--no-role-passwords", "--no-password"],
        "schema.sql": [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-password",
            "--lock-wait-timeout=5s",
            "--snapshot=" + snapshot,
        ],
        "data.sql": [
            "pg_dump",
            "--data-only",
            "--no-owner",
            "--no-password",
            "--lock-wait-timeout=5s",
            "--snapshot=" + snapshot,
        ],
    }
    for name, arguments in commands.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            result = subprocess.run(
                arguments,
                env=environment,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
                preexec_fn=limit_output if os.name != "nt" else None,
            )
        if result.returncode:
            raise ValueError("database_dump_failed")
        if (directory / name).stat().st_size > MAX_TOTAL:
            raise ValueError("dump_size_limit")


def collect(config, destination: Path, key: Path):
    destination = output_path(destination)
    key_bytes(key)
    if key.parent.resolve() == destination.parent:
        raise ValueError("separate_key_required")
    parent = destination.parent
    with TemporaryDirectory(prefix=".we2day-collection-", dir=parent) as workspace:
        export = Path(workspace)
        with psycopg.connect(**connection_options(config), autocommit=True) as connection:
            with connection.transaction():
                connection.execute("set transaction isolation level repeatable read, read only")
                connection.execute("set local statement_timeout='30s'")
                connection.execute("set local idle_in_transaction_session_timeout='15min'")
                inventory = objects(connection)
                snapshot = connection.execute("select pg_export_snapshot()").fetchone()[0]
                dump(config, snapshot, export)
                with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                    download(client, config, inventory, export)
            # Read committed AFTER the shared dump snapshot, detecting additions/removals/updates.
            if objects(connection) != inventory:
                raise ValueError("storage_changed_retry")
        (export / "storage-inventory.json").write_text(
            json.dumps(
                {
                    "bucket": BUCKET,
                    "objects": [
                        {"name": name, "size": item["size"]} for name, item in inventory.items()
                    ],
                }
            ),
            encoding="utf-8",
        )
        return encrypted("snapshot", export, key, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = collect(configuration(args.config), args.output, args.key)
        print(json.dumps({"collection": "PASS", **result, "live_restore": False}))
        return 0
    except Exception:
        # Never emit URLs, SQL, object names, subprocess stderr or exception messages.
        print("FAIL: backup collection prerequisites, consistency or integrity")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
