"""Real SQL round trip in disposable PostgreSQL, with synthetic photo bytes only."""

import json
import subprocess
from pathlib import Path

import psycopg
import pytest
from database_fixture import temporary_database
from psycopg.conninfo import make_conninfo
from test_database import USERS, actor, connect_pair
from test_photo_database import call, put, reserve

from we2day_api import backup_bundle as backup
from we2day_api.local_archive import create_key


def test_encrypted_export_restores_sql_permissions_and_photo_bytes(request, tmp_path):
    if not request.config.getoption("--database"):
        pytest.skip("Use --database for isolated DB restoration")
    with temporary_database() as (dsn, container):
        with psycopg.connect(dsn) as connection:
            connection.execute("create role we2day_fixture_auth_owner nologin")
            connection.execute("alter schema auth owner to we2day_fixture_auth_owner")
            connection.execute("alter table auth.users owner to we2day_fixture_auth_owner")
        with psycopg.connect(dsn) as connection:
            for user in USERS:
                connection.execute("insert into auth.users(id) values (%s)", (user,))
        connect_pair(dsn)
        row = reserve(dsn)
        put(dsn, USERS[0], row)
        call(dsn, USERS[0], "complete_photo", row["id"])
        export = tmp_path / "export"
        export.mkdir()
        # Cluster roles already exist in this disposable cluster. Production roles need
        # their own approved export and password recovery procedure.
        (export / "roles.sql").write_text("-- Isolated cluster roles retained\n")
        for name, option in (("schema.sql", "--schema-only"), ("data.sql", "--data-only")):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "-U",
                    "postgres",
                    option,
                    "postgres",
                ],
                check=True,
                capture_output=True,
            )
            (export / name).write_bytes(result.stdout)
        with psycopg.connect(dsn) as connection:
            object_name = connection.execute("select name from storage.objects").fetchone()[0]
            expected_policies = connection.execute(
                "select schemaname, tablename, policyname from pg_policies order by 1,2,3"
            ).fetchall()
        photo = export / "storage" / object_name
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"x" * 100)
        (export / backup.INVENTORY).write_text(
            json.dumps(
                {
                    "bucket": "we2day-photos",
                    "objects": [{"name": object_name, "size": 100}],
                }
            )
        )
        keys, copies = tmp_path / "keys", tmp_path / "copies"
        keys.mkdir()
        copies.mkdir()
        key, archive = keys / "key.bin", copies / "we2day-rehearsal.enc"
        create_key(key)
        backup.encrypted("snapshot", export, key, archive)
        restored = tmp_path / "recovered"
        backup.encrypted("restore", archive, key, restored)
        subprocess.run(
            ["docker", "exec", container, "createdb", "-U", "postgres", "rehearsal"],
            check=True,
            capture_output=True,
        )
        for name in backup.DATABASE:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-U",
                    "postgres",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--dbname",
                    "rehearsal",
                ],
                input=(restored / name).read_bytes(),
                check=True,
                capture_output=True,
            )
        restored_dsn = make_conninfo(dsn, dbname="rehearsal")
        with psycopg.connect(restored_dsn) as connection:
            assert connection.execute(
                "select pg_get_userbyid(relowner) from pg_class where oid='auth.users'::regclass"
            ).fetchone() == ("we2day_fixture_auth_owner",)
            assert (
                connection.execute(
                    "select schemaname, tablename, policyname from pg_policies order by 1,2,3"
                ).fetchall()
                == expected_policies
            )
            assert (
                connection.execute("select name from storage.objects").fetchone()[0] == object_name
            )
        for user, count in ((USERS[0], 1), (USERS[1], 1), (USERS[2], 0)):
            with actor(restored_dsn, user) as connection:
                assert len(connection.execute("select * from photos").fetchall()) == count
        assert (restored / "storage" / Path(object_name)).read_bytes() == photo.read_bytes()
        assert archive.exists() and not list(copies.glob(".we2day-backup-*"))
