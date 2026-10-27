"""Bounded read tools and private conversation context; no model-directed business writes."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from functools import cache
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from we2day_api.ai_context import model_messages
from we2day_api.ai_dialogue import analyze, merge_context
from we2day_api.ai_dialogue import explicit_date as explicit_date
from we2day_api.ai_intake import PlanningBrief, change_window, start_brief, window_checks
from we2day_api.ai_place_answers import (
    candidate_reply,
    claims_place_search,
    read_candidate_request,
    recover_followup_area,
)
from we2day_api.ai_place_policy import PlacePolicy
from we2day_api.ai_runtime import (
    AIStore,
    Budget,
    RunStats,
    ai_transport,
    bounded_response,
    with_disconnect,
)
from we2day_api.ai_tool_runtime import ToolIO, execute_batch
from we2day_api.ai_tools import (
    TOOLS,
    Candidate,
    ChosenPlace,
    ModelAnswer,
    ModelPlan,
    PlanningContext,
    SelectedPlace,
    StoredContext,
    ToolSession,
    WeatherSummary,
    check_course,
    place_options,
)
from we2day_api.calendar import Store
from we2day_api.plans import Activity, PlanContent
from we2day_api.prompt_bundle import PROMPT

router = APIRouter(tags=["ai-planner"])
logger = logging.getLogger(__name__)
PROMPT_VERSION = PROMPT.version
PROMPT_SHA256 = PROMPT.sha256
MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"
SYSTEM = PROMPT.system


@cache
def _answer_schema_json():
    # Static parser metadata only. No user value ever enters this process-wide cache.
    schema = ModelAnswer.model_json_schema()

    def strict_object(value):
        if isinstance(value, dict):
            if isinstance(value.get("title"), str):
                value.pop("title", None)
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                strict_object(child)
        elif isinstance(value, list):
            for child in value:
                strict_object(child)

    strict_object(schema)
    return json.dumps(schema, separators=(",", ":"))


def answer_format(plan_date=None, activity_limit=None):
    # Fresh mutable schema per request, backed by an immutable static JSON template.
    schema = json.loads(_answer_schema_json())
    if plan_date:
        schema["properties"]["plan"] = {"$ref": "#/$defs/ModelPlan"}
        schema["$defs"]["ModelPlan"]["properties"]["date"]["const"] = plan_date
    if activity_limit:
        schema["$defs"]["ModelPlan"]["properties"]["activities"]["maxItems"] = activity_limit
        schema["$defs"]["ModelPlan"]["properties"]["activities"]["minItems"] = activity_limit
    return {
        "type": "json_schema",
        "json_schema": {"name": "we2day_answer", "strict": True, "schema": schema},
    }


ANSWER_FORMAT = answer_format()


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # Compatibility only. New UI explicitly submits text without a separate checkbox.
    consent: Literal[True] | None = None
    messages: list[Message] = Field(min_length=1, max_length=12)
    proposal: PlanContent | None = None
    conversation_id: UUID | None = Field(default=None, strict=False)
    request_id: UUID | None = Field(default=None, strict=False)
    version: int = Field(default=0, ge=0)
    selected_places: list[SelectedPlace] = Field(default_factory=list, max_length=8)
    chosen_places: list[ChosenPlace] = Field(default_factory=list, max_length=8)
    brief: PlanningBrief | None = None

    @model_validator(mode="after")
    def first_brief(self):
        if self.brief:
            if self.version != 0 or len(self.messages) != 1 or self.proposal or self.chosen_places:
                raise ValueError("Conditions are a first-turn input")
            if not self.brief.region and not self.selected_places:
                raise ValueError("Provide a region or explicitly selected places")
        return self


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str = Field(min_length=1, max_length=4000)
    plan: PlanContent | None = None
    context: StoredContext = Field(default_factory=StoredContext)
    checks: list[str] = Field(default_factory=list, max_length=16)
    tools: list[dict] = Field(default_factory=list, max_length=9)
    weather: list[WeatherSummary] = Field(default_factory=list, max_length=2)
    prompt_version: str | None = Field(default=None, max_length=80)
    prompt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SavedChatResult(ChatResult):
    conversation_id: UUID | None = None
    version: int = 0
    candidates: list[Candidate] = Field(default_factory=list, max_length=64)


async def complete(
    settings,
    messages: list[dict],
    session: ToolSession | None = None,
    *,
    client=None,
    budget=None,
    stats=None,
    io=None,
) -> ChatResult:
    """At most three inferences per user request; fixed host/model and overall deadline."""
    if len(json.dumps(messages, ensure_ascii=False).encode()) > 24000:
        raise HTTPException(422, "ai_context_too_long")
    budget = budget or Budget()
    stats = stats or RunStats(PROMPT_VERSION)
    if client is None:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as owned:
            return await complete(
                settings, messages, session, client=owned, budget=budget, stats=stats, io=io
            )
    format_completion = False
    schema_completion = bool(session and session.direct_final)
    try:
        for step in range(3):
            budget.remaining()
            final = step == 2 or session is None or format_completion or schema_completion
            inputs = {
                "model": MODEL,
                "messages": messages,
                "max_tokens": 2048,
                "temperature": 0.4,
            }
            if final:
                inputs["response_format"] = (
                    answer_format(session.plan_date, session.activity_limit)
                    if session and session.require_plan
                    else ANSWER_FORMAT
                )
                if session:
                    inputs["messages"] = messages + [
                        {
                            "role": "system",
                            "content": PROMPT.finish,
                        }
                    ]
            else:
                inputs["tools"] = [
                    tool
                    for tool in TOOLS
                    if session.allowed_tools is None
                    or tool["function"]["name"] in session.allowed_tools
                ]
                inputs["tool_choice"] = "auto"
            if len(json.dumps(inputs, ensure_ascii=False).encode()) > 48000:
                raise HTTPException(422, "ai_context_too_long")
            encoded = json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode()
            stats.counts["model_calls"] += 1
            stats.counts["request_bytes"] += len(encoded)
            with stats.span("model"):
                status_code, raw = await bounded_response(
                    client,
                    "POST",
                    f"https://api.cloudflare.com/client/v4/accounts/"
                    f"{settings.cloudflare_account_id}/ai/v1/chat/completions",
                    budget,
                    limit=65536,
                    seconds=28,
                    headers={
                        "Authorization": f"Bearer {settings.cloudflare_api_token}",
                        "Content-Type": "application/json",
                    },
                    content=encoded,
                )
            stats.counts["response_bytes"] += len(raw)
            if status_code == 429:
                try:
                    error_payload = json.loads(raw)
                    errors = error_payload.get("errors", [])
                    if isinstance(error_payload.get("error"), dict):
                        errors.append(error_payload["error"])
                    exhausted = any(str(item.get("code")) == "3036" for item in errors)
                except (ValueError, TypeError, AttributeError):
                    exhausted = False
                raise HTTPException(429, "ai_provider_limited" if exhausted else "ai_provider_busy")
            if not 200 <= status_code < 300:
                raise HTTPException(503, "ai_unavailable")
            payload = json.loads(raw)
            if payload.get("success") is False:
                raise HTTPException(503, "ai_unavailable")
            result = payload.get("result", payload)
            stats.usage(payload if "usage" in payload else result)
            if "choices" in result:
                message = result["choices"][0]["message"]
            else:
                message = {
                    "content": result.get("response"),
                    "tool_calls": result.get("tool_calls", []),
                }
            calls = message.get("tool_calls") or []
            if calls:
                if final or not session or len(calls) > 4:
                    raise HTTPException(502, "ai_invalid_response")
                normalized = []
                for index, call in enumerate(calls):
                    function = call.get("function", call)
                    args = function.get("arguments", {})
                    normalized.append(
                        {
                            "id": f"call_{step}_{index}",
                            "type": "function",
                            "function": {
                                "name": function["name"],
                                "arguments": args
                                if isinstance(args, str)
                                else json.dumps(args, ensure_ascii=False),
                            },
                        }
                    )
                messages.append({"role": "assistant", "content": "", "tool_calls": normalized})
                with stats.span("tools"):
                    if io is not None:
                        outcomes = await execute_batch(session, normalized, io)
                    else:
                        # Pure in-memory doubles used by direct completion tests.
                        outcomes = [
                            session.execute(c["function"]["name"], c["function"]["arguments"])
                            for c in normalized
                        ]
                stats.counts["tool_calls"] = session.calls
                blocked = sum(
                    o.get("error")
                    in {
                        "outside_requested_scope",
                        "excluded_activity_kind",
                        "tool_not_allowed_for_current_request",
                    }
                    for o in outcomes
                )
                if blocked:
                    stats.counts["scope_blocks"] = stats.counts.get("scope_blocks", 0) + blocked
                for call, outcome in zip(normalized, outcomes, strict=True):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(
                                outcome, ensure_ascii=False, separators=(",", ":")
                            ),
                        }
                    )
                # Successful evidence can go directly to structured completion. Failed reads
                # may use the remaining planning round, always within the same total budget.
                schema_completion = all(not outcome.get("error") for outcome in outcomes)
                if session.needs_place_search and not session.searches:
                    schema_completion = False
                if session.policy.scope.kinds and len(session.policy.scope.kinds) > 1:
                    schema_completion = set(session.policy.scope.kinds) <= set(
                        session.candidate_kinds.values()
                    )
                continue
            text = message.get("content")
            if not final:
                schema_completion = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": text
                        if isinstance(text, str)
                        else json.dumps(text, ensure_ascii=False),
                    }
                )
                continue
            try:
                if isinstance(text, str):
                    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
                    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
                    model_answer = ModelAnswer.model_validate_json(text)
                else:
                    model_answer = ModelAnswer.model_validate(text)
                if (
                    session
                    and session.require_plan
                    and (not model_answer.plan or model_answer.plan.date != session.plan_date)
                ):
                    raise ValueError("Missing requested plan or date mismatch")
            except (ValidationError, ValueError):
                if format_completion or step == 2:
                    raise
                # One formatting completion inside the same three-call budget, never a
                # retry of transport/provider failures or permission errors.
                format_completion = True
                stats.counts["schema_repairs"] = stats.counts.get("schema_repairs", 0) + 1
                messages.append(
                    {
                        "role": "assistant",
                        "content": text
                        if isinstance(text, str)
                        else json.dumps(text, ensure_ascii=False),
                    }
                )
                messages.append(
                    {
                        "role": "system",
                        "content": PROMPT.repair,
                    }
                )
                continue
            plan = session.resolve(model_answer.plan) if session and model_answer.plan else None
            guarded = []
            if session:
                plan, guarded = session.guard_plan(model_answer.plan, plan)
                if plan and session.append_only and session.previous_plan:
                    places = {(a.place, a.map_url) for a in session.previous_plan.activities}
                    new = [
                        a for a in plan.activities if a.place and (a.place, a.map_url) not in places
                    ]
                    if not new or len(new) + len(session.previous_plan.activities) > 8:
                        plan = None
                        guarded.append("추가할 새 장소를 선택해 주세요. 활동은 최대 8개예요.")
                    else:
                        plan = session.previous_plan.model_copy(deep=True)
                        plan.activities.extend(new)
                        for name, value in session.plan_updates.items():
                            setattr(plan, name, value)
                        plan = PlanContent.model_validate(plan.model_dump())
            checks = (check_course(plan) if plan else []) + guarded
            reply = model_answer.reply
            if session and (
                session.operation in {"search", "reject"}
                or session.operation is None
                and session.policy.scope.search_only
                or guarded
                and session.operation not in {"chat", "weather"}
                or session.operation != "weather"
                and not plan
                and claims_place_search(reply)
            ):
                reply = candidate_reply(session)
            if plan and session:
                session.reports.append(
                    {"name": "validate_course", "status": "ok", "count": len(checks)}
                )
            return ChatResult(
                reply=reply,
                plan=plan,
                context=StoredContext.model_validate(
                    (model_answer.context or PlanningContext()).model_dump(exclude_unset=True)
                ),
                checks=checks,
                tools=session.reports if session else [],
                weather=session.weather if session else [],
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
            )
        raise HTTPException(502, "ai_invalid_response")
    except TimeoutError as error:
        raise HTTPException(503, "ai_timeout") from error
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        ValidationError,
    ) as error:
        logger.warning("AI completion failed: category=%s", type(error).__name__)
        raise HTTPException(502, "ai_invalid_response") from error


@router.get("/ai/planner")
def status(request: Request, response: Response, store: Store):
    response.headers["Cache-Control"] = "private, no-store"
    if not store.rpc("get_my_couple"):
        raise HTTPException(403, "couple_required")
    settings = request.app.state.settings
    return {"available": bool(settings.cloudflare_account_id and settings.cloudflare_api_token)}


@router.get("/ai/planner/history")
def history(
    response: Response, store: Store, conversation_id: UUID | None = None, before: int | None = None
):
    response.headers["Cache-Control"] = "private, no-store"
    return store.rpc(
        "read_ai_conversations",
        {"p_id": str(conversation_id) if conversation_id else None, "p_before": before},
    )


@router.get("/ai/planner/places")
def selected_options(
    response: Response, store: Store, source: Literal["favorite", "wish"], offset: int = 0
):
    response.headers["Cache-Control"] = "private, no-store"
    if not 0 <= offset <= 100000:
        raise HTTPException(422, "invalid_request")
    return place_options(store, source, offset)


@router.post("/ai/planner", response_model=SavedChatResult)
async def chat(body: ChatInput, request: Request, response: Response, store: Store):
    response.headers["Cache-Control"] = "private, no-store"
    settings = request.app.state.settings
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        raise HTTPException(503, "ai_not_configured")
    if body.messages[-1].role != "user":
        raise HTTPException(422, "ai_invalid_messages")
    if bool(body.conversation_id) != bool(body.request_id):
        raise HTTPException(422, "invalid_request")
    stats, budget = RunStats(PROMPT_VERSION), Budget()
    status = "ok"
    try:
        async with (
            httpx.AsyncClient(
                transport=ai_transport(request), trust_env=False, follow_redirects=False
            ) as external,
            httpx.AsyncClient(
                transport=ai_transport(request), trust_env=False, follow_redirects=False
            ) as database,
        ):
            scoped = AIStore(store, database, budget, stats)
            return await with_disconnect(
                _chat(body, settings, scoped, external, budget, stats), request, budget
            )
    except TimeoutError as error:
        status = "timeout"
        raise HTTPException(503, "ai_timeout") from error
    except HTTPException as error:
        status = error.status_code
        stats.error(error.detail)
        raise
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        stats.emit(status)


async def _chat(body, settings, store, client, budget, stats):
    lease = str(uuid4())
    acquired, finished = False, False
    try:
        latest = body.brief.message() if body.brief else body.messages[-1].content
        context, proposal = StoredContext(), body.proposal
        if body.conversation_id:
            with stats.span("context"):
                head = await store.rpc(
                    "begin_ai_planner_turn",
                    {
                        "p_id": str(body.conversation_id),
                        "p_request": str(body.request_id),
                        "p_version": body.version,
                        "p_user": latest,
                        "p_fingerprint": hashlib.sha256(
                            body.model_dump_json(
                                exclude={"brief"} if body.brief is None else set()
                            ).encode()
                        ).hexdigest(),
                        "p_lease": lease,
                    },
                )
            if head.get("replay"):
                turn = head["replay"]
                replay = dict(turn["result"])
                replay.setdefault("prompt_version", turn.get("prompt_version"))
                stats.counts["replayed"] = 1
                return SavedChatResult(
                    **replay, conversation_id=body.conversation_id, version=turn["version"]
                )
            acquired = True
            context = StoredContext.model_validate(head.get("context") or {})
            proposal = head.get("proposal") or proposal
            proposal = PlanContent.model_validate(proposal) if proposal else None
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        before_context = context.model_dump()
        if (
            context.intake
            and context.intake.pending
            and context.intake.turn_version != body.version
        ):
            before_context["intake"]["pending"] = None
        if context.activity_edit and context.activity_edit.turn_version != body.version:
            before_context["activity_edit"] = None
        if context.pending_fields and context.pending_fields.turn_version != body.version:
            before_context["pending_fields"] = None
        if context.dialogue.turn_version != body.version:
            # Opaque state can survive an older API writer; never resume a stale pending edit.
            before_context["dialogue"]["pending"] = None
        if proposal and not before_context.get("date") and not context.dialogue.cleared_date:
            before_context["date"] = proposal.date
        directive = (
            start_brief(body.brief, before_context)
            if body.brief
            else change_window(latest, before_context)
        )
        if not directive:
            if before_context.get("intake"):
                before_context["intake"]["pending"] = None
            directive = analyze(
                latest,
                before_context,
                proposal,
                body.chosen_places,
                today,
                selected=bool(body.selected_places),
            )
        recover_followup_area(directive, body.messages[:-1])
        directive.state.turn_version = body.version + 1
        if directive.slots.get("activity_edit"):
            directive.slots["activity_edit"]["turn_version"] = body.version + 1
        if directive.slots.get("pending_fields"):
            directive.slots["pending_fields"]["turn_version"] = body.version + 1
        if directive.slots.get("intake"):
            directive.slots["intake"]["turn_version"] = body.version + 1
        scope = directive.scope
        context = StoredContext.model_validate(merge_context(before_context, {}, directive))
        known_date = context.date
        policy = PlacePolicy(
            scope,
            "\n".join(m.content for m in body.messages[:-1] if m.role == "user") + "\n" + latest,
            rejected=directive.state.rejected_places,
            excluded=directive.state.excluded_kinds,
        )
        session = ToolSession(settings, store, body.selected_places, body.chosen_places, policy)
        session.previous_plan = proposal
        session.operation = directive.intent
        if body.brief:
            session.initial_activities = body.brief.activities
        if body.brief and not body.brief.recommend:
            session.activity_limit = len(body.brief.activities)
        session.append_only = bool(
            directive.state.append_pending and proposal and directive.intent in {"plan", "select"}
        )
        session.plan_updates = {
            k: v for k, v in directive.slots.items() if k in {"date", "budget", "transport"}
        }
        session.allowed_tools = set(directive.allowed_tools)
        if body.selected_places and directive.intent in {"search", "plan", "select"}:
            session.allowed_tools.add("lookup_selected_places")
            if not re.search(r"검색|찾아|주변|근처|다른|새로운|추가", latest):
                session.allowed_tools.discard("search_places")
            else:
                session.needs_place_search = True
            if body.brief and not body.brief.region:
                session.allowed_tools.discard("search_places")
                session.needs_place_search = False
        session.direct_final = not session.allowed_tools
        session.plan_date = known_date
        session.require_plan = bool(known_date and directive.intent in {"plan", "select"})
        if proposal:
            for activity in proposal.activities:
                if activity.place:
                    session.seed(activity)
        if (
            directive.intent == "select"
            and known_date
            and not proposal
            and (scope.single_activity or len(context.activities) <= 1)
        ):
            candidate = session.chosen_candidate
            if candidate:
                directive.plan = session.resolve(
                    ModelPlan(
                        title=f"{candidate.title} 코스"[:100],
                        date=known_date,
                        budget=context.budget,
                        transport=context.transport,
                        activities=[
                            {
                                "title": context.activities[0]
                                if context.activities
                                else candidate.title,
                                "place_ref": candidate.ref,
                            }
                        ],
                    )
                )
                directive.reply = "선택한 장소로 코스 초안을 정리했어요."
            else:
                directive.ask("target", "장소 이름을 다시 확인해 주세요.", resume="select")
        io = ToolIO(settings, client, store, budget, stats)
        await read_candidate_request(directive, session, io)
        stats.counts["tool_calls"] = session.calls
        if (
            not directive.reply
            and session.append_only
            and scope.exact_name
            and len(scope.kinds) == 1
            and not body.selected_places
            and not re.search(r"시간|\d시|\d:\d|비용|가격|예산|원|날짜|제목|교통|이동수단", latest)
        ):
            call = {
                "function": {
                    "name": "search_places",
                    "arguments": json.dumps(
                        {
                            "mode": "exact_name",
                            "name": scope.exact_name,
                            "query": scope.exact_name,
                            "kind": scope.kinds[0],
                            "area": scope.area,
                        },
                        ensure_ascii=False,
                    ),
                }
            }
            outcome = (await execute_batch(session, [call], io))[0]
            stats.counts["tool_calls"] = session.calls
            candidates = [c for c in session.visible_candidates() if c.ref in session.fresh_refs]
            existing = {a.place for a in proposal.activities}
            new_candidates = [c for c in candidates if c.destination not in existing]
            if len(candidates) == len(new_candidates) == 1 and len(proposal.activities) < 8:
                directive.plan = proposal.model_copy(deep=True)
                candidate = candidates[0]
                directive.plan.activities.append(
                    Activity(title=candidate.title, place=candidate.destination)
                )
                for name, value in session.plan_updates.items():
                    setattr(directive.plan, name, value)
                directive.plan = PlanContent.model_validate(directive.plan.model_dump())
                directive.reply = "지정한 장소를 확인해 기존 코스에 추가했어요."
            else:
                if outcome.get("error"):
                    directive.reply = "장소 검색을 완료하지 못했어요. 잠시 후 다시 시도해 주세요."
                elif candidates and not new_candidates:
                    directive.reply = "이미 코스에 포함된 장소예요. 기존 활동을 확인해 주세요."
                elif not candidates:
                    directive.reply = (
                        "지정한 이름과 일치하는 장소를 확인하지 못했어요. 이름을 확인해 주세요."
                    )
                else:
                    directive.reply = "추가할 장소 후보를 선택해 주세요. 활동은 최대 8개예요."
        if not directive.reply:
            messages = model_messages(
                SYSTEM, body, context, scope, directive, session, proposal, today, latest
            )
            if not await store.rpc("reserve_ai_planner_request"):
                raise HTTPException(429, "ai_rate_limited")
        if directive.reply:
            stats.counts["server_responses"] = 1
            answer = ChatResult(
                reply=directive.reply,
                plan=directive.plan,
                checks=check_course(directive.plan) if directive.plan else [],
                tools=session.reports,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
            )
        else:
            answer = await complete(
                settings, messages, session, client=client, budget=budget, stats=stats, io=io
            )
        if answer.plan and session.append_only:
            directive.state.append_pending = False
        if answer.plan and body.brief:
            # Explicit conditions override model defaults, including zero and unknown budget.
            answer.plan.date = body.brief.date
            answer.plan.budget = body.brief.budget
            answer.plan.transport = body.brief.transport
        answer.context = StoredContext.model_validate(
            merge_context(
                context.model_dump(), answer.context.model_dump(exclude_unset=True), directive
            )
        )
        if not answer.plan and proposal:
            answer.checks = list(dict.fromkeys(answer.checks + check_course(proposal)))
        answer.checks = list(
            dict.fromkeys(answer.checks + window_checks(answer.plan or proposal, context.intake))
        )[:16]
        candidates = session.visible_candidates()
        if body.conversation_id:
            with stats.span("persist"):
                saved = await store.rpc(
                    "finish_ai_planner_turn",
                    {
                        "p_id": str(body.conversation_id),
                        "p_request": str(body.request_id),
                        "p_lease": lease,
                        "p_version": body.version,
                        "p_user": latest,
                        "p_result": answer.model_dump(mode="json"),
                        "p_prompt": PROMPT_VERSION,
                    },
                )
            finished = True
            return SavedChatResult(
                **saved["result"],
                conversation_id=body.conversation_id,
                version=saved["version"],
                candidates=candidates,
            )
        return SavedChatResult(**answer.model_dump(), candidates=candidates)
    finally:
        # No business write after cancellation/deadline. Expiry recovers abandoned leases.
        if acquired and not finished and not asyncio.current_task().cancelling():
            try:
                async with asyncio.timeout(budget.remaining(1)):
                    await store.rpc(
                        "release_ai_planner_turn",
                        {
                            "p_id": str(body.conversation_id),
                            "p_request": str(body.request_id),
                            "p_lease": lease,
                        },
                    )
            except (HTTPException, TimeoutError, httpx.HTTPError):
                pass
