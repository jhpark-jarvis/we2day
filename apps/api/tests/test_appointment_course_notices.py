from copy import deepcopy
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from test_calendar_api import upstream  # noqa: F401
from test_database import USERS, actor, call, connect_pair, reset_database  # noqa: F401
from test_push import ENDPOINT, keys, manage
from test_routes_plans import CONTENT, change

from we2day_api.reminder_worker import ACL_CHECK, query


def confirmed(dsn, *, day="2026-01-01", title="synthetic course"):
    identifier = uuid4()
    content = {**deepcopy(CONTENT), "title": title, "date": day}
    content["activities"] *= 2
    change(dsn, USERS[0], identifier, "save", 0, content)
    change(dsn, USERS[0], identifier, "confirm", 1)
    return identifier, content


def progress(dsn):
    with psycopg.connect(dsn) as db:
        return db.execute(
            "select plan_id,publication,states,version from public.plan_visit_progress "
            "order by plan_id,publication"
        ).fetchall()


def test_mark_met_completes_only_linked_current_courses_and_preserves_manual_changes(database_url):
    dsn = database_url
    connect_pair(dsn)
    first, _ = confirmed(dsn)
    second, _ = confirmed(dsn, title="other same day")
    archived, _ = confirmed(dsn)
    change(dsn, USERS[0], archived, "archive", 2)
    confirmed(dsn, day="2026-01-02")
    call(
        dsn,
        USERS[0],
        "create_personal_appointment",
        "private",
        date(2026, 1, 1),
        None,
        "",
        "",
        uuid4(),
    )
    request = uuid4()
    args = (date(2026, 1, 1), True, "note", 0, request)
    saved = call(dsn, USERS[0], "save_meeting_day", *args)
    assert call(dsn, USERS[0], "save_meeting_day", *args) == saved
    rows = progress(dsn)
    assert {r[0] for r in rows} == {first, second}
    assert all(r[1:] == (1, ["visited", "visited"], 1) for r in rows)
    call(dsn, USERS[1], "change_visit_progress", first, 1, 0, "skipped", 1, uuid4())
    before = progress(dsn)
    call(dsn, USERS[0], "save_meeting_day", date(2026, 1, 1), True, "note edit", 1, uuid4())
    call(dsn, USERS[1], "save_meeting_day", date(2026, 1, 1), False, "note edit", 2, uuid4())
    assert progress(dsn) == before
    call(dsn, USERS[0], "save_meeting_day", date(2026, 1, 1), True, "note edit", 3, uuid4())
    assert all(r[2] == ["visited", "visited"] for r in progress(dsn))
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[1], "change_visit_progress", first, 1, 1, "skipped", 1, uuid4())


def test_met_completion_is_atomic_and_old_publications_are_preserved(database_url):
    dsn = database_url
    connect_pair(dsn)
    identifier, content = confirmed(dsn)
    call(dsn, USERS[0], "change_visit_progress", identifier, 1, 0, "skipped", 0, uuid4())
    changed = {**content, "title": "new publication"}
    change(dsn, USERS[0], identifier, "save", 2, changed)
    change(dsn, USERS[0], identifier, "confirm", 3, av=1)
    with psycopg.connect(dsn) as db:
        db.execute("""create function we2day_private.fixture_fail_progress() returns trigger
          language plpgsql as $$
          begin raise exception 'synthetic_progress_failure'; end $$;
          create trigger fixture_fail_progress before insert on public.plan_visit_progress
          for each row execute function we2day_private.fixture_fail_progress();""")
    try:
        with pytest.raises(psycopg.Error, match="synthetic_progress_failure"):
            call(dsn, USERS[0], "save_meeting_day", date(2026, 1, 1), True, "", 0, uuid4())
        with actor(dsn, USERS[0]) as db:
            assert db.execute("select count(*) from public.meeting_days").fetchone()[0] == 0
    finally:
        with psycopg.connect(dsn) as db:
            db.execute(
                "drop trigger fixture_fail_progress on public.plan_visit_progress; "
                "drop function we2day_private.fixture_fail_progress()"
            )
    call(dsn, USERS[0], "save_meeting_day", date(2026, 1, 1), True, "", 0, uuid4())
    assert [(r[1], r[2]) for r in progress(dsn)] == [
        (1, ["skipped", "planned"]),
        (2, ["visited", "visited"]),
    ]


