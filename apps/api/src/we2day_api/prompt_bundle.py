"""Immutable, versioned package resources, validated once before serving requests."""

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable


@dataclass(frozen=True)
class PromptBundle:
    version: str
    sha256: str
    system: str
    finish: str
    repair: str


def read_bundle(root: Traversable) -> PromptBundle:
    """Reject incomplete/corrupt releases; never accept a request-supplied path."""
    raw = root.joinpath("manifest.json").read_bytes()
    if len(raw) > 1024:
        raise ValueError("Prompt manifest exceeds limit")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) != {"version", "sha256"}:
        raise ValueError("Invalid prompt manifest")
    version, expected = manifest["version"], manifest["sha256"]
    if not isinstance(version, str) or not re.fullmatch(r"we2-ai-\d{4}-\d{2}-\d{2}-v\d+", version):
        raise ValueError("Invalid prompt version")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid prompt digest")
    sections = {}
    for name in ("system", "finish", "repair"):
        content = root.joinpath(version, f"{name}.txt").read_bytes()
        if not content or len(content) > 16384:
            raise ValueError("Invalid prompt section size")
        # Git CRLF checkout must produce the same instructions/digest as Linux packaging.
        sections[name] = content.decode("utf-8").replace("\r\n", "\n")
    canonical = json.dumps(sections, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != expected:
        raise ValueError("Prompt digest mismatch")
    return PromptBundle(version=version, sha256=actual, **sections)


PROMPT = read_bundle(files("we2day_api").joinpath("prompts"))
