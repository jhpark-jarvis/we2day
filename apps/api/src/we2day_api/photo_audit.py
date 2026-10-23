"""Read-only photo lifecycle inventory. Never print object names or remove data."""

import argparse
import json
from pathlib import Path

import psycopg

from we2day_api.backup_collect import configuration, connection_options

QUERY = """
with p as (
  select *, couple_id::text || '/' || id::text || '.webp' as object_name
  from public.photos
), o as (
  select name, created_at, metadata from storage.objects where bucket_id='we2day-photos'
)
select
  (select count(*) from p) as photo_rows,
  (select count(*) from o) as storage_objects,
  (select count(*) from p where uploaded_at is null
    and created_at < now()-interval '24 hours') as stale_pending,
  (select count(*) from p where uploaded_at is not null
    and not exists(select 1 from o where o.name=p.object_name)) as missing_objects,
  (select count(*) from o where created_at < now()-interval '24 hours'
    and not exists(select 1 from p where p.object_name=o.name)) as unreferenced_objects,
  (select count(*) from p where purging_at < now()-interval '24 hours') as stalled_purges,
  (select count(*) from p where purge_after < now() and purging_at is null) as expired_trash,
  (select pg_database_size(current_database())) as database_bytes,
  (select coalesce(sum((metadata->>'size')::bigint),0) from o) as storage_bytes
"""


def audit(db):
    # One snapshot avoids misclassifying an upload that changes between separate queries.
    cursor = db.execute(QUERY)
    metrics = dict(
        zip([column.name for column in cursor.description], cursor.fetchone(), strict=True)
    )
    metrics = {key: int(value) for key, value in metrics.items()}
    attention = sum(
        metrics[key]
        for key in ("stale_pending", "missing_objects", "unreferenced_objects", "stalled_purges")
    )
    return {
        "format": 1,
        "status": "attention" if attention else "ok",
        "read_only": True,
        "deletion_enabled": False,
        **metrics,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        options = connection_options(configuration(args.config))
        options["options"] += " -c statement_timeout=15000"
        with psycopg.connect(**options) as db:
            if db.execute("show transaction_read_only").fetchone()[0] != "on":
                raise ValueError("read_only_required")
            print(json.dumps(audit(db)))
        return 0
    except Exception:
        print(
            json.dumps(
                {"format": 1, "status": "failed", "read_only": True, "deletion_enabled": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
