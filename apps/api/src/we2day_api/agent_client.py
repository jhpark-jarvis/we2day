"""Provider-independent agent API client. No model calls or key provisioning."""

import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from we2day_api.agents import DraftInput
from we2day_api.backup_bundle import json_value
from we2day_api.plans import PlanContent

MAX_RESPONSE = 2 * 1024**2


def read_json(path, limit=40000):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("input_file")
    return json_value(path.read_bytes())


def write_json(path, value):
    # Windows callers must select an operator-owned directory with a private ACL.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")


def prepare_draft(content_file, output):
    content = PlanContent.model_validate(read_json(content_file))
    request = DraftInput(id=uuid4(), request_id=uuid4(), content=content)
    write_json(output, request.model_dump(mode="json"))


def calendar_path(start, end, offset=0):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if (
        first.year < 2000
        or last.year > 2100
        or not 0 <= (last - first).days <= 30
        or type(offset) is not int
        or not 0 <= offset <= 100000
    ):
        raise ValueError("calendar_range")
    return f"/calendar?start={first.isoformat()}&end={last.isoformat()}&offset={offset}"


class AgentClient:
    def __init__(self, base, key, *, allow_local=False, transport=None):
        import re

        parsed = urlsplit(base)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or parsed.path.rstrip("/") != "/api/agent/v1"
            or not re.fullmatch(r"w2d_agent_[0-9a-f]{64}", key)
            or not (
                parsed.scheme == "https"
                or (
                    allow_local
                    and parsed.scheme == "http"
                    and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
        ):
            raise ValueError("connection_configuration")
        self.base, self.key, self.transport = base.rstrip("/"), key, transport

    def request(self, action, *, start=None, end=None, offset=0, plan_id=None, draft=None):
        body = None
        if action in {"check", "calendar"}:
            path, method = calendar_path(start, end, offset), "GET"
        elif action == "plan":
            path, method = f"/plans/{UUID(plan_id)}", "GET"
        elif action == "draft":
            body = DraftInput.model_validate(draft).model_dump(mode="json")
            if (
                len(json.dumps(body, ensure_ascii=False).encode()) > 40000
                or len(json.dumps(body["content"], ensure_ascii=False).encode()) > 32768
            ):
                raise ValueError("draft_size")
            path, method = "/drafts", "POST"
        else:
            raise ValueError("unsupported_action")
        with httpx.Client(
            timeout=25, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            with client.stream(
                method,
                self.base + path,
                headers={"Authorization": "Bearer " + self.key},
                json=body,
            ) as response:
                if not 200 <= response.status_code < 300:
                    # Never echo server error text, request URL, headers or key.
                    raise ValueError(f"agent_http_{response.status_code}")
                data = bytearray()
                for chunk in response.iter_bytes(65536):
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise ValueError("response_limit")
        value = json_value(bytes(data))
        if not isinstance(value, dict) or self.key in json.dumps(value):
            raise ValueError("invalid_response")
        if action == "check":
            return {
                "connected": True,
                "appointments": len(value.get("appointments", [])),
                "plans": len(value.get("plans", [])),
                "more": value.get("next_offset") is not None,
            }
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare-draft", "check", "calendar", "plan", "draft"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--plan-id")
    parser.add_argument("--allow-local", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare-draft":
            if not args.input or not args.output:
                raise ValueError("input_output_required")
            prepare_draft(args.input, args.output)
        else:
            if args.action != "check" and (not args.output or args.output.exists()):
                raise ValueError("new_output_required")
            client = AgentClient(
                os.environ.get("WE2DAY_AGENT_URL", ""),
                os.environ.get("WE2DAY_AGENT_KEY", ""),
                allow_local=args.allow_local,
            )
            value = client.request(
                args.action,
                start=args.start,
                end=args.end,
                offset=args.offset,
                plan_id=args.plan_id,
                draft=read_json(args.input) if args.action == "draft" and args.input else None,
            )
            if args.action == "check":
                print(json.dumps(value))
            else:
                write_json(args.output, value)
        print("PASS: agent client; credentials and record contents suppressed")
        return 0
    except Exception:
        print("FAIL: agent configuration, input, connection or response; values suppressed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
