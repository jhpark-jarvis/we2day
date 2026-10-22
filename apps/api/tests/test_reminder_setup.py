import base64
import hashlib
import hmac
from urllib.parse import parse_qs, urlsplit

import pytest
from test_push import keys

from we2day_api.reminder_setup import prepare


def test_offline_setup_reuses_push_only_and_never_overwrites(tmp_path):
    raw, _ = keys()
    source = tmp_path / "api.env"
    source.write_text(
        "WE2DAY_PUSH_ENABLED=true\nWE2DAY_PUSH_PRIVATE_KEY="
        + raw
        + "\nWE2DAY_PUSH_SUBJECT=https://example.com\nADMIN_SECRET=must-not-copy\n"
    )
    output = tmp_path / "worker-private"
    host, project = "aws-0-ap-northeast-1.pooler.supabase.com", "abcdefghijklmnopqrst"
    prepare(source, output, host, project)
    env = dict(line.split("=", 1) for line in (output / "worker.env").read_text().splitlines())
    assert env["WE2DAY_REMINDER_WORKER_ENABLED"] == "false"
    assert env["WE2DAY_PUSH_PRIVATE_KEY"] == raw and "ADMIN_SECRET" not in env
    password = urlsplit(env["WE2DAY_REMINDER_DATABASE_URL"]).password
    assert parse_qs(urlsplit(env["WE2DAY_REMINDER_DATABASE_URL"]).query) == {
        "sslmode": ["verify-full"],
        "sslrootcert": ["/run/we2day/supabase-ca.crt"],
    }
    sql = (output / "worker-login.sql").read_text()
    assert password not in sql and "SCRAM-SHA-256$4096:" in sql
    verifier = sql.split("password '")[1].split("'")[0]
    _, salt_part, key_part = verifier.split("$")
    iterations, salt64 = salt_part.split(":")
    stored64, server64 = key_part.split(":")
    salted = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt64), int(iterations)
    )
    assert (
        base64.b64decode(stored64)
        == hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    )
    assert base64.b64decode(server64) == hmac.digest(salted, b"Server Key", "sha256")
    original = (output / "worker.env").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(source, output, host, project)
    assert (output / "worker.env").read_bytes() == original
    for bad_host in ["localhost", "aws-0-ap-northeast-1.pooler.supabase.com.evil.test"]:
        with pytest.raises(ValueError):
            prepare(source, tmp_path / "bad", bad_host, project)
    assert not (tmp_path / "bad").exists()
    assert source.read_text().endswith("ADMIN_SECRET=must-not-copy\n")


def test_invalid_push_setup_has_no_output(tmp_path):
    source = tmp_path / "api.env"
    source.write_text("WE2DAY_PUSH_ENABLED=false\n")
    with pytest.raises(ValueError):
        prepare(source, tmp_path / "new", "aws-0-ap-northeast-1.pooler.supabase.com", "a" * 20)
    assert not (tmp_path / "new").exists()
