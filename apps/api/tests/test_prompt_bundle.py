import json
from dataclasses import FrozenInstanceError
from importlib.resources import files

import pytest

from we2day_api.prompt_bundle import PROMPT, read_bundle


@pytest.fixture
def resource_copy(tmp_path):
    root = files("we2day_api").joinpath("prompts")
    (tmp_path / "manifest.json").write_bytes(root.joinpath("manifest.json").read_bytes())
    directory = tmp_path / PROMPT.version
    directory.mkdir()
    for name in (
        "system",
        "finish",
        "repair",
        "interpret",
        "relevance",
        "route",
        "retrieval",
        "turn",
        "turn_route",
        "turn_operations",
    ):
        (directory / f"{name}.txt").write_bytes(
            root.joinpath(PROMPT.version, f"{name}.txt").read_bytes()
        )
    return tmp_path


def test_immutable_release_and_cross_platform_digest(resource_copy):
    assert PROMPT.version == "we2-ai-2026-11-12-v44"
    assert PROMPT.sha256 == "a3daae9269618f78e8bca1e5b1dd435e94b4c1a95926e52fcc40a3b9367ab3d6"
    assert PROMPT.interpret
    for path in (resource_copy / PROMPT.version).iterdir():
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert read_bundle(resource_copy) == PROMPT
    with pytest.raises(FrozenInstanceError):
        PROMPT.system = "replacement"


@pytest.mark.parametrize("failure", ["tamper", "missing", "oversize", "traversal", "manifest"])
def test_invalid_release_fails_closed(resource_copy, failure):
    section = resource_copy / PROMPT.version / "system.txt"
    manifest_path = resource_copy / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if failure == "tamper":
        section.write_text("changed", encoding="utf-8")
    elif failure == "missing":
        section.unlink()
    elif failure == "oversize":
        section.write_text("x" * 16385)
    elif failure == "traversal":
        manifest["version"] = "../other"
        manifest_path.write_text(json.dumps(manifest))
    else:
        manifest_path.write_text("[]")
    with pytest.raises((ValueError, FileNotFoundError)):
        read_bundle(resource_copy)


def test_each_operation_prompt_is_present_and_isolated():
    operations = json.loads(PROMPT.turn_operations)
    assert set(operations) == {
        "date",
        "status",
        "help",
        "chat",
        "read",
        "search",
        "plan",
        "edit",
        "resume",
        "clarify",
        "cancel",
    }
    for kind, value in operations.items():
        assert ("Fixed operation " + kind) in value
