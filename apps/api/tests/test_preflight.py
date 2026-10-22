import subprocess
import sys
from copy import deepcopy

import pytest

from we2day_api.preflight import read_environment, review


def config():
    web = {
        "WE2DAY_SITE_URL": "https://we2day.example",
        "WE2DAY_SUPABASE_URL": "https://fixture.supabase.co",
        "WE2DAY_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_SYNTHETIC_ONLY",
        "WE2DAY_AUTH_PROVIDERS": "password,google,kakao",
        "WE2DAY_API_URL": "http://api:8000",
    }
    api = {
        "WE2DAY_SUPABASE_URL": web["WE2DAY_SUPABASE_URL"],
        "WE2DAY_SUPABASE_PUBLISHABLE_KEY": web["WE2DAY_SUPABASE_PUBLISHABLE_KEY"],
        "WE2DAY_CORS_ORIGINS": '["https://we2day.example"]',
    }
    return web, api


def test_preflight_detects_origin_credentials_and_compose_override_without_exposure(tmp_path):
    web, api = config()
    assert not any(c["status"] == "FAIL" for c in review(web, api, True))
    for target, changes in [
        ("web", {"WE2DAY_SITE_URL": "http://we2day.example"}),
        ("web", {"WE2DAY_AUTH_PROVIDERS": "password,unknown"}),
        ("web", {"WE2DAY_SUPABASE_PUBLISHABLE_KEY": "synthetic-invalid-publishable-key"}),
        ("api", {"WE2DAY_SUPABASE_URL": "https://wrong.supabase.co"}),
        ("web", {"WE2DAY_PUSH_PRIVATE_KEY": "synthetic-not-a-real-key"}),
        ("api", {"WE2DAY_PUSH_ENABLED": "true"}),
        ("api", {"WE2DAY_CORS_ORIGINS": '["*"]'}),
    ]:
        w, a = deepcopy(web), deepcopy(api)
        (w if target == "web" else a).update(changes)
        assert any(c["status"] == "FAIL" for c in review(w, a, True))
    assert any(
        c["check"] == "local_compose_requires_production_override" and c["status"] == "FAIL"
        for c in review(web, api, True, True)
    )
    paths = []
    for name, env in [("web", web), ("api", api)]:
        path = tmp_path / f"{name}.env"
        path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
        paths.append(path)
        assert read_environment(path) == env
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "we2day_api.preflight",
            "--web-env",
            str(paths[0]),
            "--api-env",
            str(paths[1]),
            "--production",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert all(v not in result.stdout + result.stderr for v in web.values())
    paths[0].write_text("WE2DAY_SITE_URL=x\nWE2DAY_SITE_URL=secret", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "we2day_api.preflight",
            "--web-env",
            str(paths[0]),
            "--api-env",
            str(paths[1]),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and "secret" not in result.stdout + result.stderr


def reminder_config():
    web, api = config()
    web["WE2DAY_SUPABASE_URL"] = api["WE2DAY_SUPABASE_URL"] = (
        "https://abcdefghijklmnopqrst.supabase.co"
    )
    api.update(
        WE2DAY_PUSH_ENABLED="true",
        WE2DAY_PUSH_AUTOMATIC_ENABLED="true",
        WE2DAY_PUSH_PRIVATE_KEY="a" * 43,
        WE2DAY_PUSH_SUBJECT="mailto:operator@example.com",
    )
    worker = {
        k: v
        for k, v in api.items()
        if k in {"WE2DAY_PUSH_ENABLED", "WE2DAY_PUSH_PRIVATE_KEY", "WE2DAY_PUSH_SUBJECT"}
    }
    worker.update(
        WE2DAY_REMINDER_WORKER_ENABLED="true",
        WE2DAY_REMINDER_DATABASE_URL=(
            "postgresql://we2day_reminder_worker.abcdefghijklmnopqrst:synthetic-password"
            "@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
            "?sslmode=verify-full&sslrootcert=/run/we2day/supabase-ca.crt"
        ),
    )
    return web, api, worker


@pytest.mark.parametrize(
    "case",
    [
        "mixed_web",
        "mixed_api",
        "missing",
        "admin",
        "project",
        "tls",
        "ca",
        "extra",
        "key",
        "subject",
        "flag",
        "invalid_flag",
        "parser",
    ],
)
def test_worker_preflight_rejects_mixed_access_and_broken_configuration(case):
    web, api, worker = reminder_config()
    assert not any(c["status"] == "FAIL" for c in review(web, api, True, worker=worker))
    if case in {"mixed_web", "mixed_api"}:
        target = web if case == "mixed_web" else api
        target["WE2DAY_REMINDER_DATABASE_URL"] = worker["WE2DAY_REMINDER_DATABASE_URL"]
    elif case == "missing":
        worker = None
    elif case in {"key", "subject", "extra", "invalid_flag", "flag"}:
        key, value = {
            "key": ("WE2DAY_PUSH_PRIVATE_KEY", "b" * 43),
            "subject": ("WE2DAY_PUSH_SUBJECT", "mailto:other@example.com"),
            "extra": ("WE2DAY_SUPABASE_SECRET_KEY", "synthetic-admin-secret"),
            "flag": ("WE2DAY_REMINDER_WORKER_ENABLED", "false"),
            "invalid_flag": ("WE2DAY_REMINDER_WORKER_ENABLED", "maybe"),
        }[case]
        worker[key] = value
    else:
        old, new = {
            "admin": ("we2day_reminder_worker", "postgres"),
            "project": ("abcdefghijklmnopqrst", "z" * 20),
            "tls": ("verify-full", "require"),
            "ca": ("/run/we2day/supabase-ca.crt", "system"),
            "parser": (worker["WE2DAY_REMINDER_DATABASE_URL"], "invalid secret DSN"),
        }[case]
        worker["WE2DAY_REMINDER_DATABASE_URL"] = worker["WE2DAY_REMINDER_DATABASE_URL"].replace(
            old, new
        )
    assert any(c["status"] == "FAIL" for c in review(web, api, True, worker=worker))


def test_worker_cli_never_exposes_private_file_or_driver_input(tmp_path):
    web, api, worker = reminder_config()
    command = [sys.executable, "-m", "we2day_api.preflight", "--production"]
    for name, env in [("web", web), ("api", api), ("worker", worker)]:
        path = tmp_path / f"{name}.env"
        path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
        command += [f"--{name}-env", str(path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert all(v not in result.stdout + result.stderr for v in worker.values() if len(v) > 10)
    (tmp_path / "worker.env").write_text(
        "WE2DAY_REMINDER_DATABASE_URL=broken-secret-dsn", encoding="utf-8"
    )
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert "broken-secret-dsn" not in result.stdout + result.stderr


def test_vm_compose_overrides_are_reviewed_without_file_changes(tmp_path):
    web, api, worker = reminder_config()
    # VM Compose overrides these raw local defaults, without rewriting the source files.
    web["WE2DAY_SITE_URL"] = "http://127.0.0.1:3000"
    api["WE2DAY_CORS_ORIGINS"] = '["http://127.0.0.1:3000"]'
    vm = {
        "WE2DAY_SITE_ORIGIN": "https://we2day.example",
        "WE2DAY_ALLOWED_ORIGINS": '["https://we2day.example"]',
    }
    command = [sys.executable, "-m", "we2day_api.preflight", "--production"]
    before = {}
    for name, env in [("web", web), ("api", api), ("worker", worker), ("vm", vm)]:
        path = tmp_path / f"{name}.env"
        path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
        before[path] = path.read_bytes()
        command += [f"--{name}-env", str(path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert all(path.read_bytes() == content for path, content in before.items())
    (tmp_path / "vm.env").write_text(
        'WE2DAY_SITE_ORIGIN=http://bad.example\nWE2DAY_ALLOWED_ORIGINS=["*"]'
    )
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert "bad.example" not in result.stdout + result.stderr
