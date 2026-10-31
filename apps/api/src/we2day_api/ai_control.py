"""One bounded task decision, versioned continuation, and factual result projection."""

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from we2day_api.ai_dialogue import Directive, analyze, merge_context, new_task, social_turn
from we2day_api.ai_edits import cancel_request
from we2day_api.ai_intake import PlanningBrief, change_window, start_brief
from we2day_api.ai_place_answers import address_area, private_anchor, recover_followup_area
from we2day_api.ai_place_policy import (
    LABELS,
    Kind,
    SearchScope,
    explicit_area,
    kinds,
    norm,
    relational_area,
)
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_search_followups import (
    continuation,
    grounded_query,
    refinement,
    result_question,
    saved_refinement,
)
from we2day_api.ai_search_spec import (
    SearchSpec,
    SearchTarget,
    anchor_key,
    area_only_request,
    changed_area,
    place_name,
    referenced_anchor,
    saved_spec,
    scope_for,
    semantic_request,
)
from we2day_api.prompt_bundle import PROMPT

VERSION = 1
PLACE_INTENTS = {"search", "plan", "select"}


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["search", "plan", "chat", "clarify"]
    area: str = Field(default="", max_length=100)
    kinds: list[Kind] = Field(default_factory=list, max_length=8)
    question: str = Field(default="", max_length=180)
    query: str = Field(default="", max_length=50)
    targets: list[str] = Field(default_factory=list, max_length=4)
    anchor_ref: str = Field(default="", max_length=32)
    anchor_index: int | None = Field(default=None, ge=0, le=7)
    anchor_needed: bool = False


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
    proposal: object = None
    previous_request: str = ""


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
    narrowed = None if body.brief else refinement(latest)
    if (
        not narrowed
        and continuation(latest)
        and not saved_spec(before)
        and (control.get("last_action") or {}).get("operation") == "search"
    ):
        # Legacy promise/status chain: stop at the most recent substantive user request.
        prior = next(
            (
                m.content
                for m in reversed(body.messages[:-1])
                if m.role == "user" and not continuation(m.content)
            ),
            "",
        )
        narrowed = refinement(prior)
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
            remaining + " 장소 찾아줘" if narrowed else remaining,
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
    if not body.brief and cancel_request(latest):
        directive = Directive(
            directive.state,
            directive.scope,
            intent="chat",
            reply="진행 중인 변경을 취소했어요. 이미 정한 조건과 코스는 유지해요.",
        )
        directive.state.intent = "chat"
        directive.state.pending = None
        directive.state.append_pending = False
        directive.slots.update(activity_edit=None, pending_fields=None)
        if before.get("intake"):
            directive.slots["intake"] = {**before["intake"], "pending": None}
        directive.slots["place_search"] = None
        directive.allowed_tools.clear()
        return RequestControl(directive, before, "rule", proposal=proposal)
    if (
        not window
        and (before.get("intake") or {}).get("pending")
        and (new_task(latest) or narrowed)
    ):
        directive.slots["intake"] = {**before["intake"], "pending": None}
    if narrowed:
        directive.intent = directive.state.intent = "search"
        directive.reply, directive.plan = "", None
        directive.state.pending = None
        directive.scope.kinds = [narrowed["kind"]]
        directive.state.excluded_kinds = [
            k for k in directive.state.excluded_kinds if k != narrowed["kind"]
        ]
        directive.scope.exact_name, directive.scope.name_kind = "", "any"
        directive.scope.search_only = True
        directive.slots.update(place_search=narrowed, activity_edit=None, pending_fields=None)
    elif directive.intent in PLACE_INTENTS and not result_question(latest):
        # An explicit new search/selection replaces a one-off lexical refinement.
        previous_spec = saved_spec(before)
        if previous_spec and area_only_request(latest):
            if not previous_spec.anchor_key:
                previous_spec.area = directive.scope.area
            directive.slots["place_search"] = previous_spec.model_dump()
        else:
            directive.slots["place_search"] = None
    short = re.sub(r"[\s.!?]", "", latest)
    retry = (
        bool(
            re.fullmatch(
                r"(?:저장(?:한)?장소(?:를|도)?(?:포함해서|포함해|함께)?)?"
                r"(?:다시|한번더|한번만더)(?:해줘|찾아줘|추천해줘|해볼래|해)?",
                short,
            )
        )
        and not narrowed
    )
    selection_repair = bool(
        re.search(r"(?:체크|선택)(?:해\s*둔|해\s*놓|했|해놨|했잖|한\s*곳)|저장.*체크", latest)
        and not re.search(r"해제|취소|선택하지|체크하지", latest)
    )
    if not body.brief and (retry or selection_repair):
        directive.slots.pop("place_search", None)
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
        if not directive.scope.kinds and not (retry and previous.get("scope")):
            directive.scope.kinds = kinds(" ".join(before.get("activities", [])))
        directive.allowed_tools = {"search_places"}
        reason = "retry" if retry else "selection"
        if retry and control and control.get("last_action") is None:
            directive.ask(
                "target",
                "어떤 작업을 다시 할까요? 원하는 검색이나 변경을 알려주세요.",
                resume="search",
            )
        elif (
            retry
            and previous.get("scope")
            and not directive.scope.kinds
            and directive.state.excluded_kinds
        ):
            directive.ask("target", "남길 활동이나 새로 찾을 활동을 알려주세요.", resume="search")
    if result_question(latest) and control and control.get("last_action") is None:
        directive.place_followup = ""
        directive.allowed_tools.clear()
        directive.reply = "진행 중인 검색은 없어요. 다시 찾을 지역이나 장소를 알려주세요."
    if directive.intent in PLACE_INTENTS or directive.place_followup:
        # A selection correction does not erase the user's earlier explicit area.
        if not (private_anchor(explicit_area(latest)) and explicit_area(latest)):
            recover_followup_area(directive, body.messages[:-1])
    requested_kinds = list(directive.scope.kinds)
    directive.scope.kinds = [
        kind for kind in directive.scope.kinds if kind not in directive.state.excluded_kinds
    ]
    if (
        requested_kinds
        and not directive.scope.kinds
        and directive.intent in PLACE_INTENTS
        and not directive.reply
    ):
        directive.ask("target", "남길 활동이나 새로 찾을 활동을 알려주세요.", resume="search")
    if (
        directive.intent == "search"
        and not directive.reply
        and not directive.scope.area
        and not directive.scope.exact_name
        and not body.selected_places
    ):
        directive.ask(
            "region", "어느 지역에서 찾아볼까요? 동네나 지역을 알려주세요.", resume="search"
        )
    if directive.intent in {"plan", "select"} and not directive.reply:
        known_date = directive.slots.get("date", before.get("date"))
        if not known_date and not directive.state.cleared_date and proposal:
            known_date = proposal.date
        if not known_date:
            directive.ask(
                "date", "어느 날짜의 코스로 정할까요? 날짜를 알려주세요.", resume=directive.intent
            )
    replacement_area = changed_area(latest) or explicit_area(latest)
    if (
        (directive.intent == "chat" or changed_area(latest))
        and replacement_area
        and re.search(r"지역|동네|으로|바꿔|바꾸|변경", latest)
    ):
        directive.intent = directive.state.intent = "edit"
        directive.state.pending = None
        directive.allowed_tools.clear()
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
        or re.search(
            r"장소|근방|동네|근처|주변|고른|체크|거기|밥|한잔|가볼|추천|코스|플랜|없나|있을까|먹고\s*싶",
            latest,
        )
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
    legacy_retry = (
        continuation(latest)
        and not saved_spec(before)
        and (
            bool(before.get("place_search") and not saved_spec(before))
            or relational_area(directive.scope.area)
            or control.get("outcome") == "not_requested"
            and not directive.reply
            and (control.get("last_action") or {}).get("operation") == "search"
        )
    )
    semantic = (
        not body.brief
        and not directive.slots.get("pending_fields")
        and not social_turn(latest)
        and (legacy_retry or not retry and semantic_request(latest, directive, proposal, before))
    )
    if semantic:
        directive.reply = ""
        directive.allowed_tools.clear()
        directive.state.pending = None
        directive.slots.update(activity_edit=None, pending_fields=None)
        if not re.search(r"날짜|예산|이동\s*수단|제목", latest):
            directive.plan = None
        named = proposal and any(
            norm(place_name(a)) == norm(directive.scope.area) for a in proposal.activities
        )
        if relational_area(directive.scope.area) or named:
            directive.scope.area = before.get("region", "")
        if relational_area(directive.scope.area):
            directive.scope.area = ""
    request = RequestControl(
        directive,
        before,
        reason,
        anchor_search,
        include_only,
        unclear or semantic,
        proposal=proposal,
    )
    request.previous_request = next(
        (
            m.content
            for m in reversed(body.messages[:-1])
            if m.role == "user" and not continuation(m.content) and not social_turn(m.content)
        ),
        "",
    )
    if semantic and resume_anchor_answer(request, latest):
        request.interpret = False
    return request


