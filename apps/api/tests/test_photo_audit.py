import psycopg
from test_database import USERS, connect_pair, reset_database  # noqa: F401
from test_photo_database import reserve

from we2day_api.photo_audit import read_audit


def test_inventory_distinguishes_recent_uploads_from_stale_and_missing(database_url):
    connect_pair(database_url)
    recent = reserve(database_url)
    old = reserve(database_url)
    missing = reserve(database_url)
    with psycopg.connect(database_url) as db:
        db.execute(
            "alter table storage.objects add column if not exists "
            "created_at timestamptz default now()"
        )
        db.execute(
            "update public.photos set created_at=now()-interval '25 hours' where id=%s",
            (old["id"],),
        )
        db.execute("update public.photos set uploaded_at=now() where id=%s", (missing["id"],))
        db.execute(
            "insert into storage.objects(bucket_id,name,metadata,created_at) "
            "values('we2day-photos','unknown', '{\"size\":42}',now()-interval '25 hours')"
        )
        db.commit()
        result = read_audit({"conninfo": database_url})
        assert (
            result["stale_pending"]
            == result["missing_objects"]
            == result["unreferenced_objects"]
            == 1
        )
        assert result["photo_rows"] == 3 and result["storage_bytes"] == 42
        assert result["status"] == "attention" and result["deletion_enabled"] is False
        assert "unknown" not in str(result) and recent["id"] not in str(result)
    with psycopg.connect(database_url) as db:
        assert db.execute("select count(*) from public.photos").fetchone()[0] == 3
        assert (
            db.execute("select count(*) from storage.objects where name='unknown'").fetchone()[0]
            == 1
        )
