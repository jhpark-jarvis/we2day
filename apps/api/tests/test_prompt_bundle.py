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
    for name in ("system", "finish", "repair", "interpret", "relevance", "route", "retrieval"):
        (directory / f"{name}.txt").write_bytes(
            root.joinpath(PROMPT.version, f"{name}.txt").read_bytes()
        )
    return tmp_path


def test_immutable_release_and_cross_platform_digest(resource_copy):
    assert PROMPT.version == "we2-ai-2026-11-09-v27"
    assert PROMPT.sha256 == "1046805f03b127a1734068bd9c8835aca8c0d753814963e90f8718c3af6a80c8"
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
