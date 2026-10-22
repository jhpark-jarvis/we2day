"""Disposable DB only. The production clock is replaced solely in this fixture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_push import ENDPOINT, keys, manage

from we2day_api.anniversaries import project
from we2day_api.reminder_worker import ACL_CHECK, query, run_once


@pytest.fixture(scope="module", autouse=True)
def clock_functions(database_url):
    names = [
        "public.manage_push_subscription(text,text,text,text,text)",
        "we2day_reminders.claim_due(integer)",
        "we2day_reminders.authorize_delivery(uuid,uuid,text)",
        "we2day_reminders.finish_delivery(uuid,uuid,text)",
    ]
    with psycopg.connect(database_url) as c:
        originals = [
            c.execute("select pg_get_functiondef(%s::regprocedure)", (n,)).fetchone()[0]
            for n in names
        ]
        c.execute("create table we2day_reminders.test_clock (value timestamptz)")
        c.execute("insert into we2day_reminders.test_clock values ('2026-10-22 08:55+09')")
        c.execute("""create function we2day_reminders.test_now() returns timestamptz
          language sql stable set search_path='' as $$
            select value from we2day_reminders.test_clock;
          $$; revoke all on function we2day_reminders.test_now() from public;""")
        for sql in originals:
            c.execute(sql.replace("now()", "we2day_reminders.test_now()"))
    yield
    with psycopg.connect(database_url) as c:
        for sql in originals:
            c.execute(sql)
        c.execute("drop function we2day_reminders.test_now()")
        c.execute("drop table we2day_reminders.test_clock")


def clock(dsn, value):
    with psycopg.connect(dsn) as c:
        c.execute("update we2day_reminders.test_clock set value=%s", (value,))


def worker(dsn, function, *args):
    with actor(dsn, None, "we2day_reminder_worker") as c:
        marks = ",".join("%s" for _ in args)
        return query(c, f"select we2day_reminders.{function}({marks})", args)


def state(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute("select state,attempts from we2day_reminders.deliveries").fetchall()


def seed(dsn):
    clock(dsn, "2026-10-22 08:55+09")
    space = connect_pair(dsn)
    row = call(
        dsn,
        USERS[0],
        "create_anniversary",
        "custom",
        "synthetic private title",
        date(2026, 10, 29),
        None,
        None,
        True,
        uuid4(),
    )[0]
    _, public = keys()
    manage(dsn, USERS[0], "register", public=public)
    manage(dsn, USERS[0], "automatic_on", public=public)
    clock(dsn, "2026-10-22 09:00+09")
    return row, public, space


def authorize(dsn, job, public):
    return worker(dsn, "authorize_delivery", job["id"], job["lease"], public)


def finish(dsn, job, outcome):
    return worker(dsn, "finish_delivery", job["id"], job["lease"], outcome)


def test_consent_is_separate_owner_only_and_registration_refresh(database_url):
    dsn = database_url
    clock(dsn, "2026-10-22 08:55+09")
    connect_pair(dsn)
    _, public = keys()
    manage(dsn, USERS[0], "register", public=public)
    assert manage(dsn, USERS[0], "status", public=public) == {
        "enabled": True,
        "automatic_enabled": False,
    }
    with pytest.raises(psycopg.Error, match="push_registration_required"):
        manage(dsn, USERS[1], "automatic_on", public=public)
    manage(dsn, USERS[0], "automatic_on", public=public)
    with psycopg.connect(dsn) as c:
        before = c.execute(
            "select generation,automatic_since from public.push_subscriptions"
        ).fetchone()
    clock(dsn, "2026-10-22 08:56+09")
    manage(dsn, USERS[0], "automatic_on", public=public)
    manage(dsn, USERS[0], "register", public=public)
    with psycopg.connect(dsn) as c:
        assert (
            c.execute("select generation,automatic_since from public.push_subscriptions").fetchone()
            == before
        )
    assert manage(dsn, USERS[0], "status", public=public)["automatic_enabled"] is True
    _, other = keys()
    manage(dsn, USERS[0], "register", public=other)
    assert manage(dsn, USERS[0], "status", public=other)["automatic_enabled"] is False
    manage(dsn, USERS[0], "automatic_on", public=other)
    manage(dsn, USERS[0], "remove_all", public=other)
    assert manage(dsn, USERS[0], "status", public=other)["automatic_enabled"] is False


def test_worker_role_has_only_functions_and_public_grants_fail_closed(database_url):
    dsn = database_url
    with actor(dsn, None, "we2day_reminder_worker") as c:
        assert query(c, ACL_CHECK) is True
    for statement in [
        "select * from public.anniversaries",
        "select * from public.push_subscriptions",
        "select * from auth.users",
        "select * from storage.objects",
        "select * from we2day_reminders.deliveries",
        "select public.manage_push_subscription('remove_all')",
        "select public.create_couple()",
    ]:
        with (
            actor(dsn, None, "we2day_reminder_worker") as c,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            c.execute(statement)
    for grant, revoke in [
        (
            "grant select on public.appointments to public",
            "revoke select on public.appointments from public",
        ),
        (
            "grant authenticated to we2day_reminder_worker",
            "revoke authenticated from we2day_reminder_worker",
        ),
        (
            "grant execute on function public.create_couple() to public",
            "revoke execute on function public.create_couple() from public",
        ),
    ]:
        try:
            with psycopg.connect(dsn) as c:
                c.execute(grant)
            with actor(dsn, None, "we2day_reminder_worker") as c:
                assert query(c, ACL_CHECK) is False
        finally:
            with psycopg.connect(dsn) as c:
                c.execute(revoke)


def test_database_occurrences_match_originals_and_python_projection(database_url):
    rows = [
        {"date": "2028-02-29", "month": None, "day": None, "annual": True},
        {"date": None, "month": 2, "day": 29, "annual": True},
        {"date": "2026-12-31", "month": None, "day": None, "annual": True},
        {"date": "2026-10-29", "month": None, "day": None, "annual": False},
    ]
    with psycopg.connect(database_url) as c:
        for row in rows:
            for start in [
                date(2026, 1, 1),
                date(2027, 2, 27),
                date(2028, 2, 28),
                date(2028, 12, 30),
            ]:
                projected = project({**row, "kind": "custom"}, start)["next_date"]
                for offset in range(4):
                    target = start + timedelta(days=offset)
                    actual = c.execute(
                        "select we2day_reminders.occurrence(%s,%s,%s,%s,%s)",
                        (*row.values(), target),
                    ).fetchone()[0]
                    assert actual is (projected == target)


def test_supabase_rls_event_trigger_is_not_directly_callable(database_url):
    dsn = database_url
    try:
        with psycopg.connect(dsn) as c:
            c.execute("""create function public.rls_auto_enable() returns event_trigger
              language plpgsql security definer as $$ begin null; end; $$;""")
        with actor(dsn, None, "we2day_reminder_worker") as c:
            assert query(c, ACL_CHECK) is True
        with (
            actor(dsn, None, "we2day_reminder_worker") as c,
            pytest.raises(psycopg.Error, match="trigger functions"),
        ):
            c.execute("select public.rls_auto_enable()")
        with (
            actor(dsn, None, "we2day_reminder_worker") as c,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            c.execute("""create event trigger fixture_event on ddl_command_end
              execute function public.rls_auto_enable()""")
        with psycopg.connect(dsn) as c:
            c.execute("drop function public.rls_auto_enable()")
            c.execute("""create function public.rls_auto_enable() returns void
              language plpgsql security definer as $$ begin null; end; $$;""")
        with actor(dsn, None, "we2day_reminder_worker") as c:
            assert query(c, ACL_CHECK) is False
    finally:
        with psycopg.connect(dsn) as c:
            c.execute("drop function if exists public.rls_auto_enable()")


def test_parallel_claim_and_single_authorization_finish(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(dsn, "claim_due", 1), range(2)))
    jobs = [j for batch in results for j in batch]
    assert len(jobs) == 1
    job = jobs[0]
    assert authorize(dsn, job | {"lease": str(uuid4())}, public) is None
    assert authorize(dsn, job, public)["endpoint"] == ENDPOINT
    assert authorize(dsn, job, public) is None
    assert finish(dsn, job, "accepted") is True
    assert finish(dsn, job, "accepted") is False
    assert worker(dsn, "claim_due", 10) == []
    assert state(dsn) == [("accepted", 1)]


@pytest.mark.parametrize(
    "mutation", ["version", "membership", "off", "expired", "remove", "rekey", "vapid"]
)
def test_latest_source_membership_and_device_rechecked(database_url, mutation):
    dsn = database_url
    _, public, _ = seed(dsn)
    job = worker(dsn, "claim_due", 10)[0]
    with psycopg.connect(dsn) as c:
        if mutation == "version":
            c.execute("update public.anniversaries set version=version+1")
        elif mutation == "membership":
            c.execute("delete from public.couple_members where user_id=%s", (USERS[0],))
        elif mutation == "expired":
            c.execute("update public.push_subscriptions set expires_at='2026-10-22 08:59+09'")
    if mutation == "off":
        manage(dsn, USERS[0], "automatic_off", public=public)
    elif mutation == "remove":
        manage(dsn, USERS[0], "remove_all", public=public)
    elif mutation == "rekey":
        manage(dsn, USERS[0], "register", public=keys()[1])
    assert authorize(dsn, job, keys()[1] if mutation == "vapid" else public) is None
    assert state(dsn) == [("cancelled", 0)]


def test_changed_unsent_source_can_reclaim_but_accepted_slot_never_repeats(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    job = worker(dsn, "claim_due", 10)[0]
    with psycopg.connect(dsn) as c:
        c.execute("update public.anniversaries set version=version+1")
    assert authorize(dsn, job, public) is None
    replacement = worker(dsn, "claim_due", 10)[0]
    assert replacement["id"] == job["id"] and replacement["lease"] != job["lease"]
    assert authorize(dsn, replacement, public)
    assert finish(dsn, replacement, "accepted")
    with psycopg.connect(dsn) as c:
        c.execute("update public.anniversaries set version=version+1,title='changed private text'")
    assert worker(dsn, "claim_due", 10) == []


def test_lease_recovery_only_before_send_and_unknown_not_retried(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    original = worker(dsn, "claim_due", 10)[0]
    clock(dsn, "2026-10-22 09:02+09")
    replacement = worker(dsn, "claim_due", 10)[0]
    assert replacement["lease"] != original["lease"]
    assert authorize(dsn, original, public) is None
    assert authorize(dsn, replacement, public)
    clock(dsn, "2026-10-22 09:04+09")
    assert worker(dsn, "claim_due", 10) == []
    assert finish(dsn, replacement, "accepted") is False
    assert state(dsn) == [("unknown", 1)]


def test_definite_retry_bound_and_new_registration_not_removed_by_late_expiry(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    for attempt, moment in enumerate(["09:00", "09:02", "09:06"], 1):
        clock(dsn, f"2026-10-22 {moment}+09")
        job = worker(dsn, "claim_due", 10)[0]
        assert authorize(dsn, job, public)
        assert finish(dsn, job, "retry")
        assert state(dsn) == [("queued" if attempt < 3 else "failed", attempt)]
        assert worker(dsn, "claim_due", 10) == []
    with psycopg.connect(dsn) as c:
        c.execute("delete from we2day_reminders.deliveries")
    job = worker(dsn, "claim_due", 10)[0]
    assert authorize(dsn, job, public)
    other = keys()[1]
    manage(dsn, USERS[0], "register", public=other)
    assert finish(dsn, job, "expired")
    assert manage(dsn, USERS[0], "status", public=other)["enabled"] is True


def test_window_and_opt_in_never_replay_prior_times(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    clock(dsn, "2026-10-22 08:59:59+09")
    assert worker(dsn, "claim_due", 10) == []
    clock(dsn, "2026-10-22 09:00:01+09")
    manage(dsn, USERS[0], "automatic_off", public=public)
    manage(dsn, USERS[0], "automatic_on", public=public)
    assert worker(dsn, "claim_due", 10) == []
    clock(dsn, "2026-10-22 10:00+09")
    assert worker(dsn, "claim_due", 10) == []
    with pytest.raises(psycopg.Error, match="invalid_batch"):
        worker(dsn, "claim_due", 21)


def test_worker_integration_reports_counts_without_jobs_or_private_text(database_url):
    dsn = database_url
    _, public, _ = seed(dsn)
    with actor(dsn, None, "we2day_reminder_worker") as c:
        checked = run_once(c, (None, public, "https://example.com"), check_only=True)
        assert checked == {"checked": True}
        result = run_once(c, (None, public, "https://example.com"), sender=lambda *_: "accepted")
    assert result == {"claimed": 1, "accepted": 1}
    assert ENDPOINT not in str(result) and "private" not in str(result)
