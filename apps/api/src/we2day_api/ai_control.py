"""One bounded task decision, versioned continuation, and factual result projection."""

import json
import re
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from we2day_api.ai_dialogue import Directive, analyze, merge_context, social_turn
from we2day_api.ai_intake import PlanningBrief, change_window, start_brief
from we2day_api.ai_place_answers import private_anchor, recover_followup_area
from we2day_api.ai_place_policy import Kind, SearchScope, explicit_area, kinds, norm
from we2day_api.ai_runtime import bounded_response
from we2day_api.prompt_bundle import PROMPT

VERSION = 1
PLACE_INTENTS = {"search", "plan", "select"}


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["search", "plan", "chat", "clarify"]
    area: str = Field(max_length=100)
    kinds: list[Kind] = Field(max_length=8)
    question: str = Field(max_length=180)


class SavedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["search", "plan", "select"]
    scope: SearchScope


class TaskState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = VERSION
    basis: int = Field(ge=0)
    last_action: SavedAction | None = None
    reason: Literal[
        "brief", "rule", "compound", "retry", "selection", "conditions", "interpreted", "clarify"
    ] = "rule"
    selected_count: int = Field(default=0, ge=0, le=8)
    outcome: Literal[
        "not_requested",
        "selection_required",
        "ambiguous",
        "unresolved",
        "empty",
        "failed",
        "partial",
        "ready",
        "not_allowed",
        "invalid_arguments",
        "budget_exhausted",
    ] = "not_requested"
    planned_tools: int = Field(default=0, ge=0, le=8)
    executed_tools: int = Field(default=0, ge=0, le=9)
    initial_brief: PlanningBrief | None = None


@dataclass
class RequestControl:
    directive: Directive
    context: dict
    reason: str
    nearby: bool = False
    include_only: bool = False
    interpret: bool = False
    model_reserved: bool = False


def state_at(context, version):
    raw = context.get("control") or {}
    try:
        state = TaskState.model_validate(raw)
        return state.model_dump(exclude_none=True) if state.basis == version else {}
    except ValidationError:
        return {}


