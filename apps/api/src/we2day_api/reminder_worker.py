"""Bounded one-shot worker. Only three private DB functions; never print credentials or jobs."""

import argparse
import json
import re
from collections import Counter

import psycopg
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from psycopg.conninfo import conninfo_to_dict
from py_vapid import Vapid02
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pywebpush import WebPushException, webpush

from we2day_api.push import RestrictedSession, decode_key, push_configuration, validate_endpoint


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WE2DAY_", extra="ignore", env_ignore_empty=True)
    reminder_worker_enabled: bool = False
    reminder_database_url: str = Field(default="", repr=False)
    push_enabled: bool = False
    push_private_key: str | None = Field(default=None, repr=False)
    push_subject: str | None = Field(default=None, repr=False)


# PUBLIC privileges also apply to NOINHERIT roles. Never repair global ACLs automatically.
# Supabase's RLS event trigger cannot be called directly or installed by this non-superuser.
ACL_CHECK = """
select current_user='we2day_reminder_worker'
  and not exists(select 1 from pg_roles where rolname=current_user and
    (rolsuper or rolinherit or rolcreatedb or rolcreaterole or rolreplication or rolbypassrls))
  and not exists(select 1 from pg_auth_members where member=(select oid from pg_roles
    where rolname=current_user))
  and not exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname in ('public','we2day_private','we2day_reminders','auth','storage')
    and c.relkind in ('r','v','m','p','f')
    and has_schema_privilege(current_user,n.oid,'USAGE')
    and has_table_privilege(current_user,c.oid,
      'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
  and not exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname !~ '^pg_' and n.nspname<>'information_schema'
    and p.prosecdef and has_schema_privilege(current_user,n.oid,'USAGE')
    and has_function_privilege(current_user,p.oid,'EXECUTE')
    and not (n.nspname='public' and p.proname='rls_auto_enable' and p.pronargs=0
      and p.prorettype='event_trigger'::regtype)
    and p.oid not in (
      'we2day_reminders.claim_due(integer)'::regprocedure,
      'we2day_reminders.authorize_delivery(uuid,uuid,text)'::regprocedure,
      'we2day_reminders.finish_delivery(uuid,uuid,text)'::regprocedure))
  and not exists(select 1 from pg_namespace n where n.nspname !~ '^pg_'
    and n.nspname<>'information_schema' and has_schema_privilege(current_user,n.oid,'CREATE'))
"""


def connection_options(database_url: str):
    """Validate without opening a connection; also used by offline preflight."""
    info = conninfo_to_dict(database_url)
    if (
        not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", info.get("host", ""))
        or not re.fullmatch(r"we2day_reminder_worker\.[a-z]{20}", info.get("user", ""))
        or info.get("port") not in {"5432", "6543"}
        or info.get("dbname") != "postgres"
        or not info.get("password")
        or set(info) - {"host", "port", "user", "password", "dbname", "sslmode", "sslrootcert"}
        or info.get("sslmode", "verify-full") != "verify-full"
    ):
        raise ValueError("invalid_worker_connection")
    return info | {"sslmode": "verify-full", "sslrootcert": info.get("sslrootcert", "system")}


def connect(settings: WorkerSettings):
    return psycopg.connect(
        **connection_options(settings.reminder_database_url),
        connect_timeout=5,
        prepare_threshold=None,
        autocommit=True,
    )


def query(connection, sql, args=()):
    # Each transaction carries its own limits, including transaction-pooler use.
    with connection.transaction():
        connection.execute("set local statement_timeout='10s'")
        connection.execute("set local lock_timeout='2s'")
        return connection.execute(sql, args).fetchone()[0]


def deliver(subscription: dict, config) -> str:
    key, _, subject = config

    def outcome(status):
        if 200 <= status < 300:
            return "accepted"
        if status in {404, 410}:
            return "expired"
        return "retry" if status in {429, 500, 502, 503, 504} else "rejected"

    try:
        validate_endpoint(subscription["endpoint"])
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), decode_key(subscription["keys"]["p256dh"], 65)
        )
        decode_key(subscription["keys"]["auth"], 16)
        response = webpush(
            subscription_info=subscription,
            data=json.dumps({"type": "we2day-anniversary-v1"}),
            vapid_private_key=Vapid02(private_key=key),
            vapid_claims={"sub": subject},
            ttl=60,
            timeout=4,
            requests_session=RestrictedSession(),
            verbose=False,
        )
        return outcome(response.status_code)
    except WebPushException as error:
        return outcome(error.response.status_code) if error.response is not None else "unknown"
    except requests.RequestException:
        return "unknown"  # The remote service may have accepted a timed-out request.
    except (ValueError, KeyError, TypeError):
        return "rejected"


def run_once(connection, config, *, check_only=False, sender=deliver):
    if query(connection, ACL_CHECK) is not True:
        raise ValueError("worker_privileges_rejected")
    if check_only:
        return {"checked": True}
    jobs = query(connection, "select we2day_reminders.claim_due(10)")
    counts = Counter()
    for job in jobs:
        subscription = query(
            connection,
            "select we2day_reminders.authorize_delivery(%s,%s,%s)",
            (job["id"], job["lease"], config[1]),
        )
        if subscription is None:
            counts["cancelled"] += 1
            continue
        result = sender(subscription, config)
        saved = query(
            connection,
            "select we2day_reminders.finish_delivery(%s,%s,%s)",
            (job["id"], job["lease"], result),
        )
        counts[result if saved else "unrecorded"] += 1
    return {"claimed": len(jobs), **counts}


def main():
    parser = argparse.ArgumentParser(description="Run one bounded anniversary Push batch")
    parser.add_argument(
        "--check", action="store_true", help="Check ACL only; no queue writes or sends"
    )
    args = parser.parse_args()
    stage = "configuration"
    try:
        settings = WorkerSettings()
        config = push_configuration(settings)
        if not config or (not args.check and not settings.reminder_worker_enabled):
            raise ValueError("worker_disabled_or_unconfigured")
        stage = "connection"
        with connect(settings) as connection:
            stage = "access_or_processing"
            result = run_once(connection, config, check_only=args.check)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Never reflect libpq errors, DSNs, endpoint responses or SQL parameters.
        print(f"FAIL: reminder_worker_{stage}; private details withheld")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
