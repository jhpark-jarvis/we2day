"""Opt-in Korean task evaluation: real planner/model, controlled read tools, no business DB.

The caller provides server settings in memory. Never serialize credentials or user records.
This evaluator is not imported by the application and makes no model calls on import.
"""

import asyncio
import copy
import hashlib
import json
import time
from uuid import uuid4

from fastapi import HTTPException

from we2day_api import ai_planner
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.places import SearchResults
from we2day_api.plans import PlanContent

LIBRARY = [
    {
        "title": "샘플도서관A",
        "category": "교육>군구립도서관",
        "roadAddress": "서울특별시 중랑구 신내로 1",
    },
    {
        "title": "샘플도서관B",
        "category": "교육>도서관",
        "roadAddress": "서울특별시 중랑구 동일로 2",
    },
    {
        "title": "샘플도서관카페",
        "category": "음식점>카페",
        "roadAddress": "서울특별시 중랑구 망우로 9",
    },
]
CAFE = [
    {"title": "샘플카페A", "category": "카페,디저트", "roadAddress": "서울특별시 중랑구 망우로 3"},
    {"title": "샘플카페B", "category": "카페,디저트", "roadAddress": "서울특별시 중랑구 동일로 4"},
    {
        "title": "샘플카페C",
        "category": "카페,디저트",
        "roadAddress": "서울특별시 성동구 성수동 연무장길 5",
    },
]
PARK = [
    {
        "title": "서울숲",
        "category": "자연,공원>도시공원",
        "roadAddress": "서울특별시 성동구 뚝섬로 273",
    },
    {"title": "서울숲카페", "category": "카페,디저트", "roadAddress": "서울특별시 성동구 성수동 9"},
]


class MemoryStore:
    def __init__(self, case):
        self.case = case
        self.context = copy.deepcopy(case["initial"].get("context", {}))
        self.proposal = copy.deepcopy(case["initial"].get("proposal"))
        self.events = []
        self.version = 0

    async def rpc(self, name, values=None):
        if name == "begin_ai_planner_turn":
            return {"context": self.context, "proposal": self.proposal}
        if name == "reserve_ai_planner_request":
            # Isolated evaluator state. The live driver spaces requests and stops on quota errors.
            return True
        if name == "finish_ai_planner_turn":
            result = values["p_result"]
            self.context = copy.deepcopy(result["context"])
            self.proposal = result.get("plan") or self.proposal
            self.version += 1
            return {"result": result, "version": self.version}
        if name == "release_ai_planner_turn":
            return True
        raise AssertionError("Unexpected database operation")

    async def call(self, *args, **kwargs):
        raise AssertionError("Evaluation cannot read business tables")


class ControlledTools:
    def __init__(self, settings, client, store, budget, stats):
        self.store = store

    async def perform(self, action):
        self.store.events.append(action[0])
        if action[0] != "places":
            raise HTTPException(503, "evaluation_tool_unavailable")
        mode = self.store.case.get("provider", "normal")
        if mode == "failed":
            raise HTTPException(503, "evaluation_tool_unavailable")
        query = action[1]
        rows = PARK if "서울숲" in query else LIBRARY if "도서관" in query else CAFE
        return SearchResults.model_validate({"items": [] if mode == "empty" else rows})


def normalized(value):
    return "".join(value.split())


def set_path(value, path, content):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, list):
        value[int(parts[-1])] = content
    else:
        value[parts[-1]] = content


