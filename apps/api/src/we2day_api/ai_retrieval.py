"""Bounded semantic retrieval planning for verbal goals, with no caller data reads."""

import json

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from we2day_api.ai_model import model_parameters
from we2day_api.ai_place_policy import LABELS, kinds
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_search_spec import SearchSpec, broad_goal, saved_spec
from we2day_api.prompt_bundle import PROMPT


class RetrievalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=3)
    kind: str = Field(json_schema_extra={"enum": ["literal", *LABELS]})

    @model_validator(mode="after")
    def known_kind(self):
        if self.kind not in {"literal", *LABELS}:
            raise ValueError("Unknown retrieval category")
        return self


class RetrievalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decisions: list[RetrievalDecision] = Field(min_length=1, max_length=4)


def retrieval_targets(control):
    directive = control.directive
    if directive.reply or directive.intent not in {"search", "plan"} or directive.scope.exact_name:
        return None, []
    spec = saved_spec(
        {"place_search": directive.slots.get("place_search", control.context.get("place_search"))}
    )
    if not spec:
        return None, []
    targets = [
        (i, t)
        for i, t in enumerate(spec.targets)
        if not t.category_retrieval and broad_goal(t.query)
    ]
    return spec, targets


async def plan_retrieval(control, settings, client, budget, stats):
    spec, targets = retrieval_targets(control)
    if not targets or stats.counts.get("model_calls", 0) >= 2 or budget.remaining() < 12:
        return
    values = [{"index": i, "goal": t.query} for i, t in targets]
    body = {
        **model_parameters(settings),
        "messages": [
            {"role": "system", "content": PROMPT.retrieval},
            {"role": "user", "content": json.dumps(values, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 384,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "retrieval_categories",
                "strict": True,
                "schema": RetrievalAnswer.model_json_schema(),
            },
        },
    }
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    stats.counts["model_calls"] += 1
    stats.counts["request_bytes"] += len(encoded)
    try:
        with stats.inference("interpretation"):
            status, raw = await bounded_response(
                client,
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/chat/completions",
                budget,
                limit=6000,
                seconds=10,
                content=encoded,
                headers={
                    "Authorization": f"Bearer {settings.cloudflare_api_token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as error:
        raise HTTPException(503, "ai_unavailable") from error
    stats.counts["response_bytes"] += len(raw)
    if status == 429:
        try:
            payload = json.loads(raw)
            errors = payload.get("errors", []) + (
                [payload["error"]] if isinstance(payload.get("error"), dict) else []
            )
            limited = any(str(e.get("code")) == "3036" for e in errors)
        except (ValueError, TypeError, AttributeError):
            limited = False
        raise HTTPException(429, "ai_provider_limited" if limited else "ai_provider_busy")
    if status != 200:
        raise HTTPException(503, "ai_unavailable")
    try:
        payload = json.loads(raw)
        result = payload.get("result", payload)
        stats.usage(result, role="interpretation")
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Truncated retrieval plan")
        answer = RetrievalAnswer.model_validate_json(choice["message"]["content"])
        decisions = {d.index: d.kind for d in answer.decisions}
        if len(decisions) != len(answer.decisions) or set(decisions) != {i for i, _ in targets}:
            raise ValueError("Missing or extra retrieval decision")
        for index, target in targets:
            kind = decisions[index]
            if kind == "literal":
                continue
            explicit = kinds(target.query)
            if explicit and kind not in explicit:
                raise ValueError("Contradictory explicit category")
            target.kind, target.category_retrieval = kind, True
        spec = SearchSpec.model_validate(spec.model_dump())
    except (ValueError, TypeError, KeyError, IndexError, ValidationError) as error:
        raise HTTPException(502, "ai_invalid_response") from error
    control.directive.slots["place_search"] = spec.model_dump()
    control.directive.scope.kinds = list(dict.fromkeys(t.kind for t in spec.targets))
