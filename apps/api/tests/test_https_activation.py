"""Exercise activation failures without network, certificates or host services."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deployment" / "activate-https.sh"


def run_activation_case(tmp_path, failure):
    bash = shutil.which("bash")
    deployment, configuration, commands = (tmp_path / n for n in ("app", "proxy", "bin"))
    for directory in (deployment, configuration, commands):
        directory.mkdir()
    before = (
        "WE2DAY_SITE_ORIGIN=http://127.0.0.1:3200\n"
        'WE2DAY_ALLOWED_ORIGINS=["http://127.0.0.1:3200"]\n'
        "WE2DAY_API_IMAGE=sha256:unchanged\n"
    )
    (deployment / ".env").write_text(before)
    (deployment / ".env").chmod(0o600)
    (deployment / "compose.yaml").write_text("reviewed compose fixture")
    (configuration / "nginx.conf").write_text("bootstrap")
    (configuration / "nginx.https.pending.conf").write_text("https")
    program = """#!/bin/sh
set -eu
name=${0##*/}
printf '%s %s\\n' "$name" "$*" >> "$EVENTS"
if [ "$name" = certbot ] && [ "$FAILURE" = certbot ]; then exit 1; fi
if [ "$name" = docker ] && [ "$FAILURE" = docker ] && [ ! -f "$ONCE" ]; then
    touch "$ONCE"; exit 1
fi
if [ "$name" = systemctl ] && [ "${1:-}" = reload ]; then
    if [ "$FAILURE" = reload ] && [ ! -f "$ONCE" ]; then touch "$ONCE"; exit 1; fi
fi
if [ "$name" = curl ] && [ "$FAILURE" = tls ]; then exit 60; fi
if [ "$name" = curl ] && echo "$*" | grep -q write-out; then printf 401; fi
"""
    for name in ("certbot", "openssl", "nginx", "docker", "systemctl", "curl"):
        path = commands / name
        path.write_text(program)
        path.chmod(0o755)
    result = subprocess.run(
        [bash, str(SCRIPT), "we2day.example", str(deployment), str(configuration)],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "FAILURE": failure,
            "EVENTS": str(tmp_path / "events"),
            "ONCE": str(tmp_path / "once"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    events = (tmp_path / "events").read_text()
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert "WE2DAY_SITE_ORIGIN=https://we2day.example" in (deployment / ".env").read_text()
        assert (configuration / "nginx.conf").read_text() == "https"
        assert "systemctl enable --now certbot.timer" in events
    else:
        assert result.returncode != 0
        assert (deployment / ".env").read_text() == before
        assert (configuration / "nginx.conf").read_text() == "bootstrap"
        assert "systemctl enable" not in events
        if failure == "certbot":
            assert "docker" not in events and not (configuration / "pre-https").exists()
        else:
            assert "restored" in result.stderr
    assert not list(deployment.glob(".env.https.*"))
    assert (deployment / ".env").stat().st_mode & 0o777 == 0o600


class HttpsActivationTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "Linux host required")
    def test_activation_success_and_failures(self):
        for failure in ("certbot", "docker", "reload", "tls", "none"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                run_activation_case(Path(directory), failure)


if __name__ == "__main__":
    unittest.main()
