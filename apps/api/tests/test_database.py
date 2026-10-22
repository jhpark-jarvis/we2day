from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest

USERS = [str(UUID(int=index)) for index in range(1, 6)]


@pytest.fixture(autouse=True)
def reset_database(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "truncate public.appointments, public.couple_invites, "
            "public.couple_members, public.couples, auth.users cascade"
        )
        for user in USERS:
            connection.execute("insert into auth.users(id) values (%s)", (user,))


@contextmanager
def actor(dsn, user, role="authenticated"):
    with psycopg.connect(dsn) as connection:
        connection.execute(f"set local role {role}")
        connection.execute("select set_config('request.jwt.claim.sub', %s, true)", (user or "",))
        yield connection


def call(dsn, user, function, *args):
    # Function names are test constants, never user input.
    with actor(dsn, user) as connection:
        placeholders = ",".join(["%s"] * len(args))
        return connection.execute(
            f"select * from public.{function}({placeholders})", args
        ).fetchone()


def connect_pair(dsn):
    space = call(dsn, USERS[0], "create_couple")[0]
    invite = call(dsn, USERS[0], "create_couple_invite")[0]
    joined = call(dsn, USERS[1], "accept_couple_invite", invite["token"])[0]
    assert joined == {"id": space["id"], "member_count": 2}
    return space


def test_invite_hash_rotation_reuse_and_anonymous(database_url):
    dsn = database_url
    assert call(dsn, USERS[0], "get_my_couple") == (None,)
    call(dsn, USERS[0], "create_couple")
    first = call(dsn, USERS[0], "create_couple_invite")[0]
    second = call(dsn, USERS[0], "create_couple_invite")[0]
    assert len(second["token"]) == 64 and first["token"] != second["token"]
    with psycopg.connect(dsn) as connection:
        stored = connection.execute("select token_hash from public.couple_invites").fetchone()[0]
        assert stored != second["token"] and len(stored) == 64
    with pytest.raises(psycopg.Error, match="invalid_invite"):
        call(dsn, USERS[1], "accept_couple_invite", first["token"])
    with pytest.raises(psycopg.Error, match="already_connected"):
        call(dsn, USERS[0], "accept_couple_invite", second["token"])
    call(dsn, USERS[1], "accept_couple_invite", second["token"])
    with pytest.raises(psycopg.Error, match="invalid_invite"):
        call(dsn, USERS[2], "accept_couple_invite", second["token"])
    with (
        actor(dsn, None, "anon") as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("select public.create_couple()")
    with pytest.raises(psycopg.Error, match="authentication_required"):
        call(dsn, None, "create_couple")


def test_expiry_and_no_write_bypass(database_url):
    dsn = database_url
    call(dsn, USERS[0], "create_couple")
    invite = call(dsn, USERS[0], "create_couple_invite")[0]
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "update public.couple_invites set expires_at = now() - interval '1 second'"
        )
    with pytest.raises(psycopg.Error, match="invalid_invite"):
        call(dsn, USERS[1], "accept_couple_invite", invite["token"])
    for sql in [
        "select * from public.couple_invites",
        "delete from public.couple_members",
        "insert into public.couples default values",
        "update public.appointments set version=9",
    ]:
        with (
            actor(dsn, USERS[0]) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(sql)


def test_concurrent_accept_has_only_one_winner(database_url):
    dsn = database_url
    call(dsn, USERS[0], "create_couple")
    invite = call(dsn, USERS[0], "create_couple_invite")[0]

    def accept(user):
        try:
            return call(dsn, user, "accept_couple_invite", invite["token"])[0]["member_count"]
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(accept, USERS[1:3]))
    assert result.count(2) == 1 and result.count("PT400") == 1
    with psycopg.connect(dsn) as connection:
        assert connection.execute("select count(*) from public.couple_members").fetchone() == (2,)


def test_same_user_cannot_create_two_couples(database_url):
    def create(_):
        try:
            return call(database_url, USERS[0], "create_couple")[0]["member_count"]
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(create, range(2)))
    assert sorted(map(str, result)) == ["1", "PT409"]
    with psycopg.connect(database_url) as connection:
        assert connection.execute("select count(*) from public.couples").fetchone() == (1,)


def test_shared_appointment_isolation_idempotency_and_conflict(database_url):
    dsn = database_url
    space = connect_pair(dsn)
    request = uuid4()
    args = ("함께 산책", "2026-10-24", "14:30", "산책길", "메모", request)
    row = call(dsn, USERS[0], "create_appointment", *args)
    assert call(dsn, USERS[0], "create_appointment", *args) == row
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, USERS[0], "create_appointment", "다른 제목", *args[1:])
    for member in USERS[:2]:
        with actor(dsn, member) as connection:
            assert connection.execute("select title from public.appointments").fetchall() == [
                (args[0],)
            ]
            assert connection.execute("select count(*) from public.couple_members").fetchone() == (
                2,
            )
    call(dsn, USERS[2], "create_couple")
    with actor(dsn, USERS[2]) as connection:
        assert connection.execute("select * from public.appointments").fetchall() == []
        assert (
            connection.execute(
                "select id from public.couples where id=%s", (space["id"],)
            ).fetchall()
            == []
        )
    with pytest.raises(psycopg.Error, match="appointment_not_found"):
        call(dsn, USERS[2], "update_appointment", row[0], 1, "침입", *args[1:5])
    updated = call(dsn, USERS[1], "update_appointment", row[0], 1, "산책 변경", *args[1:5])
    assert updated[7] == 2 and str(updated[9]) == USERS[1]
    with pytest.raises(psycopg.Error, match="version_conflict"):
        call(dsn, USERS[0], "update_appointment", row[0], 1, "덮어쓰기", *args[1:5])
    assert call(dsn, USERS[0], "create_appointment", *args)[2] == "산책 변경"


