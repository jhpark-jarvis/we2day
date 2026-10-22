from uuid import uuid4

import psycopg
import pytest
from test_database import USERS, actor, connect_pair, reset_database  # noqa: F401
from test_photo_database import call, put, reserve


def test_trash_restore_retention_purge_retry_and_pair_permissions(database_url):
    dsn = database_url
    connect_pair(dsn)
    row = reserve(dsn)
    put(dsn, USERS[0], row)
    call(dsn, USERS[0], "complete_photo", row["id"])

    def change(user, action, version, request=None, confirmation=""):
        return call(
            dsn,
            user,
            "change_photo_lifecycle",
            row["id"],
            action,
            version,
            request or uuid4(),
            confirmation,
        )[0]

    request_id = uuid4()
    trashed = change(USERS[0], "trash", 1, request_id)
    assert trashed["trashed_by"] == USERS[0] and trashed["lifecycle_version"] == 2
    assert change(USERS[0], "trash", 1, request_id) == trashed
    with pytest.raises(psycopg.Error, match="photo_not_found"):
        change(USERS[2], "restore", 2)
    with pytest.raises(psycopg.Error, match="version_conflict"):
        change(USERS[1], "restore", 1)
    with pytest.raises(psycopg.Error, match="photo_retention_active"):
        change(USERS[0], "purge", 2, confirmation="영구 삭제")
    with pytest.raises(psycopg.Error, match="photo_confirmation_required"):
        change(USERS[0], "purge", 2)
    with actor(dsn, USERS[0]) as connection:
        assert connection.execute("delete from storage.objects").rowcount == 0
    restored = change(USERS[1], "restore", 2)
    assert restored["trashed_at"] is None and restored["lifecycle_version"] == 3
    change(USERS[1], "trash", 3)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "update photos set trashed_at=now()-interval '31 days', "
            "purge_after=now()-interval '1 day'"
        )
    # The 30-day minimum never implies automatic deletion or loss of restore before purge.
    assert change(USERS[0], "restore", 4)["lifecycle_version"] == 5
    change(USERS[0], "trash", 5)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "update photos set trashed_at=now()-interval '31 days', "
            "purge_after=now()-interval '1 day'"
        )
    purging = change(USERS[1], "purge", 6, confirmation="영구 삭제")
    assert purging["purging_at"] and purging["lifecycle_version"] == 7
    assert change(USERS[0], "purge", 7, confirmation="영구 삭제") == purging
    with pytest.raises(psycopg.Error, match="photo_deleting"):
        change(USERS[0], "restore", 7)
    with pytest.raises(psycopg.Error, match="photo_delete_incomplete"):
        call(dsn, USERS[0], "finish_photo_purge", row["id"])
    with actor(dsn, USERS[2]) as connection:
        assert connection.execute("delete from storage.objects").rowcount == 0
    # This SQL operation simulates the disposable Storage HTTP fixture only.
    with actor(dsn, USERS[0]) as connection:
        assert connection.execute("delete from storage.objects").rowcount == 1
    assert call(dsn, USERS[1], "finish_photo_purge", row["id"])[0]["deleted"] is True
    with actor(dsn, USERS[0]) as connection:
        assert connection.execute("select * from photos").fetchall() == []
