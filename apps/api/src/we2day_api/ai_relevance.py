"""Bounded public-category suggestions; never proof of a requested menu or facility."""

import json
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from we2day_api.ai_model import model_parameters
from we2day_api.ai_place_policy import kinds, norm, plain, source_kind
from we2day_api.ai_runtime import bounded_response
from we2day_api.prompt_bundle import PROMPT


class RelevanceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int
    evidence: str = Field(max_length=160)
    relation: Literal[
        "same_service",
        "related_cuisine",
        "activity_venue",
        "preference_only",
        "unrelated",
        "insufficient",
    ]


class RelevanceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decisions: list[RelevanceDecision] = Field(max_length=20)


async def enrich_candidates(session, io):
    """One optional inference shares the existing three-inference request budget."""
    if session.relevance_attempted:
        return
    session.relevance_attempted = True
    pool, inputs = [], []
    seen = set()
    for key, args, item in session.relevance_pool[:20]:
        matched = session.policy.query_target(args)
        target = matched[1] if matched else ""
        identity = (target, plain(item.title), plain(item.category))
        if not target or identity in seen or not session.policy.eligible(item, args):
            continue
        inferred = kinds(target)
        primary = args.kind if args.kind != "any" else inferred[0] if len(inferred) == 1 else "any"
        # A semantic score cannot invent the explicit primary service missing from
        # a provider's category. Use the existing Kind registry, not venue blacklists.
        # Direct results have already passed the normal search policy and stay intact.
        if primary != "any" and source_kind(plain(item.category) or plain(item.title)) != primary:
            if hasattr(io, "stats"):
                io.stats.counts["related_kind_blocked"] = (
                    io.stats.counts.get("related_kind_blocked", 0) + 1
                )
            continue
        seen.add(identity)
        pool.append((key, args, item))
        inputs.append(
            {
                "index": len(pool) - 1,
                "request": target[:100],
                "name": plain(item.title)[:100],
                "category": plain(item.category)[:160],
            }
        )
    if not inputs or not hasattr(io, "stats") or io.stats.counts.get("model_calls", 0) >= 3:
        return
    if io.budget.remaining() < 3:
        return
    body = {
        **model_parameters(io.settings),
        "messages": [
            {"role": "system", "content": PROMPT.relevance},
            {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 2048,
    }
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    io.stats.counts["model_calls"] += 1
    io.stats.counts["request_bytes"] += len(encoded)
    try:
        with io.stats.span("model"):
            status, raw = await bounded_response(
                io.client,
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/{io.settings.cloudflare_account_id}/ai/v1/chat/completions",
                io.budget,
                limit=12000,
                seconds=10,
                content=encoded,
                headers={
                    "Authorization": f"Bearer {io.settings.cloudflare_api_token}",
                    "Content-Type": "application/json",
                },
            )
        io.stats.counts["response_bytes"] += len(raw)
        if status != 200:
            return
        payload = json.loads(raw)
        io.stats.usage(payload)
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            return
        answer = RelevanceAnswer.model_validate_json(choice["message"]["content"])
        if sorted(d.index for d in answer.decisions) != list(range(len(pool))):
            return
    except (
        httpx.HTTPError,
        HTTPException,
        TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        ValidationError,
    ):
        # Optional suggestions fail closed; direct search evidence remains usable.
        io.budget.remaining()
        return
    for decision in answer.decisions:
        index = decision.index
        key, args, item = pool[index]
        if decision.relation in {"unrelated", "insufficient"}:
            continue
        if not decision.evidence or norm(decision.evidence) not in norm(
            plain(item.title) + plain(item.category)
        ):
            continue
        candidate = session.add(
            item.title, item.roadAddress or item.address, "naver", coordinates=item.coordinates
        )
        if not candidate or candidate.source != "naver":
            continue
        candidate.match = "related"
        session.fresh_refs.add(candidate.ref)
        actual = source_kind(item.category)
        session.candidate_kinds[candidate.ref] = actual if actual != "any" else args.kind
        if not any(row["ref"] == candidate.ref for row in session.searches[key]):
            session.searches[key].append(candidate.evidence())
        if key in session.search_reports:
            session.search_reports[key]["count"] = len(session.searches[key])
    session.order_search_results()
