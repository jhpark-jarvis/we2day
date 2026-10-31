"""Opt-in ordinary conversations: actual model, fixed provider catalog, memory-only state."""

import asyncio
import copy
import hashlib
import json
import time
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from dialogue_evaluation import MemoryStore, grade
from fastapi import HTTPException

from we2day_api import ai_planner
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.ai_search_followups import pending_promise
from we2day_api.places import SearchResults

CATALOG = {
    area: [
        {"title": f"예시{area}{name}", "category": category, "roadAddress": address}
        for name, category in [
            ("도서관", "교육>도서관"),
            ("카페", "음식점>카페"),
            ("식당", "음식점>한식"),
            ("전시관", "문화>박물관,미술관,전시"),
        ]
    ]
    for area, address in [
        ("성수동", "서울특별시 성동구 성수동1가 1"),
        ("연남동", "서울특별시 마포구 연남동 1"),
        ("중랑구", "서울특별시 중랑구 신내동 1"),
    ]
}


class ReadFixture:
    def __init__(self, settings, client, store, budget, stats):
        self.store = store

    async def perform(self, action):
        self.store.events.append(action[0])
        if action[0] != "places":
            raise HTTPException(503, "evaluation_tool_unavailable")
        self.store.queries.append(action[1])
        area = next((a for a in CATALOG if a in action[1]), "중랑구")
        # A stable source catalog, independent of the expected target/answer.
        rows = CATALOG[area] + [
            {"title": "다른지역카페", "category": "카페", "roadAddress": "부산광역시 동구 1"}
        ]
        return SearchResults.model_validate({"items": rows})


def assess(case, step, result, store, before):
    failures = grade(case, step, result, store.events, before)
    expected, context = step["expect"], result.get("context", {})
    if expected.get("keep_proposal") and before != store.proposal:
        failures.append("unexpected_proposal_change")
    if expected.get("pending") and not context.get("dialogue", {}).get("pending"):
        failures.append("missing_clarification_state")
    if expected.get("reverse_activities"):
        plan = result.get("plan")
        if not plan or plan["activities"] != list(reversed(before["activities"])):
            failures.append("wrong_activity_order")
    if pending_promise(result.get("reply", "")):
        failures.append("background_promise")
    if len(store.queries) > 4:
        failures.append("search_budget")
    for query in expected.get("queries_any", []):
        aliases = [query] if isinstance(query, str) else query
        if not any(term in q for term in aliases for q in store.queries):
            failures.append("missing_target:" + str(query))
    if expected.get("relative_date") == "next_saturday":
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        target = today - timedelta(days=today.weekday()) + timedelta(days=12)
        if context.get("date") != target.isoformat():
            failures.append("wrong_relative_date")
    return failures


async def evaluate(settings, corpus, client, progress=None):
    original = ai_planner.ToolIO
    ai_planner.ToolIO = ReadFixture
    report = {
        "corpus": corpus["version"],
        "sha256": hashlib.sha256(
            json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "prompt": ai_planner.PROMPT_VERSION,
        "prompt_sha256": ai_planner.PROMPT_SHA256,
        "cases": [],
        "halted": False,
        "business_db_access": False,
    }
    deadline, model_calls = time.monotonic() + 900, 0
    try:
        for case in corpus["cases"]:
            store, history, observed = MemoryStore(case), [], []
            cid = str(uuid4())
            for step in case["steps"]:
                before = copy.deepcopy(store.proposal)
                store.events, store.queries = [], []
                history.append({"role": "user", "content": step["text"]})
                body = ai_planner.ChatInput.model_validate(
                    {
                        "messages": history[-11:],
                        "conversation_id": cid,
                        "request_id": str(uuid4()),
                        "version": store.version,
                        "chosen_places": step.get("chosen", []),
                        **({"brief": step["brief"]} if "brief" in step else {}),
                    }
                )
                stats, start = RunStats(ai_planner.PROMPT_VERSION), time.monotonic()
                try:
                    result = await ai_planner._chat(
                        body,
                        settings,
                        store,
                        client,
                        Budget(min(85, max(0.1, deadline - start))),
                        stats,
                    )
                    value = result.model_dump(mode="json")
                    failures = assess(case, step, value, store, before)
                    history.append({"role": "assistant", "content": result.reply})
                    observed.append(
                        {
                            "input": step["text"],
                            "failures": failures,
                            "result": value,
                            "queries": store.queries,
                            "events": store.events,
                            "counts": stats.counts,
                            "ms": round((time.monotonic() - start) * 1000, 1),
                        }
                    )
                except HTTPException as error:
                    observed.append(
                        {
                            "input": step["text"],
                            "failures": ["http:" + str(error.detail)],
                            "counts": stats.counts,
                            "queries": store.queries,
                        }
                    )
                    if error.status_code in {401, 403, 429}:
                        report["halted"] = True
                    break
                model_calls += stats.counts["model_calls"]
                if model_calls >= 80 or time.monotonic() >= deadline:
                    report["halted"] = True
                if report["halted"]:
                    break
                if stats.counts["model_calls"]:
                    await asyncio.sleep(0.5)
            item = {
                "id": case["id"],
                "split": case["split"],
                "turns": observed,
                "passed": len(observed) == len(case["steps"])
                and all(not x["failures"] for x in observed),
            }
            report["cases"].append(item)
            if progress:
                progress(item["id"], item["passed"])
            if report["halted"]:
                break
    finally:
        ai_planner.ToolIO = original
    report["model_calls"] = model_calls
    return report
