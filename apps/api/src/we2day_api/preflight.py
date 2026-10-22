"""Read-only .env review. No network, provisioning, credentials or URLs in output."""

import argparse
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class InvalidEnvironment(ValueError):
    pass


def read_environment(path):
    if path.stat().st_size > 65536:
        raise InvalidEnvironment()
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not re.fullmatch(r"[A-Z_][A-Z_0-9]*", key) or key in values:
            raise InvalidEnvironment()
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise InvalidEnvironment()
            value = value[1:-1]
        if "${" in value or "\x00" in value:
            raise InvalidEnvironment()
        values[key] = value
    return values


def origin(value, local=False):
    try:
        url = urlsplit(value)
        if (
            url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
            or not url.hostname
            or url.port == 0
        ):
            return None
        if url.scheme != "https" and not (
            local and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
        ):
            return None
        return f"{url.scheme}://{url.netloc}"
    except (ValueError, TypeError):
        return None


def public_key(value):
    if value.startswith("sb_publishable_") and len(value) > 20:
        return True
    try:
        parts = value.split(".")
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return payload.get("role") == "anon"
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return False


def review(web, api, production=False, compose=False, worker=None):
    checks = []

    def add(name, ok, warn=False):
        checks.append({"check": name, "status": "PASS" if ok else "WARN" if warn else "FAIL"})

    site = origin(web.get("WE2DAY_SITE_URL", "http://127.0.0.1:3000"), not production)
    add("site_https_origin" if production else "site_origin", bool(site))
    web_project = origin(web.get("WE2DAY_SUPABASE_URL", ""), not production)
    api_project = origin(api.get("WE2DAY_SUPABASE_URL", ""), not production)
    add("same_supabase_project", bool(web_project and web_project == api_project))
    for name, env in [("web", web), ("api", api)]:
        add(f"{name}_publishable_key", public_key(env.get("WE2DAY_SUPABASE_PUBLISHABLE_KEY", "")))
        add(
            f"{name}_no_admin_or_public_secret",
            not any(
                v
                and (
                    "SERVICE_ROLE" in k
                    or k.endswith("SUPABASE_SECRET_KEY")
                    or "REMINDER_DATABASE_URL" in k
                    or (name == "web" and "PUSH_PRIVATE_KEY" in k)
                    or (
                        k.startswith("NEXT_PUBLIC_")
                        and any(s in k for s in ["SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY"])
                    )
                )
                for k, v in env.items()
            ),
        )
    add(
        "same_publishable_key",
        web.get("WE2DAY_SUPABASE_PUBLISHABLE_KEY") == api.get("WE2DAY_SUPABASE_PUBLISHABLE_KEY"),
        warn=True,
    )
    providers = web.get("WE2DAY_AUTH_PROVIDERS", "password").split(",")
    providers = [p.strip() for p in providers]
    add(
        "configured_login_methods",
        bool(providers)
        and len(providers) == len(set(providers))
        and all(p in {"password", "google", "kakao"} for p in providers),
    )
    cors = (
        '["http://localhost:3000","http://127.0.0.1:3000"]'
        if compose
        else api.get("WE2DAY_CORS_ORIGINS", '["http://localhost:3000","http://127.0.0.1:3000"]')
    )
    try:
        allowed = json.loads(cors)
        add(
            "cors_site_and_exact_origins",
            isinstance(allowed, list)
            and bool(site)
            and site in allowed
            and all(isinstance(u, str) and origin(u, not production) == u for u in allowed),
        )
    except (ValueError, TypeError):
        add("cors_site_and_exact_origins", False)
    if production and compose:
        add("local_compose_requires_production_override", False)
    upstream = "http://api:8000" if compose else web.get("WE2DAY_API_URL", "http://127.0.0.1:8000")
    # Internal container HTTP is allowed; never use this URL in the browser.
    try:
        u = urlsplit(upstream)
        add(
            "server_api_url",
            u.scheme in {"http", "https"}
            and bool(u.hostname)
            and not (u.username or u.password or u.query or u.fragment or u.path not in ("", "/")),
        )
    except ValueError:
        add("server_api_url", False)
    enabled = api.get("WE2DAY_NAVER_SEARCH_ENABLED", "false").lower()
    add("search_enabled_value", enabled in {"true", "false", "1", "0"})
    if enabled in {"true", "1"}:
        add(
            "search_credentials_present",
            bool(
                api.get("WE2DAY_NAVER_SEARCH_CLIENT_ID")
                and api.get("WE2DAY_NAVER_SEARCH_CLIENT_SECRET")
            ),
        )
    add(
        "maps_optional_configuration",
        bool(re.fullmatch(r"[a-zA-Z0-9_-]{3,128}", web.get("WE2DAY_NAVER_MAPS_CLIENT_ID", ""))),
        warn=True,
    )
    push_enabled = api.get("WE2DAY_PUSH_ENABLED", "false").lower()
    add("push_enabled_value", push_enabled in {"true", "false", "1", "0"})
    if push_enabled in {"true", "1"}:
        private = api.get("WE2DAY_PUSH_PRIVATE_KEY", "")
        subject = api.get("WE2DAY_PUSH_SUBJECT", "")
        add(
            "push_server_configuration",
            bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", private))
            and (subject.startswith("mailto:") and "@" in subject or bool(origin(subject))),
        )
    automatic = api.get("WE2DAY_PUSH_AUTOMATIC_ENABLED", "false").lower()
    add("automatic_enabled_value", automatic in {"true", "false", "1", "0"})
    automatic_on = automatic in {"true", "1"}
    if automatic_on:
        add(
            "automatic_requires_push_and_worker_review",
            push_enabled in {"true", "1"} and worker is not None,
        )
    if worker is not None:
        # No connections or environment mutation. Reuse the actual worker's restrictions.
        from we2day_api.reminder_worker import connection_options

        allowed = {
            "WE2DAY_REMINDER_WORKER_ENABLED",
            "WE2DAY_REMINDER_DATABASE_URL",
            "WE2DAY_PUSH_ENABLED",
            "WE2DAY_PUSH_PRIVATE_KEY",
            "WE2DAY_PUSH_SUBJECT",
        }
        add("worker_only_dedicated_settings", not (set(worker) - allowed))
        enabled = worker.get("WE2DAY_REMINDER_WORKER_ENABLED", "false").lower()
        add("worker_enabled_value", enabled in {"true", "false", "1", "0"})
        add("worker_and_api_activation_match", (enabled in {"true", "1"}) == automatic_on)
        add(
            "worker_reuses_server_push_configuration",
            push_enabled in {"true", "1"}
            and worker.get("WE2DAY_PUSH_ENABLED", "false").lower() in {"true", "1"}
            and bool(api.get("WE2DAY_PUSH_PRIVATE_KEY"))
            and all(
                worker.get(k) == api.get(k)
                for k in ("WE2DAY_PUSH_PRIVATE_KEY", "WE2DAY_PUSH_SUBJECT")
            ),
        )
        try:
            options = connection_options(worker.get("WE2DAY_REMINDER_DATABASE_URL", ""))
            project = urlsplit(api_project or "").hostname
            matches = project == options["user"].split(".", 1)[1] + ".supabase.co"
            add(
                "worker_dedicated_project_and_verified_ca",
                matches and options["sslrootcert"] == "/run/we2day/supabase-ca.crt",
            )
        except Exception:
            # libpq parsing errors can include the entire input DSN.
            add("worker_dedicated_project_and_verified_ca", False)
    checks.append(
        {"check": "cloud_schema_oauth_storage_limits_device_delivery", "status": "NOT_CHECKED"}
    )
    return checks


