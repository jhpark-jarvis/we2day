"""Portable read-only record copies; checksums detect corruption, not authenticity."""

import hashlib
import json
from datetime import UTC, datetime

MAX_FILE_BYTES = 5 * 1024 * 1024
EXPORT_FIELDS = {
    "appointments": [
        "id",
        "title",
        "date",
        "time",
        "place",
        "note",
        "version",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "anniversaries": [
        "id",
        "kind",
        "title",
        "date",
        "month",
        "day",
        "annual",
        "version",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "meeting_days": ["date", "met", "note", "version", "updated_by", "updated_at"],
    "meeting_routes": [
        "date",
        "start_name",
        "start_lat",
        "start_lng",
        "end_name",
        "end_lat",
        "end_lng",
        "version",
        "updated_by",
        "updated_at",
    ],
    "date_plans": [
        "id",
        "content",
        "published_content",
        "published_revision",
        "appointment_id",
        "archived",
        "version",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "date_reports": [
        "plan_id",
        "author_id",
        "observed_plan_version",
        "plan_snapshot",
        "content",
        "shared",
        "version",
        "created_at",
        "updated_at",
    ],
    "photos": [
        "id",
        "date",
        "caption",
        "filename",
        "device",
        "captured_at",
        "file_modified",
        "width",
        "height",
        "bytes",
        "created_by",
        "uploaded_at",
        "lifecycle_version",
    ],
    "wishes": [
        "id",
        "title",
        "kind",
        "note",
        "done",
        "archived",
        "version",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "shared_checklists": [
        "id",
        "title",
        "note",
        "items",
        "archived",
        "version",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "shared_goals": [
        "id",
        "title",
        "target_date",
        "steps",
        "completed",
        "archived",
        "version",
        "updated_by",
        "created_at",
        "updated_at",
    ],
    "couple_questions": ["id", "date", "prompt", "created_by", "created_at"],
    "question_answers": [
        "question_id",
        "author_id",
        "content",
        "shared",
        "skipped",
        "version",
        "updated_at",
    ],
    "timezone_preferences": ["user_id", "timezone", "version", "updated_at"],
    "roulette_wheels": [
        "id",
        "title",
        "candidates",
        "archived",
        "version",
        "updated_by",
        "updated_at",
    ],
    "roulette_draws": [
        "id",
        "wheel_id",
        "wheel_version",
        "candidates",
        "selected_index",
        "drawn_by",
        "drawn_at",
    ],
    "plan_visit_progress": [
        "plan_id",
        "publication",
        "snapshot",
        "states",
        "version",
        "updated_by",
        "updated_at",
    ],
}


def canonical(payload):
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def encode_snapshot(kind, rows, start, end, include_private):
    payload = {
        "kind": kind,
        "start_date": str(start),
        "end_date": str(end),
        "exported_at": datetime.now(UTC).isoformat(),
        "include_private": include_private,
        "records": [{k: row[k] for k in EXPORT_FIELDS[kind]} for row in rows],
    }
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    content = canonical(
        {"format": "we2day-record-snapshot", "version": 1, "sha256": digest, "payload": payload}
    )
    if len(rows) > 500 or len(content) > MAX_FILE_BYTES:
        raise ValueError("snapshot_too_large")
    return content


def unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate_key")
        obj[key] = value
    return obj


def inspect_snapshot(content):
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("snapshot_too_large")
    try:
        doc = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")),
        )
        if (
            set(doc) != {"format", "version", "sha256", "payload"}
            or doc["format"] != "we2day-record-snapshot"
            or type(doc["version"]) is not int
            or doc["version"] != 1
        ):
            raise ValueError("unsupported_format")
        payload = doc["payload"]
        if set(payload) != {
            "kind",
            "start_date",
            "end_date",
            "exported_at",
            "include_private",
            "records",
        }:
            raise ValueError("invalid_payload")
        kind = payload["kind"]
        records = payload["records"]
        if (
            kind not in EXPORT_FIELDS
            or type(records) is not list
            or len(records) > 500
            or type(payload["include_private"]) is not bool
        ):
            raise ValueError("invalid_records")
        from datetime import date

        start, end = (
            date.fromisoformat(payload["start_date"]),
            date.fromisoformat(payload["end_date"]),
        )
        if not date(2000, 1, 1) <= start <= end <= date(2100, 12, 31) or (end - start).days > 365:
            raise ValueError("invalid_dates")
        if datetime.fromisoformat(payload["exported_at"]).utcoffset() is None:
            raise ValueError("invalid_timestamp")
        for row in records:
            if not isinstance(row, dict) or set(row) != set(EXPORT_FIELDS[kind]):
                raise ValueError("invalid_record")
        if hashlib.sha256(canonical(payload)).hexdigest() != doc["sha256"]:
            raise ValueError("checksum_mismatch")
        return {"kind": kind, "count": len(records), "version": 1}
    except (KeyError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid_snapshot") from error


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Check a record copy locally, without import or network"
    )
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        with args.file.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        result = inspect_snapshot(content)
    except (OSError, ValueError):
        print("FAIL: invalid or damaged snapshot; no data written")
        return 1
    print(
        f"PASS: format v{result['version']}; kind={result['kind']}; "
        f"records={result['count']}; no data written"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