def prepare(body, context, proposal, today):
    """Normalize all deterministic clauses before granting tool obligations."""
    latest = body.brief.message() if body.brief else body.messages[-1].content
    before = dict(context)
    control = state_at(before, body.version)
    window = None if body.brief else change_window(latest, before)
    remaining = latest
    if window:
        before = merge_context(before, {}, window)
        remaining = re.sub(
            r"(?:시작|종료|끝나는)\s*시간(?:은|는|을|이)?\s*"
            r"(?:(?:오전|오후)?\s*\d{1,2}(?::\d{2}|시(?:\s*\d{1,2}분)?)|미정)"
            r"\s*(?:으로|로)?\s*(?:바꾸고|변경하고|수정하고|해주고|하고|바꿔줘|수정해줘)?",
            "",
            latest,
        ).strip(" ,.!?")
        remaining = re.sub(r"^그리고\s*", "", remaining)
    reason = "brief" if body.brief else "rule"
    if body.brief:
        directive = start_brief(body.brief, before)
    elif window and (remaining == latest or not remaining or len(remaining) < 3):
        directive = window
    else:
        directive = analyze(
            remaining,
            before,
            proposal,
            body.chosen_places,
            today,
            selected=bool(body.selected_places),
        )
        if window:
            directive.slots.update(window.slots)
            directive.notices.append(window.reply)
            reason = "compound"
    short = re.sub(r"[\s.!?]", "", latest)
    retry = bool(
        re.fullmatch(r"(?:다시|한번더|한번만더)(?:해줘|찾아줘|추천해줘|해볼래|해)?", short)
    )
    selection_repair = bool(
        re.search(r"(?:체크|선택)(?:해\s*둔|해\s*놓|했|해놨|했잖|한\s*곳)|저장.*체크", latest)
        and not re.search(r"해제|취소|선택하지|체크하지", latest)
    )
    if not body.brief and (retry or selection_repair):
        previous = control.get("last_action") or {}
        operation = previous.get("operation", "search")
        if operation not in PLACE_INTENTS:
            operation = "search"
        directive.intent = directive.state.intent = operation
        directive.reply = ""
        directive.state.pending = None
        if retry and previous.get("scope"):
            directive.scope = SearchScope.model_validate(previous["scope"])
        directive.scope.area = directive.scope.area or before.get("region", "")
        directive.scope.kinds = directive.scope.kinds or kinds(
            " ".join(before.get("activities", []))
        )
        directive.allowed_tools = {"search_places"}
        reason = "retry" if retry else "selection"
    if directive.intent in PLACE_INTENTS or directive.place_followup:
        # Do not override a new explicit private anchor or a new selected-anchor correction.
        if (
            not (private_anchor(explicit_area(latest)) and explicit_area(latest))
            and not selection_repair
        ):
            recover_followup_area(directive, body.messages[:-1])
    replacement_area = explicit_area(latest)
    if (
        directive.intent == "chat"
        and replacement_area
        and re.search(r"지역|동네|으로|바꿔|바꾸|변경", latest)
    ):
        directive.intent = directive.state.intent = "edit"
        directive.scope.area = replacement_area
        directive.slots["region"] = replacement_area
        directive.reply = f"지역을 {replacement_area}(으)로 바꿨어요."
        reason = "conditions"
    nearby = bool(re.search(r"근처|주변|인근|주위", latest)) or private_anchor(directive.scope.area)
    anchor_selected = any(p.usage == "anchor" for p in body.selected_places)
    include_only = bool(
        body.selected_places
        and directive.intent in {"plan", "select"}
        and not nearby
        and not anchor_selected
        and (
            not directive.scope.area
            or not re.search(r"검색|찾|추천|알아|살펴", latest)
            or body.brief
            and not body.brief.region
        )
    )
    relevant = directive.intent in PLACE_INTENTS or bool(directive.place_followup)
    if relevant and body.selected_places:
        directive.allowed_tools.add("lookup_selected_places")
    if relevant and not directive.reply:
        if include_only:
            directive.allowed_tools.discard("search_places")
        elif directive.intent in {"search", "plan"} or directive.place_followup:
            directive.allowed_tools.add("search_places")
    social = bool(directive.reply or social_turn(latest))
    tasklike = bool(
        kinds(latest)
        or re.search(r"장소|근방|동네|근처|주변|고른|체크|거기|밥|한잔|가볼|추천|코스|플랜", latest)
    )
    unclear = (
        directive.intent == "chat"
        and not directive.place_followup
        and not social
        and not directive.slots
        and tasklike
        and bool(before.get("region") or body.selected_places or proposal)
    )
    new_public_area = bool(explicit_area(latest) and not private_anchor(explicit_area(latest)))
    anchor_search = not new_public_area and (
        anchor_selected
        or selection_repair
        and bool(body.selected_places)
        or private_anchor(directive.scope.area)
        or nearby
        and not directive.scope.area
    )
    return RequestControl(directive, before, reason, anchor_search, include_only, unclear)