def resume_anchor_answer(control, latest):
    """A current activity reference answers the pending question without another guess."""
    spec = saved_spec(control.context)
    if (
        not spec
        or not spec.anchor_pending
        or re.search(r"찾|검색|추천|알려|바꿔|바꾸|변경|취소|제외", latest)
    ):
        return False
    index, required = referenced_anchor(latest, control.proposal, True)
    area = control.context.get("region", "")
    if not required or index is None or not area or relational_area(area):
        return False
    activity = control.proposal.activities[index]
    if not place_name(activity):
        return False
    spec.anchor_index, spec.anchor_key = index, anchor_key(activity)
    spec.anchor_pending, spec.area = False, area
    directive = control.directive
    directive.scope = scope_for(spec.targets, area)
    directive.intent = directive.state.intent = "search"
    directive.state.pending = None
    directive.reply, directive.plan = "", None
    directive.allowed_tools = {"search_places"}
    directive.slots.update(place_search=spec.model_dump(), activity_edit=None, pending_fields=None)
    control.reason = "rule"
    return True


async def restore_saved_area(control, body, store, stats):
    """Repair legacy alias state from this author's conversation, never model prose.

    Client model input intentionally contains only a short tail. Read at most the
    existing history RPC's fifty turns only while that tail cannot repair an alias.
    The retrieved text is server-only evidence; it is not appended to model input.
    """
    directive = control.directive
    latest = body.messages[-1].content
    if (
        body.brief
        or not body.conversation_id
        or not body.version
        or sum(message.role == "user" for message in body.messages[:-1]) >= body.version
        or not (private_anchor(directive.scope.area) or relational_area(directive.scope.area))
        or private_anchor(explicit_area(latest))
        or not (directive.intent in PLACE_INTENTS or directive.place_followup or control.interpret)
    ):
        return
    with stats.span("context"):
        history = await store.rpc(
            "read_ai_conversations",
            {"p_id": str(body.conversation_id), "p_before": body.version + 1},
        )
    stats.counts["history_repair_reads"] = 1
    if (
        not isinstance(history, dict)
        or history.get("id") != str(body.conversation_id)
        or history.get("version") != body.version
        or not isinstance(history.get("turns"), list)
        or len(history["turns"]) > 50
    ):
        return
    turns = history["turns"]
    if any(
        not isinstance(turn, dict)
        or type(turn.get("version")) is not int
        or not 0 < turn["version"] <= body.version
        or not isinstance(turn.get("user_text"), str)
        or len(turn["user_text"]) > 4000
        for turn in turns
    ) or len({turn["version"] for turn in turns}) != len(turns):
        return
    recover_followup_area(
        directive,
        [
            SimpleNamespace(role="user", content=t["user_text"])
            for t in sorted(turns, key=lambda t: t["version"])
        ],
    )
    if not private_anchor(directive.scope.area) and not relational_area(directive.scope.area):
        control.interpret = False


