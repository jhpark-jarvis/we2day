import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ai_monitor", Path(__file__).parents[1] / "deployment/operations/monitor.py"
)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def test_existing_monitor_streams_only_aggregates_and_cleans_up_owned_processes(monkeypatch):
    original, commands, processes = subprocess.Popen, [], []
    record = {
        "version": "we2-ai-2026-10-27-v8",
        "status": "ok",
        "total_ms": 100,
        "model_calls": 0,
        "address": "private",
        "prompt": "secret",
    }

    def launch(args, **kwargs):
        commands.append(args)
        command = (
            [sys.executable, "-c", f"print('ai_run '+{json.dumps(record)!r})"]
            if args[1] == "logs"
            else [sys.executable, "-m", "we2day_api.ai_metrics"]
        )
        process = original(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(monitor.subprocess, "Popen", launch)
    result = monitor.ai_usage()
    assert result["status"] == "ok" and result["accepted"] == 1
    assert "secret" not in json.dumps(result) and "private" not in json.dumps(result)
    assert commands[0][1:6] == ["logs", "--since", "24h", "--tail", "10000"]
    assert all(p.poll() is not None for p in processes)


def test_optional_metrics_timeout_does_not_hide_health_and_leaves_no_children(monkeypatch):
    original, processes = subprocess.Popen, []

    def launch(args, **kwargs):
        process = original([sys.executable, "-c", "import time;time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(monitor.subprocess, "Popen", launch)
    start = time.monotonic()
    assert monitor.ai_usage(timeout=0.05) == {"status": "unavailable"}
    assert time.monotonic() - start < 5
    assert all(p.poll() is not None for p in processes)
