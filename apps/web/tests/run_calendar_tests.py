"""Run browser -> Next -> FastAPI -> PostgREST -> PostgreSQL with synthetic identities."""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api" / "tests"))
from database_fixture import temporary_database  # noqa: E402


def main():
    screenshots = "--screenshots" in sys.argv
    photos = "--photos" in sys.argv or screenshots
    places = "--places" in sys.argv
    plans = "--plans" in sys.argv
    journey = "--journey" in sys.argv
    organizer = "--organizer" in sys.argv
    jwt_secret = "local-calendar-fixture-secret-32-chars-minimum"
    with temporary_database(rest_port=54330) as (dsn, database_name):
        with psycopg.connect(dsn) as connection:
            if photos:
                connection.execute("""
                  -- Test-only bridge for the in-memory Storage HTTP fixture.
                  create function public.fixture_put_object(p_name text,p_bytes integer)
                  returns void language sql security invoker set search_path='' as $$
                    insert into storage.objects(bucket_id,name,owner_id,metadata)
                    values('we2day-photos',p_name,auth.uid()::text,
                      jsonb_build_object('size',p_bytes,'mimetype','image/webp'));
                  $$;
                  create function public.fixture_read_object(p_name text) returns boolean
                  language sql security invoker set search_path='' as $$
                    select exists(select 1 from storage.objects
                      where bucket_id='we2day-photos' and name=p_name);
                  $$;
                  create function public.fixture_remove_object(p_name text) returns integer
                  language sql security invoker set search_path='' as $$
                    with removed as (delete from storage.objects
                      where bucket_id='we2day-photos' and name=p_name returning 1)
                    select count(*)::integer from removed;
                  $$;
                  create function public.fixture_age_photo_trash() returns void
                  language sql security definer set search_path='' as $$
                    update public.photos set trashed_at=now()-interval '31 days',
                      purge_after=now()-interval '1 day' where trashed_at is not null;
                  $$;
                  revoke all on function public.fixture_put_object(text,integer),
                    public.fixture_read_object(text),public.fixture_remove_object(text),
                    public.fixture_age_photo_trash() from public,anon;
                  grant execute on function public.fixture_put_object(text,integer),
                    public.fixture_read_object(text),public.fixture_remove_object(text),
                    public.fixture_age_photo_trash() to authenticated;
                """)
            for value in [
                "33333333-3333-4333-8333-333333333333",
                "44444444-4444-4444-8444-444444444444",
                "55555555-5555-4555-8555-555555555555",
            ]:
                connection.execute("insert into auth.users(id) values (%s)", (value,))
        name = f"{database_name}-rest"
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--network",
                f"container:{database_name}",
                "--env",
                "PGRST_DB_URI=postgres://authenticator:test-authenticator-password@127.0.0.1:5432/postgres",
                "--env",
                "PGRST_DB_SCHEMAS=public",
                "--env",
                "PGRST_DB_ANON_ROLE=anon",
                "--env",
                f"PGRST_JWT_SECRET={jwt_secret}",
                "postgrest/postgrest:v14.10",
            ],
            check=True,
            capture_output=True,
        )
        try:
            for attempt in range(60):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:54330/", timeout=1):
                        break
                except (urllib.error.URLError, TimeoutError):
                    if attempt == 59:
                        raise
                    time.sleep(0.25)
            env = {
                **os.environ,
                "WE2DAY_TEST_JWT_SECRET": jwt_secret,
                "WE2DAY_TEST_REST_URL": "http://127.0.0.1:54330",
                "WE2DAY_TEST_AUTH_PROVIDERS": "password",
                "WE2DAY_TEST_PHOTO_STORAGE": "1" if photos else "",
            }
            result = subprocess.run(
                [
                    shutil.which("npm") or "npm",
                    "exec",
                    "--workspace",
                    "@we2day/web",
                    "--",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.screenshots.config.ts"
                    if screenshots
                    else "playwright.organizer.config.ts"
                    if organizer
                    else "playwright.journey.config.ts"
                    if journey
                    else "playwright.plans.config.ts"
                    if plans
                    else "playwright.sharing.config.ts"
                    if photos
                    else "playwright.places.config.ts"
                    if places
                    else "playwright.calendar.config.ts",
                    *[
                        arg
                        for arg in sys.argv[1:]
                        if arg
                        not in {
                            "--photos",
                            "--places",
                            "--plans",
                            "--journey",
                            "--organizer",
                            "--screenshots",
                        }
                    ],
                ],
                cwd=ROOT,
                env=env,
                check=False,
            )
            return result.returncode
        finally:
            subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