def main():
    parser = argparse.ArgumentParser(
        description="Offline .env checks; values and URLs never printed"
    )
    parser.add_argument("--web-env", type=Path, default=Path("apps/web/.env"))
    parser.add_argument("--api-env", type=Path, default=Path("apps/api/.env"))
    parser.add_argument(
        "--worker-env", type=Path, help="Review the separate private worker file; no network"
    )
    parser.add_argument("--production", action="store_true")
    deployment = parser.add_mutually_exclusive_group()
    deployment.add_argument(
        "--vm-env", type=Path, help="Apply image-only VM Compose origin overrides in memory"
    )
    deployment.add_argument(
        "--compose",
        action="store_true",
        help="Account for this repository's local Compose overrides",
    )
    args = parser.parse_args()
    try:
        web, api = read_environment(args.web_env), read_environment(args.api_env)
        worker = read_environment(args.worker_env) if args.worker_env else None
        if args.vm_env:
            vm = read_environment(args.vm_env)
            web["WE2DAY_SITE_URL"] = vm.get("WE2DAY_SITE_ORIGIN", "")
            web["WE2DAY_API_URL"] = "http://api:8000"
            api["WE2DAY_CORS_ORIGINS"] = vm.get("WE2DAY_ALLOWED_ORIGINS", "")
        checks = review(web, api, args.production, args.compose, worker)
    except (OSError, UnicodeError, ValueError):
        print("FAIL: environment_file_read_or_format; no values printed; no changes")
        return 1
    for check in checks:
        print(f"{check['status']}: {check['check']}")
    print("Offline checks only; no network or changes; deployment readiness not verified")
    return int(any(c["status"] == "FAIL" for c in checks))


if __name__ == "__main__":
    raise SystemExit(main())
