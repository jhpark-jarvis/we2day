"""Scripted model outputs for executor contracts, not evidence of language accuracy."""

import json
import re

import httpx


def scripted_action(request):
    data = json.loads(json.loads(request.content)["messages"][-1]["content"])
    text = data["request"]
    if text in {"다시", "찾았어!?", "찾았어?"}:
        text = data.get("previous_request", "")
    samples = [
        ("국물 요리", "restaurant", "국물 요리"),
        ("라멘", "restaurant", "라멘"),
        ("샌드위치 파는 카페", "cafe", "샌드위치 파는 카페"),
        ("샌드위치", "restaurant", "샌드위치"),
        ("조용한 카페", "cafe", "조용한 카페"),
        ("피자집", "restaurant", "피자집"),
        ("주차장", "any", "주차장"),
    ]
    if text == "주차장 말고 카페 찾아줘":
        text = "카페 찾아줘"
        samples = [("카페", "cafe", "카페")] + samples
    target = next(
        ({"kind": kind, "query": query} for phrase, kind, query in samples if phrase in text), None
    )
    prior = data.get("previous_search") or {}
    if not target and prior.get("awaiting_anchor"):
        target = {"kind": "any", "query": prior["targets"][0]}
    assert target is not None, "Declare a scripted semantic action for " + text
    activities = data.get("activities", [])
    anchor = None
    needed = False
    spatial = bool(re.search(r"주변|근처|이후 일정|번", text)) or prior.get(
        "awaiting_anchor", False
    )
    if spatial and target["kind"] == "any":
        number = re.search(r"([1-8])\s*번", text)
        found = [
            a["number"] - 1
            for a in activities
            if ("식사" in text or "식당" in text)
            and a["title"] in {"식사", "식당"}
            or a["place_name"] == text
            or a["title"] == text
        ]
        anchor = (
            int(number[1]) - 1
            if number
            else found[0]
            if len(found) == 1
            else 0
            if len(activities) == 1
            else None
        )
        needed = anchor is None
    return {
        "operation": "clarify" if needed else "search",
        "area": data.get("area", "중랑구"),
        "targets": [target["query"]],
        "anchor_index": anchor,
        "anchor_needed": needed,
    }


def semantic_response(request, action=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            action or scripted_action(request), ensure_ascii=False
                        )
                    }
                }
            ]
        },
    )