def test_concurrent_appointment_create_and_edit(database_url):
    dsn = database_url
    connect_pair(dsn)
    args = ("동시 요청", "2026-10-24", None, "", "", uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(
            pool.map(lambda _: call(dsn, USERS[0], "create_appointment", *args), range(2))
        )
    assert created[0][0] == created[1][0]

    def edit(user):
        try:
            call(dsn, user, "update_appointment", created[0][0], 1, user, *args[1:5])
            return "ok"
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(edit, USERS[:2]))
    assert sorted(result) == ["PT409", "ok"]


def test_anniversary_security_retry_and_concurrent_baseline(database_url):
    dsn = database_url
    connect_pair(dsn)
    args = ("relationship", "처음 만난 날", "2026-01-01", None, None, True, uuid4())

    def create(user):
        try:
            return call(dsn, user, "create_anniversary", *args)
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(create, USERS[:2]))
    assert result.count("PT409") == 1
    winner = USERS[0] if isinstance(result[0], tuple) else USERS[1]
    row = call(dsn, winner, "create_anniversary", *args)
    assert row[2:4] == args[:2] and row[4].isoformat() == args[2]
    with pytest.raises(psycopg.Error, match="request_conflict"):
        call(dsn, winner, "create_anniversary", "relationship", "변경", *args[2:])
    for user in USERS[:2]:
        with actor(dsn, user) as connection:
            assert connection.execute("select count(*) from public.anniversaries").fetchone() == (
                1,
            )
    call(dsn, USERS[2], "create_couple")
    with actor(dsn, USERS[2]) as connection:
        assert connection.execute("select * from public.anniversaries").fetchall() == []
    with pytest.raises(psycopg.Error, match="anniversary_not_found"):
        call(dsn, USERS[2], "update_anniversary", row[0], 1, *args[:6])
    for sql in [
        "select * from public.anniversaries",
        "select public.create_anniversary(null,null,null,null,null,null,null)",
    ]:
        with (
            actor(dsn, None, "anon") as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(sql)
    for sql in ["delete from public.anniversaries", "update public.anniversaries set version=9"]:
        with actor(dsn, winner) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(sql)

    def edit(user):
        try:
            call(dsn, user, "update_anniversary", row[0], 1, *args[:6])
            return "ok"
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, USERS[:2])) == ["PT409", "ok"]
    assert call(dsn, winner, "create_anniversary", *args)[8] == 2


@pytest.mark.parametrize(
    "kind,value,month,day,annual",
    [
        ("birthday", None, 2, 30, True),
        ("birthday", None, 13, 1, True),
        ("birthday", "2000-02-29", 2, 29, True),
        ("birthday", None, 2, 29, False),
        ("relationship", "2026-01-01", None, None, False),
        ("custom", None, None, None, True),
        ("custom", "1899-12-31", None, None, True),
    ],
)
def test_anniversary_rpc_input_validation(database_url, kind, value, month, day, annual):
    connect_pair(database_url)
    with pytest.raises(psycopg.Error, match="invalid_anniversary"):
        call(
            database_url,
            USERS[0],
            "create_anniversary",
            kind,
            "기념일",
            value,
            month,
            day,
            annual,
            uuid4(),
        )


def test_birthday_original_and_kind_immutable(database_url):
    connect_pair(database_url)
    args = ("birthday", "생일", None, 2, 29, True)
    row = call(database_url, USERS[0], "create_anniversary", *args, uuid4())
    assert row[4:8] == (None, 2, 29, True)
    with pytest.raises(psycopg.Error, match="invalid_anniversary"):
        call(
            database_url,
            USERS[1],
            "update_anniversary",
            row[0],
            1,
            "custom",
            "기념일",
            "2028-02-29",
            None,
            None,
            True,
        )


@pytest.mark.parametrize(
    "title,date,time",
    [
        ("", "2026-10-24", None),
        ("제목", "1999-12-31", None),
        ("제목", "2026-10-24", "24:00"),
        ("제목", "2026-10-24", "12:30:01"),
    ],
)
def test_rpc_validates_even_without_fastapi(database_url, title, date, time):
    connect_pair(database_url)
    with pytest.raises(psycopg.Error, match="invalid_appointment"):
        call(database_url, USERS[0], "create_appointment", title, date, time, "", "", uuid4())