async def interpret(control, latest, settings, client, budget, stats):
    """An interpretation proposal has no permission, tool invocation, or invented facts."""
    if resume_anchor_answer(control, latest):
        return
    prior_view = saved_spec(control.context)
    legacy_view = saved_refinement(control.context, control.directive.scope)
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
                        "previous_search": (
                            {
                                "targets": [t.query for t in prior_view.targets],
                                "awaiting_anchor": prior_view.anchor_pending,
                            }
                            if prior_view
                            else {"targets": [legacy_view["query"]], "awaiting_anchor": False}
                            if legacy_view
                            else None
                        ),
                        "previous_request": control.previous_request,
                        "activities": [
                            {
                                "ref": f"activity_{i + 1}",
                                "number": i + 1,
                                "title": a.title,
                                "place_name": place_name(a),
                            }
                            for i, a in enumerate(control.proposal.activities)
                        ]
                        if control.proposal
                        else [],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
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
        if payload["choices"][0].get("finish_reason") == "length":
            raise ValueError("Incomplete interpretation")
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
        prior = saved_spec(control.context)
        targets = []
        for query in action.targets:
            query = " ".join(query.split())
            if any(norm(t.query) == norm(query) for t in targets):
                continue
            detected = kinds(query)
            specific = [k for k in detected if k != "restaurant"]
            kind = (
                specific[0] if len(specific) == 1 else detected[0] if len(detected) == 1 else "any"
            )
            targets.append(SearchTarget(kind=kind, query=query))
        if action.anchor_ref:
            match = re.fullmatch(r"activity_([1-8])", action.anchor_ref)
            if not match:
                raise ValueError("Unknown anchor reference")
            action.anchor_index = int(match[1]) - 1
        if not targets and action.kinds:
            # Compatibility for older interpreter outputs; arbitrary classes still
            # need a user-grounded query, not merely an inherited search scope.
            allowed = set(kinds(latest)) | set(scope.kinds)
            if any(k not in allowed for k in action.kinds):
                raise ValueError("Unrequested activity")
            targets = [
                SearchTarget(kind=k, query=action.query or LABELS.get(k, "")) for k in action.kinds
            ]
        evidence = latest
        resuming = bool(prior and prior.anchor_pending) or continuation(latest)
        if resuming and prior:
            evidence += " " + " ".join(t.query for t in prior.targets)
        if resuming:
            evidence += " " + control.previous_request
            if legacy_view:
                evidence += " " + legacy_view["query"]
        relation = re.search(r"주변|근처|인근|주위", latest)
        target_evidence = latest[relation.end() :] if relation else evidence
        for target in targets:
            if not grounded_query(target.query, evidence):
                raise ValueError("Ungrounded query")
        replacement = re.split(r"말고|대신", target_evidence)
        if len(replacement) > 1 and re.search(r"찾|검색|추천|알려", replacement[-1]):
            target_evidence = replacement[-1]
        if relation or len(replacement) > 1:
            targets = [t for t in targets if grounded_query(t.query, target_evidence)]
        spec = SearchSpec(targets=targets) if targets else None
        anchor_text = (
            control.previous_request
            if continuation(latest) and control.previous_request
            else latest
        )
        expected_anchor, required_anchor = referenced_anchor(
            anchor_text, control.proposal, bool(prior and prior.anchor_pending)
        )
        if required_anchor:
            action.anchor_index = expected_anchor
            action.anchor_needed = expected_anchor is None
        elif action.anchor_index is not None:
            # A model-generated reference is not evidence that the user named it.
            action.anchor_index, action.anchor_needed = None, True
        if action.anchor_index is not None:
            if not relation and not resuming:
                raise ValueError("Unrequested anchor")
            if not control.proposal or action.anchor_index >= len(control.proposal.activities):
                raise ValueError("Unknown anchor")
            activity = control.proposal.activities[action.anchor_index]
            if not place_name(activity):
                action.anchor_needed = True
            elif spec:
                spec.anchor_index = action.anchor_index
                spec.anchor_key = anchor_key(activity)
        directive = control.directive
        if spec:
            if spec.anchor_key and (not scope.area or relational_area(scope.area)):
                activity = control.proposal.activities[spec.anchor_index]
                address = re.search(r"\(([^()]*)\)", activity.place)
                scope.area = address_area(address[1]) if address else ""
            directive.scope = scope_for(targets, action.area or scope.area)
            spec.area = directive.scope.area
            directive.slots["place_search"] = spec.model_dump()
        if action.anchor_needed and (not spec or not spec.anchor_key):
            if spec:
                spec.anchor_pending = True
                directive.slots["place_search"] = spec.model_dump()
            directive.ask(
                "target",
                "어느 장소를 기준으로 무엇을 찾을까요? 활동 번호나 장소를 알려주세요.",
                resume="search",
            )
            control.reason = "clarify"
        elif action.operation == "clarify":
            directive.ask(
                "region" if spec and not directive.scope.area else "target",
                "어느 지역에서 찾아볼까요? 동네나 지역을 알려주세요."
                if spec and not directive.scope.area
                else "어떤 활동이나 장소를 찾고 싶은지 알려주세요.",
                resume="search",
            )
            control.reason = "clarify"
        elif action.operation in {"search", "plan"} and spec and directive.scope.area:
            directive.intent = directive.state.intent = action.operation
            directive.state.pending = None
            directive.reply, directive.place_followup = "", ""
            directive.slots.update(activity_edit=None, pending_fields=None)
            directive.state.excluded_kinds = [
                k for k in directive.state.excluded_kinds if k not in directive.scope.kinds
            ]
            directive.scope.search_only = action.operation == "search"
            directive.slots["region"] = directive.scope.area
            directive.allowed_tools = {"search_places"}
            if action.operation == "plan" and not control.context.get("date"):
                directive.ask(
                    "date", "어느 날짜의 코스로 정할까요? 날짜를 알려주세요.", resume="plan"
                )
            control.reason = "interpreted"
        elif action.operation == "chat":
            directive.intent = directive.state.intent = "chat"
            directive.allowed_tools.clear()
        else:
            directive.ask("region", "어느 지역에서 어떤 장소를 찾아볼까요?", resume="search")
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
    cancelled = not body.brief and cancel_request(body.messages[-1].content)
    if cancelled:
        previous = None
        result["place_search"] = None
    operation = (
        directive.state.pending.resume
        if directive.state.pending and directive.state.pending.resume in PLACE_INTENTS
        else directive.intent
    )
    if not cancelled and (operation in PLACE_INTENTS or directive.place_followup):
        previous = {
            "operation": operation if operation in PLACE_INTENTS else "search",
            "scope": directive.scope.model_dump(),
        }
    elif previous:
        previous = {**previous, "scope": directive.scope.model_dump()}
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
    if (
        not body.brief
        and directive.intent == "chat"
        and not cancel_request(body.messages[-1].content)
    ):
        # A social turn preserves an active clarification across every controller;
        # otherwise its unchanged basis would look like an older API writer next turn.
        for name in ("intake", "activity_edit", "pending_fields"):
            value = result.get(name)
            if isinstance(value, dict) and value.get("turn_version") == body.version:
                result[name] = {**value, "turn_version": body.version + 1}
    return result
