"""Disposable local PostgreSQL only. No cloud credentials or existing databases are used."""

import json
import secrets
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg


@contextmanager
def temporary_database(rest_port=None):
    name = f"we2day-test-{uuid4().hex[:12]}"
    password = secrets.token_hex(24)
    ports = ["--publish", "127.0.0.1::5432"]
    if rest_port:
        ports += ["--publish", f"127.0.0.1:{rest_port}:3000"]
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            *ports,
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "postgres:17-alpine",
        ],
        check=True,
        capture_output=True,
    )
    try:
        info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        port = info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
        for attempt in range(60):
            try:
                with psycopg.connect(dsn, connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if attempt == 59:
                    raise
                time.sleep(0.25)
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("""
                create role anon nologin;
                create role authenticated nologin;
                create role authenticator login password 'test-authenticator-password' noinherit;
                grant anon, authenticated to authenticator;
                create schema auth;
                create table auth.users (id uuid primary key);
                create function auth.uid() returns uuid language sql stable as $$
                  select coalesce(
                    nullif(current_setting('request.jwt.claim.sub', true), ''),
                    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
                  )::uuid;
                $$;
                grant usage on schema auth to anon, authenticated;
                grant execute on function auth.uid() to anon, authenticated;
                -- Minimal Storage SQL contract only; this is not a Storage server.
                create schema storage;
                create table storage.buckets (
                  id text primary key, name text, public boolean,
                  file_size_limit bigint, allowed_mime_types text[]
                );
                create table storage.objects (
                  id uuid primary key default gen_random_uuid(), bucket_id text,
                  name text, owner_id text, metadata jsonb,
                  unique(bucket_id,name)
                );
                alter table storage.objects enable row level security;
                grant usage on schema storage to authenticated, anon;
                grant select,insert,update,delete on storage.objects to authenticated;
            """)
            migrations = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
            for migration in sorted(migrations.glob("*.sql")):
                connection.execute(migration.read_text(encoding="utf-8"))
        yield dsn, name
    finally:
        subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True)