def worker(dsn, function, *args):
    with actor(dsn, None, "we2day_reminder_worker") as db:
        assert query(db, ACL_CHECK)
        return query(
            db, f"select we2day_reminders.{function}({','.join('%s' for _ in args)})", args
        )


def subscribed_pair(dsn):
    connect_pair(dsn)
    public = keys()[1]
    for index, user in enumerate(USERS[:2]):
        endpoint = ENDPOINT + str(index)
        manage(dsn, user, "register", endpoint=endpoint, public=public)
        manage(dsn, user, "automatic_on", endpoint=endpoint, public=public)
    return public


@pytest.mark.parametrize("kind", ["shared", "personal"])
def test_new_appointment_queues_both_consented_members_once_and_keeps_payload_minimal(
    database_url, kind
):
    dsn = database_url
    public = subscribed_pair(dsn)
    request = uuid4()
    function = "create_personal_appointment" if kind == "personal" else "create_appointment"
    args = ("synthetic secret title", date(2026, 1, 1), None, "", "synthetic private note", request)
    appointment = call(dsn, USERS[0], function, *args)
    assert call(dsn, USERS[0], function, *args) == appointment
    with psycopg.connect(dsn) as db:
        assert db.execute(
            "select count(distinct owner_id),count(*) from we2day_reminders.deliveries "
            "where kind='appointment_created'"
        ).fetchone() == (2, 2)
    jobs = worker(dsn, "claim_due", 10)
    assert len(jobs) == 2
    assert worker(dsn, "claim_due", 10) == []
    for job in jobs:
        subscription = worker(dsn, "authorize_delivery", job["id"], job["lease"], public)
        assert set(subscription) == {"endpoint", "keys", "notification"}
        assert subscription["notification"] == {
            "type": "we2day-appointment-created-v1",
            "date": "2026-01-01",
            "event": job["id"],
        }
        assert "secret" not in str(subscription) and "private" not in str(subscription)
        assert worker(dsn, "finish_delivery", job["id"], job["lease"], "accepted")
    call(
        dsn,
        USERS[0],
        "update_appointment",
        appointment[0],
        1,
        "edited",
        date(2026, 1, 1),
        None,
        "",
        "",
    )
    assert worker(dsn, "claim_due", 10) == []


def test_creation_notices_recheck_opt_out_and_do_not_backfill_or_reconfirm(database_url):
    dsn = database_url
    public = subscribed_pair(dsn)
    manage(dsn, USERS[1], "automatic_off", endpoint=ENDPOINT + "1", public=public)
    identifier, _ = confirmed(dsn)
    jobs = worker(dsn, "claim_due", 10)
    assert len(jobs) == 1
    manage(dsn, USERS[0], "automatic_off", endpoint=ENDPOINT + "0", public=public)
    assert worker(dsn, "authorize_delivery", jobs[0]["id"], jobs[0]["lease"], public) is None
    manage(dsn, USERS[1], "automatic_on", endpoint=ENDPOINT + "1", public=public)
    change(dsn, USERS[0], identifier, "confirm", 2, av=1)
    assert worker(dsn, "claim_due", 10) == []


def test_appointment_course_lookup_has_exact_rls_scope_and_personal_short_circuit(upstream):  # noqa: F811
    client, calls, replies = upstream
    identifier = str(uuid4())
    replies.extend([(200, [{"id": identifier, "kind": "shared"}]), (200, [])])
    result = client.get(f"/appointments/{identifier}/course")
    assert result.status_code == 200 and result.json() is None
    assert calls[-1].url.params["appointment_id"] == f"eq.{identifier}"
    assert calls[-1].url.params["archived"] == "eq.false"
    assert calls[-1].url.params["published_content"] == "not.is.null"
    replies.append((200, [{"id": identifier, "kind": "personal"}]))
    size = len(calls)
    assert client.get(f"/appointments/{identifier}/course").json() is None
    assert len(calls) == size + 1
    replies.append((200, []))
    assert client.get(f"/appointments/{identifier}/course").status_code == 404
    assert client.get("/appointments/invalid/course").status_code == 422