async def interpret(control, latest, settings, client, budget, stats):
    """An interpretation proposal has no permission, tool invocation, or invented facts."""
    schema = Action.model_json_schema()
    inputs = {
        "model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "messages": [
            {"role": "system", "content": PROMPT.interpret},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": latest,
                        "area": control.directive.scope.area,
                        "kinds": control.directive.scope.kinds,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "task_action", "strict": True, "schema": schema},
        },
        "temperature": 0,
        "max_tokens": 400,
    }
    stats.counts["model_calls"] += 1
    encoded = json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode()
    stats.counts["request_bytes"] += len(encoded)
    try:
        with stats.span("model"):
            status, raw = await bounded_response(
                client,
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/chat/completions",
                budget,
                limit=12000,
                seconds=15,
                content=encoded,
                headers={
                    "Authorization": f"Bearer {settings.cloudflare_api_token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as error:
        raise HTTPException(503, "ai_unavailable") from error
    stats.counts["response_bytes"] += len(raw)
    if status != 200:
        raise HTTPException(
            429 if status == 429 else 503,
            "ai_provider_limited" if status == 429 else "ai_unavailable",
        )
    try:
        payload = json.loads(raw)
        stats.usage(payload)
        value = payload["choices"][0]["message"]["content"]
        action = (
            Action.model_validate_json(value)
            if isinstance(value, str)
            else Action.model_validate(value)
        )
        scope = control.directive.scope
        # A proposed location must already be user-supplied, never a model geocode.
        if (
            action.area
            and norm(action.area) not in norm(latest)
            and norm(action.area) != norm(scope.area)
        ):
            raise ValueError("Ungrounded area")
        allowed = set(kinds(latest)) | set(scope.kinds)
        if any(k not in allowed for k in action.kinds):
            raise ValueError("Unrequested activity")
        if (
            action.operation in {"search", "plan"}
            and (action.area or scope.area)
            and (action.kinds or scope.kinds)
        ):
            directive = control.directive
            directive.intent = directive.state.intent = action.operation
            directive.scope.area = action.area or scope.area
            directive.scope.kinds = action.kinds or scope.kinds
            directive.scope.search_only = action.operation == "search"
            directive.slots["region"] = directive.scope.area
            directive.allowed_tools = {"search_places"}
            if action.operation == "plan" and not control.context.get("date"):
                directive.ask(
                    "date", "어느 날짜의 코스로 정할까요? 날짜를 알려주세요.", resume="plan"
                )
            control.reason = "interpreted"
        elif action.operation == "clarify":
            control.directive.ask(
                "target",
                "어느 장소나 활동을 어떻게 할까요? 원하는 작업을 알려주세요.",
                resume="search",
            )
            control.reason = "clarify"
    except (ValueError, KeyError, TypeError, IndexError, ValidationError):
        control.directive.ask(
            "target", "원하는 지역과 활동을 조금 더 구체적으로 알려주세요.", resume="search"
        )
        control.reason = "clarify"


def reduce_context(before, incoming, directive, body, session, reason):
    """Only this projection records action/conditions; no selected IDs or result lists."""
    result = merge_context(before, incoming, directive)
    old = state_at(before, body.version)
    previous = old.get("last_action")
    operation = (
        directive.state.pending.resume
        if directive.state.pending and directive.state.pending.resume in PLACE_INTENTS
        else directive.intent
    )
    if operation in PLACE_INTENTS or directive.place_followup:
        previous = {
            "operation": operation if operation in PLACE_INTENTS else "search",
            "scope": directive.scope.model_dump(),
        }
    elif previous and directive.slots.get("region"):
        previous = {**previous, "scope": {**previous["scope"], "area": directive.slots["region"]}}
    control = {
        "version": VERSION,
        "basis": body.version + 1,
        "last_action": previous,
        "reason": reason,
        "selected_count": len(body.selected_places),
        "outcome": session.resolution,
        "planned_tools": len(directive.allowed_tools),
        "executed_tools": len(session.reports),
    }
    if body.brief:
        control["initial_brief"] = body.brief.model_dump()
    elif isinstance(before.get("control"), dict) and before["control"].get("initial_brief"):
        control["initial_brief"] = before["control"]["initial_brief"]
    result["control"] = TaskState.model_validate(control).model_dump(exclude_none=True)
    # intake is the current form projection; the original brief is separately retained.
    if result.get("intake"):
        current = dict(result["intake"])
        current["data"] = {
            **current["data"],
            **{
                k: result[k]
                for k in ("date", "region", "budget", "transport", "activities", "requirements")
                if k in result
            },
        }
        current["data"]["recommend"] = not bool(current["data"].get("activities"))
        result["intake"] = current
    return result