def grade(case, step, result, events, before):
    expected = step["expect"]
    failures = []

    def require(ok, reason):
        if not ok:
            failures.append(reason)

    plan = result.get("plan")
    if "plan" in expected:
        require(bool(plan) == (expected["plan"] == "required"), "plan_presence")
    if expected.get("no_search"):
        require("places" not in events, "unexpected_search")
    if expected.get("needs_search"):
        require("places" in events, "missing_search")
    for key, value in expected.get("slots", {}).items():
        require(result.get("context", {}).get(key) == value, f"slot:{key}")
    for key, value in expected.get("scope", {}).items():
        require(result.get("context", {}).get("search_scope", {}).get(key) == value, f"scope:{key}")
    reply = normalized(result.get("reply", ""))
    if "reply_any" in expected:
        require(any(normalized(word) in reply for word in expected["reply_any"]), "clarification")
    for word in expected.get("reply_not", []):
        require(normalized(word) not in reply, "misleading_reply")
    candidates = result.get("candidates", [])
    for name in expected.get("candidate_not", []):
        require(all(p["title"] != name for p in candidates), "rejected_or_outside_candidate")
    if "candidate_min" in expected:
        require(len(candidates) >= expected["candidate_min"], "missing_candidates")
    if "candidate_max" in expected:
        require(len(candidates) <= expected["candidate_max"], "unexpected_candidates")
    if "patch" in expected:
        target = PlanContent.model_validate(before).model_dump()
        for path, value in expected["patch"].items():
            set_path(target, path, value)
        require(plan == target, "unintended_edit_or_missing_patch")
    if expected.get("preserve_prefix"):
        target = PlanContent.model_validate(before).model_dump()
        require(
            bool(plan) and plan["activities"][: len(target["activities"])] == target["activities"],
            "rewritten_existing_activity",
        )
        require(
            bool(plan)
            and all(
                plan[k] == target[k]
                for k in ("title", "date", "budget", "transport", "preparation")
            ),
            "rewritten_plan_metadata",
        )
    if "retain_only" in expected:
        target = PlanContent.model_validate(before).model_dump()
        target["activities"] = [target["activities"][i] for i in expected["retain_only"]]
        require(plan == target, "unintended_remove")
    if "activity_max" in expected:
        require(
            bool(plan) and len(plan["activities"]) <= expected["activity_max"], "extra_activity"
        )
    for name in expected.get("plan_places", []):
        require(
            bool(plan) and any(name in p["place"] for p in plan["activities"]),
            "lost_selected_place",
        )
    if expected.get("unknown_cost_time"):
        require(
            bool(plan)
            and all(a.get("time") is None and a.get("cost") is None for a in plan["activities"]),
            "invented_time_or_cost",
        )
    if "plan_budget" in expected:
        require(bool(plan) and plan.get("budget") == expected["plan_budget"], "invented_budget")
    if "initial_order" in expected:
        from we2day_api.ai_place_policy import kinds

        require(
            bool(plan)
            and len(plan["activities"]) == len(expected["initial_order"])
            and all(
                k in kinds(a["place"])
                for k, a in zip(expected["initial_order"], plan["activities"], strict=True)
            ),
            "initial_activity_order",
        )
    for name, value in expected.get("window", {}).items():
        require(
            result.get("context", {}).get("intake", {}).get("data", {}).get(name) == value,
            "window:" + name,
        )
    return failures


async def evaluate(settings, corpus, *, client, minimum_interval=0, progress=None):
    """No retries; provider quota/capacity/auth failures halt the batch."""
    original_tools = ai_planner.ToolIO
    ai_planner.ToolIO = ControlledTools
    canonical = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report = {
        "corpus_version": corpus["version"],
        "corpus_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "prompt_version": ai_planner.PROMPT_VERSION,
        "prompt_sha256": ai_planner.PROMPT_SHA256,
        "model": ai_planner.MODEL,
        "cases": [],
        "halted": False,
    }
    last_start, last_model_start, total_calls = 0, 0, 0
    batch_deadline = time.monotonic() + 900
    try:
        for case in corpus["cases"]:
            store, observations = MemoryStore(case), []
            chosen = case.get("chosen", [])
            cid = uuid4()
            for step in case["steps"]:
                await asyncio.sleep(
                    max(0, minimum_interval - (time.monotonic() - last_model_start))
                )
                last_start = time.monotonic()
                before = copy.deepcopy(store.proposal)
                store.events = []
                chosen = step.get("chosen", chosen)
                body = ai_planner.ChatInput.model_validate(
                    {
                        "messages": step.get("history", [])
                        + [{"role": "user", "content": step["text"]}],
                        "conversation_id": str(cid),
                        "request_id": str(uuid4()),
                        "version": store.version,
                        "chosen_places": chosen,
                        **({"brief": step["brief"]} if "brief" in step else {}),
                    }
                )
                stats = RunStats(ai_planner.PROMPT_VERSION)
                try:
                    remaining = batch_deadline - time.monotonic()
                    if remaining <= 0:
                        report["halted"] = True
                        break
                    result = await ai_planner._chat(
                        body, settings, store, client, Budget(min(85, remaining)), stats
                    )
                    value = result.model_dump(mode="json")
                    failures = grade(case, step, value, store.events, before)
                    observations.append(
                        {
                            "failures": failures,
                            "result": value,
                            "events": store.events,
                            "counts": stats.counts,
                            "ms": round((time.monotonic() - last_start) * 1000, 1),
                        }
                    )
                except HTTPException as error:
                    observations.append(
                        {"failures": [f"http:{error.detail}"], "counts": stats.counts}
                    )
                    if error.status_code in {429, 503}:
                        report["halted"] = True
                total_calls += stats.counts.get("model_calls", 0)
                if stats.counts.get("model_calls", 0):
                    last_model_start = last_start
                if total_calls > 150:
                    report["halted"] = True
                if report["halted"]:
                    break
            report["cases"].append(
                {
                    "id": case["id"],
                    "split": case["split"],
                    "category": case["category"],
                    "turns": observations,
                    "passed": all(not r["failures"] for r in observations),
                }
            )
            if progress:
                progress(case["id"], report["cases"][-1]["passed"])
            if report["halted"]:
                break
    finally:
        ai_planner.ToolIO = original_tools
    return report
