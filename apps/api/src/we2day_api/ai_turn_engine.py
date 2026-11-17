"""Validated turn plan -> bounded executors -> one semantic state projection.

The legacy language interpreters must never be called from this path. Tool and
completion results are evidence, not additional instructions or condition patches.
"""

import copy
import json
from datetime import date

from fastapi import HTTPException

from we2day_api.ai_capabilities import QUESTIONS
from we2day_api.ai_capability_reads import read_plan
from we2day_api.ai_context import model_context
from we2day_api.ai_course_check import inspect_current_course
from we2day_api.ai_dialogue import DialogueState, Directive, PendingChange
from we2day_api.ai_edits import targets as reference_indices
from we2day_api.ai_intake import IntakeState, PlanningBrief, window_checks
from we2day_api.ai_place_answers import address_area, candidate_reply, private_anchor
from we2day_api.ai_place_policy import (
    LABELS,
    PlacePolicy,
    SearchScope,
    generic_name,
    kinds,
    norm,
    relational_area,
)
from we2day_api.ai_read_answers import join_replies, selected_reply, weather_reply
from we2day_api.ai_relevance import enrich_candidates
from we2day_api.ai_saved_schedule import ScheduleRead, read_schedule
from we2day_api.ai_search_spec import SearchSpec, SearchTarget, anchor_key, broad_goal, place_name
from we2day_api.ai_state import advance_context
from we2day_api.ai_tool_runtime import execute_batch
from we2day_api.ai_tools import PlanningContext, StoredContext, ToolSession, check_course
from we2day_api.ai_turn_contract import Delta, ReadTask, SearchTask, uncertain_fields
from we2day_api.ai_turn_selector import select_turn
from we2day_api.plans import Activity, PlanContent


def bind_continuation(plan, before, body, proposal=None):
    """Compile a typed resume against the existing task, never interpret text again."""
    if plan.operation != "resume":
        return plan
    if plan.act != "slot_answer":
        raise ValueError("Resume requires a slot answer")
    pending = before.get("turn_engine", {}).get("pending") or before.get("dialogue", {}).get(
        "pending"
    )
    if not pending:
        raise ValueError("No pending task to resume")
    field = pending["field"]
    supplied = plan.delta.model_dump(exclude_none=True, exclude={"evidence", "clear"})
    has_answer = field in supplied or field in plan.delta.clear
    has_answer |= field == "target" and bool(plan.searches or plan.delta.activities)
    has_answer |= field == "region" and bool(body.selected_places or body.chosen_places)
    has_answer |= field == "title" and plan.title is not None
    has_answer |= field == "activity_time" and bool(plan.activity_edits)
    if not has_answer:
        raise ValueError("Missing value for pending field")
    if field == "activity_time":
        ref = pending.get("target_ref", "")
        index = int(ref.split("_")[-1]) - 1 if ref else -1
        if (
            not proposal
            or index < 0
            or index >= len(proposal.activities)
            or anchor_key(proposal.activities[index]) != pending.get("target_key")
            or any(p.ref != ref for p in plan.activity_edits)
        ):
            raise ValueError("Pending activity changed; clarify the target again")
    result = plan.model_copy(deep=True)
    result.operation = pending["resume"]
    result.pending, result.ask = "resolve", ""
    if result.operation == "answer":
        # A query parameter is never a planning patch, including explicit clears.
        if (
            field == "date"
            and not plan.delta.date
            or field == "title"
            and plan.title is None
            or field not in {"date", "title"}
            or set(supplied) - {field}
            or plan.delta.clear
            or field != "title"
            and plan.title is not None
            or plan.activity_edits
            or plan.preparation is not None
            or plan.preferences.changed
            or plan.searches
        ):
            raise ValueError("Read answers cannot patch planning state")
        result.reads = [ReadTask.model_validate(r) for r in pending.get("reads", [])]
        for query in result.reads:
            if field == "date":
                query.date = plan.delta.date
            else:
                query.title = plan.title
        result.delta, result.title = Delta(), None
    elif not result.searches and result.operation in {"search", "plan"}:
        result.searches = [SearchTask.model_validate(s) for s in pending.get("searches", [])]
        if not result.searches and not pending.get("original_request"):
            stored = (before.get("place_search") or {}).get("targets", [])
            result.searches = [
                SearchTask(
                    target=t["query"],
                    kind=t["kind"],
                    category_retrieval=t.get("category_retrieval", False),
                )
                for t in stored
            ]
        if field == "target" and result.delta.activities:
            result.searches = activity_searches(result.delta.activities)
        if not result.searches and pending.get("original_request"):
            raise ValueError("Extract search tasks from pending original_request")
    if field == "region":
        for search in result.searches:
            # Substitute the newly supplied dependency, not its old unresolved placeholder.
            search.area = plan.delta.region or ""
            search.anchor_ref = ""
    return result


def activity_searches(activities):
    """Dependencies of an already-typed activity list, never free-text intent parsing."""
    if len(activities) > 4:
        raise ValueError("Search dependency budget exceeded")
    return [
        SearchTask(target=label, kind=detected[0] if len(detected := kinds(label)) == 1 else "any")
        for label in activities
    ]


def validate_effects(plan, body, before, proposal, today):
    """Pure semantic firewall. No IO or mutations, even for a rejected batch."""
    values = plan.delta.values(today)
    latest = body.messages[-1].content
    if values and not body.brief:
        # A literal region carries its own provenance; do not require the model to
        # duplicate that quote in a second field. Other changes still need evidence.
        intrinsic = (
            set(values) == {"region"}
            and plan.delta.region
            and norm(plan.delta.region) in norm(latest)
        )
        if not intrinsic and (
            not plan.delta.evidence or norm(plan.delta.evidence) not in norm(latest)
        ):
            raise ValueError("Ungrounded condition change")
        if plan.delta.region and norm(plan.delta.region) not in norm(latest):
            raise ValueError("Region must be explicit")
        if plan.delta.activities is not None and any(
            not norm(label) or norm(label) not in norm(latest)
            for label in plan.delta.activities
        ):
            raise ValueError("activities_must_quote_user_goals_not_edit_arguments")
    if plan.title is not None and norm(plan.title) not in norm(latest):
        raise ValueError("Title must be explicit")
    if (
        plan.operation == "edit"
        and not proposal
        and (plan.title is not None or plan.preparation is not None or plan.activity_edits)
    ):
        raise ValueError("No current proposal to edit")
    if plan.target_ref and (
        not proposal or int(plan.target_ref.split("_")[1]) > len(proposal.activities)
    ):
        raise ValueError("Invalid anchor reference")
    if plan.preferences.changed:
        if not plan.preferences.evidence or norm(plan.preferences.evidence) not in norm(latest):
            raise ValueError("Preference changes require latest user evidence")
        for name in [*plan.preferences.exclude_places, *plan.preferences.restore_places]:
            if norm(name) not in norm(latest):
                raise ValueError("Preference place names must be explicit")
        if set(plan.preferences.exclude_places) & set(plan.preferences.restore_places) or set(
            plan.preferences.exclude_kinds
        ) & set(plan.preferences.restore_kinds):
            raise ValueError("Conflicting preference changes")
        if any(
            k not in LABELS
            for k in [*plan.preferences.exclude_kinds, *plan.preferences.restore_kinds]
        ):
            raise ValueError("Preference category must be concrete")
    if any(p.operation == "move" for p in plan.activity_edits) and any(
        p.operation == "delete" for p in plan.activity_edits
    ):
        raise ValueError("Delete and move require separate unambiguous edits")
    refs = set()
    for edit in plan.activity_edits:
        index = int(edit.ref.split("_")[1]) - 1
        if index >= len(proposal.activities) or edit.ref in refs:
            raise ValueError("Invalid or duplicate activity reference")
        refs.add(edit.ref)
        if edit.operation == "shift":
            clock = proposal.activities[index].time
            if clock is None or edit.offset_minutes is None or edit.time is not None:
                raise ValueError("Time shift requires an existing time and offset")
            h, m = map(int, clock.split(":"))
            if not 0 <= h * 60 + m + edit.offset_minutes < 1440:
                raise ValueError("Time shift leaves the selected date")
        if edit.operation == "swap":
            target = int(edit.swap_with.split("_")[-1]) - 1 if edit.swap_with else -1
            if (
                target < 0
                or target >= len(proposal.activities)
                or target == index
                or len(plan.activity_edits) != 1
            ):
                raise ValueError("Swap requires one distinct valid target pair")
        if any(getattr(edit, key) is not None for key in edit.clear if key in {"time", "cost"}):
            raise ValueError("Conflicting activity effects")
        if edit.operation == "move" and (
            edit.to_index is None or edit.to_index >= len(proposal.activities)
        ):
            raise ValueError("Invalid destination index")
    allowed = latest + " " + " ".join(before.get("activities", []))
    pending = before.get("turn_engine", {}).get("pending") or {}
    allowed += " " + " ".join(s.get("target", "") for s in pending.get("searches", []))
    allowed += " " + pending.get("original_request", "")
    saved = before.get("place_search") or {}
    allowed += " " + " ".join(t.get("query", "") for t in saved.get("targets", []))
    if proposal:
        allowed += " " + " ".join(a.title + " " + a.place for a in proposal.activities)
    if body.brief:
        allowed += " " + " ".join(body.brief.activities)
    for task in plan.searches:
        query_area = task.area or plan.delta.region or before.get("region", "")
        if query_area and norm(task.target) == norm(query_area) and task.mode != "exact_name":
            raise ValueError("Search target must be an activity or venue, not the query area")
        if norm(task.target) not in norm(allowed):
            raise ValueError(
                "Unrequested exact venue"
                if task.mode == "exact_name"
                else "Search target must quote a permitted activity or venue"
            )
        detected = kinds(task.target)
        if len(detected) == 1 and task.kind not in {"any", detected[0]}:
            raise ValueError("Search kind conflicts with the quoted target")
        if task.anchor_ref and (
            not proposal or int(task.anchor_ref.split("_")[1]) > len(proposal.activities)
        ):
            raise ValueError("Invalid anchor reference")
        if task.area and norm(task.area) not in norm(
            allowed + " " + before.get("region", "") + " " + (plan.delta.region or "")
        ):
            raise ValueError("Ungrounded search area")
        if (
            "region" in uncertain_fields(before)
            and task.area
            and not (norm(task.area) in norm(latest) or plan.delta.region == task.area)
        ):
            raise ValueError("Legacy region requires confirmation")
        if task.category_retrieval and task.kind not in LABELS:
            raise ValueError("Category retrieval requires a concrete kind")
    if plan.selected and not body.selected_places:
        raise ValueError("No explicitly selected saved places")
    for task in plan.weather:
        date.fromisoformat(task.date)
        if norm(task.city) not in norm(latest + " " + before.get("region", "")):
            raise ValueError("Unrequested weather city")
    for task in plan.reads:
        if task.date:
            task.date.resolve(today)
    return values


def edit_proposal(proposal, plan, values):
    """Apply only typed edits; untouched fields/activities remain byte-equivalent."""
    result = proposal.model_copy(deep=True)
    for key in ("date", "budget", "transport"):
        if key in values:
            if key == "date" and values[key] is None:
                continue  # A stored plan requires a date; clear condition only.
            setattr(result, key, values[key])
    if plan.title is not None:
        result.title = plan.title
    if plan.preparation is not None:
        result.preparation = plan.preparation
    changes = {int(e.ref.split("_")[1]) - 1: e for e in plan.activity_edits}
    items = []
    moves = []
    for index, activity in enumerate(result.activities):
        patch = changes.get(index)
        if patch and patch.operation == "delete":
            continue
        if patch:
            content = activity.model_dump()
            content.update(patch.model_dump(include={"title", "time", "cost"}, exclude_none=True))
            if patch.operation == "shift":
                h, m = map(int, activity.time.split(":"))
                total = h * 60 + m + patch.offset_minutes
                content["time"] = f"{total // 60:02d}:{total % 60:02d}"
            for field in patch.clear:
                content[field] = "" if field == "place" else None
                if field == "place":
                    content["map_url"] = ""
            activity = Activity.model_validate(content)
            if patch.operation == "move":
                moves.append((activity, patch.to_index))
        items.append(activity)
    for activity, index in moves:
        items = [item for item in items if item is not activity]
        items.insert(index, activity)
    for patch in plan.activity_edits:
        if patch.operation == "swap":
            first, second = (int(ref.split("_")[-1]) - 1 for ref in (patch.ref, patch.swap_with))
            items[first], items[second] = items[second], items[first]
    result.activities = items
    return PlanContent.model_validate(result.model_dump())


def project(
    before,
    plan,
    values,
    version,
    *,
    pending=None,
    scope=None,
    spec=None,
    outcome=None,
    restored_places=(),
):
    """The ONLY semantic state writer. Versions advance even for pure side answers."""
    result = copy.deepcopy(before)
    result["dialogue"] = plan.preferences.apply(result.get("dialogue", {}), restored_places)
    result.update({k: v for k, v in values.items() if k in PlanningContext.model_fields})
    if before.get("intake") or any(k in values for k in ("start_time", "end_time")):
        data = copy.deepcopy((before.get("intake") or {}).get("data") or {})
        data.update({k: result[k] for k in PlanningContext.model_fields})
        data.update({k: values[k] for k in ("start_time", "end_time") if k in values})
        data["recommend"] = not bool(data.get("activities"))
        result["intake"] = IntakeState(
            data=PlanningBrief.model_validate(data), turn_version=version
        ).model_dump()
    if values:
        PlanningContext.model_validate({k: result[k] for k in PlanningContext.model_fields})
    engine = copy.deepcopy(result.get("turn_engine") or {})
    engine.update(version=1, basis=version)
    engine["unverified_fields"] = sorted(uncertain_fields(before) - set(values))
    if plan.operation == "cancel":
        engine["pending"] = None
        result.update(
            location_request=None, activity_edit=None, pending_fields=None, place_search=None
        )
        result["dialogue"].update(pending=None, append_pending=False)
    elif pending:
        result.update(location_request=None, activity_edit=None, pending_fields=None)
        engine["pending"] = pending
        result["dialogue"]["pending"] = PendingChange(
            field=pending["field"],
            resume="chat" if pending["resume"] == "answer" else pending["resume"],
        ).model_dump()
        if pending["field"] == "region" and pending["resume"] in {"search", "plan"}:
            result["location_request"] = {
                "version": 1,
                "basis": version,
                "operation": pending["resume"],
                "scope": (scope or SearchScope()).model_dump(),
                "search": spec.model_dump() if spec else None,
            }
    elif plan.pending == "resolve":
        engine["pending"] = None
        result.update(location_request=None, activity_edit=None, pending_fields=None)
        result["dialogue"]["pending"] = None
    # Side answers must not touch legacy pending controller semantics.
    if plan.operation != "answer":
        result["dialogue"]["intent"] = plan.operation if plan.operation != "cancel" else "chat"
        if scope:
            result["search_scope"] = scope.model_dump()
        if spec:
            result["place_search"] = spec.model_dump()
    if "date" in values:
        result["dialogue"]["cleared_date"] = values["date"] is None
    result["turn_engine"] = engine
    old = (before.get("control") or {}).get("last_action")
    if plan.operation == "cancel":
        old = None
    elif plan.operation in {"search", "plan"} and scope:
        old = {"operation": plan.operation, "scope": scope.model_dump()}
    result["control"] = {
        "version": 1,
        "basis": version,
        "last_action": old,
        "reason": "interpreted",
        "outcome": outcome or "not_requested",
        "selected_count": 0,
        "planned_tools": 0,
        "executed_tools": 0,
    }
    return StoredContext.model_validate(advance_context(result, version))


def compile_turn(plan, body, before, proposal, today):
    if plan.selected and not body.selected_places:
        # Model availability error, not caller authorization. No row can be read.
        raise ValueError("Selected places unavailable; use public searches or ask for selection")
    latest = body.brief.message() if body.brief else body.messages[-1].content
    if plan.operation in {"plan", "search"} and not body.brief:
        # Repeating an established value is not an effect. Do not demand a fresh
        # change quote for unchanged state echoed by the model. Explicit clears,
        # unverified fields and answers to pending queries retain their meaning.
        values = plan.delta.values(today)
        unverified = uncertain_fields(before)
        for key, value in values.items():
            if key not in plan.delta.clear and key not in unverified and before.get(key) == value:
                setattr(plan.delta, key, None)
    # Field-value normalization happens ONLY after a typed date operation was chosen.
    # It never classifies a sentence or creates a condition change from a question.
    dates = [q.date for q in plan.reads if q.date]
    if plan.delta.date:
        if not plan.delta.date.source:
            plan.delta.date = plan.delta.date.model_copy(update={"source": plan.delta.evidence})
        dates.append(plan.delta.date)
    if plan.query_date:
        if not plan.query_date.source:
            plan.query_date = plan.query_date.model_copy(update={"source": latest})
        dates.append(plan.query_date)
    for spec in dates:
        if spec.source and norm(spec.source) not in norm(latest):
            raise ValueError("Date source must quote latest user")
    plan = bind_continuation(plan, before, body, proposal)
    if plan.operation == "edit" and plan.searches:
        raise ValueError("Edit searches require a pending search task")
    if plan.operation == "plan" and not (
        plan.searches or body.selected_places or body.chosen_places or proposal
    ):
        # Capability prerequisites depend on already-typed task labels, not language rules.
        activities = (
            plan.delta.activities
            or before.get("activities")
            or (body.brief.activities if body.brief else [])
        )
        plan.searches = activity_searches(activities)
    pending = (before.get("turn_engine") or {}).get("pending") or {}
    reference_source = latest + " " + pending.get("original_request", "")
    indices, invalid = (
        reference_indices(reference_source, len(proposal.activities)) if proposal else ([], False)
    )
    for task in plan.searches:
        if not task.anchor_ref or not proposal:
            continue
        index = int(task.anchor_ref.split("_")[1]) - 1
        if not 0 <= index < len(proposal.activities):
            continue  # Invalid references are rejected by the firewall.
        name = place_name(proposal.activities[index])
        named = name and norm(name) in norm(reference_source)
        ordinal = not invalid and len(indices) == 1 and index in indices
        if not named and not ordinal:
            task.anchor_ref = ""  # Available data is not authorization to use an old anchor.
    for task in plan.searches:
        if broad_goal(task.target):
            # A verbal activity goal is a category query, not a venue identity.
            task.mode = "category"
            task.category_retrieval = task.kind in LABELS
        # Normalize structured argument values before the reused executor infers
        # a concrete kind. Approved query identity must use that same kind.
        if task.mode != "exact_name" and task.area:
            for suffix in ("", "에서", "에", "의"):
                prefix = task.area + suffix + " "
                if task.target.startswith(prefix):
                    task.target = task.target[len(prefix) :].strip()
                    break
        detected = kinds(task.target)
        if task.kind == "any" and len(detected) == 1:
            task.kind = detected[0]
        if task.mode == "exact_name" and generic_name(task.target):
            task.mode = "category"
    values = validate_effects(plan, body, before, proposal, today)
    if plan.operation == "edit" and not (
        plan.title is not None
        or plan.preparation is not None
        or plan.activity_edits
        or plan.preferences.changed
        or plan.delta.clear
        or any(k in uncertain_fields(before) or before.get(k) != v for k, v in values.items())
    ):
        raise ValueError("Edit has no changes; extract latest requested values or answer unchanged")
    if plan.operation == "edit" and proposal:
        edit_proposal(proposal, plan, values)  # Pure dry run before any tool.
    return plan


def verified_single_plan(session, tasks, working, body, proposal, plan_mode, changes=None):
    """No generation is needed for one unambiguous verified place with no extras.

    Never guess hours/costs or choose among multiple candidates. Complex routes,
    explicit preferences/windows, previous courses and saved choices keep the
    existing grounded completion path.
    """
    window = (working.get("intake") or {}).get("data") or {}
    if (
        proposal
        or plan_mode != "replace"
        or len(tasks) != 1
        or body.selected_places
        or body.chosen_places
        or working.get("requirements")
        or any(window.get(k) for k in ("start_time", "end_time"))
        or any((changes or {}).get(k) for k in ("start_time", "end_time", "requirements"))
        or body.brief
        and (body.brief.start_time or body.brief.end_time)
    ):
        return None
    candidates = session.visible_candidates()
    if len(candidates) != 1 or candidates[0].match != "direct":
        return None
    candidate = candidates[0]
    return PlanContent(
        title=tasks[0].target,
        date=working["date"],
        budget=working.get("budget"),
        transport=working.get("transport", ""),
        activities=[Activity(title=tasks[0].target, place=candidate.destination)],
    )


async def run_turn(body, before, proposal, today, settings, store, client, budget, stats, api):
    if not await store.rpc("reserve_ai_planner_request"):
        raise HTTPException(429, "ai_rate_limited")
    plan = await select_turn(
        body,
        before,
        proposal,
        today,
        settings,
        client,
        budget,
        stats,
        validate=lambda p: compile_turn(p, body, before, proposal, today),
    )
    values = plan.delta.values(today)
    if (
        plan.operation in {"search", "plan"}
        and "region" in uncertain_fields(before)
        and before.get("region")
        and any(
            task.area == before["region"]
            and norm(task.area) in norm(body.messages[-1].content)
            and not private_anchor(task.area)
            and not relational_area(task.area)
            for task in plan.searches
        )
    ):
        # A validated task explicitly confirms the existing legacy value. This
        # updates provenance, never substitutes a query's different planning area.
        values.setdefault("region", before["region"])
    if plan.operation == "plan" and not proposal and "region" not in values:
        areas = {task.area for task in plan.searches if task.area}
        if len(areas) == 1:
            explicit_area = next(iter(areas))
            if (
                norm(explicit_area) in norm(body.messages[-1].content)
                and not private_anchor(explicit_area)
                and not relational_area(explicit_area)
            ):
                values["region"] = explicit_area
    if body.brief:
        # Authored form is stronger than a model extraction, including explicit clears.
        values = body.brief.model_dump(include=set(PlanningContext.model_fields))
        values.update(start_time=body.brief.start_time, end_time=body.brief.end_time)
    region_value = values.get("region") or ""
    unresolved_alias = private_anchor(region_value)
    unresolved_region = unresolved_alias or relational_area(region_value)
    if unresolved_region:
        values.pop("region", None)
    working = {**before, **{k: v for k, v in values.items() if k in PlanningContext.model_fields}}
    restored_places = (
        [p.title for p in body.chosen_places]
        if plan.operation in {"search", "plan", "edit"}
        else []
    )
    working["dialogue"] = plan.preferences.apply(before.get("dialogue", {}), restored_places)
    # Validate time-window changes before tools, not after a partial execution.
    if any(k in values for k in ("start_time", "end_time")):
        window = {
            **((before.get("intake") or {}).get("data") or {}),
            **{k: working[k] for k in PlanningContext.model_fields},
            **{k: values[k] for k in ("start_time", "end_time") if k in values},
        }
        window["recommend"] = not bool(window.get("activities"))
        try:
            PlanningBrief.model_validate(window)
        except ValueError as error:
            raise HTTPException(502, "ai_selection_failed") from error
    area = working.get("region", "")
    if unresolved_region or "region" in uncertain_fields(before) and "region" not in values:
        area = ""
        working["region"] = ""
    scope = SearchScope(area=area, search_only=plan.operation == "search")
    # Each search owns its own exact-name/type policy; no stale scope inheritance.
    tasks = plan.searches
    spec = (
        SearchSpec(
            area=area,
            targets=[
                SearchTarget(query=s.target, kind=s.kind, category_retrieval=s.category_retrieval)
                for s in tasks
            ],
        )
        if tasks
        else None
    )
    session = ToolSession(settings, store, body.selected_places, body.chosen_places, PlacePolicy())
    session.previous_plan = proposal
    session.operation = plan.operation
    session.allowed_tools = {"lookup_selected_places", "get_weather", "search_places"}
    session.direct_final = True
    session.responses_api = True
    session.plan_date = working.get("date")
    session.plan_updates = {k: working.get(k) for k in ("budget", "transport")}
    if working.get("date"):
        session.plan_updates["date"] = working["date"]
    if proposal:
        for activity in proposal.activities:
            if activity.place:
                session.seed(activity)
    io = api.ToolIO(settings, client, store, budget, stats)
    replies, reports, extra_checks = [], [], []
    pending = None

    async def execute(name, arguments):
        calls = [{"function": {"name": name, "arguments": json.dumps(arguments)}}]
        with stats.span("tools"):
            result = (await execute_batch(session, calls, io))[0]
            if any(r.get("status") == "failed" for r in session.reports):
                raise HTTPException(503, "ai_tool_unavailable")
            return result

    if plan.selected or body.selected_places and plan.operation in {"search", "plan"}:
        await execute("lookup_selected_places", {})
        if plan.operation != "answer":
            restored_places.extend(c.title for c in session.selected_candidates())
            working["dialogue"] = plan.preferences.apply(
                before.get("dialogue", {}), restored_places
            )
        previous_pending = (before.get("turn_engine") or {}).get("pending") or (
            before.get("dialogue") or {}
        ).get("pending")
        if plan.act == "slot_answer" and previous_pending and previous_pending["field"] == "region":
            # A verified, explicitly selected row may answer location. Its label
            # alone never authorizes a lookup, and a URL is not a geocoded address.
            areas = {
                address_area(c.address, allow_road=True) for c in session.selected_candidates()
            } - {""}
            if len(areas) == 1:
                area = areas.pop()
                values["region"] = working["region"] = scope.area = area
                if spec:
                    spec.area = area
    if unresolved_region and not tasks and plan.operation == "edit":
        pending = {"field": "region", "resume": "edit", "searches": []}
        replies.append(QUESTIONS["region"])
    if plan.operation == "cancel":
        replies.append("진행 중인 요청을 취소했어요. 기존 조건과 코스 초안은 유지했어요.")
    if plan.operation == "clarify":
        pending = {
            "field": plan.ask,
            "resume": plan.resume,
            "searches": [t.model_dump() for t in tasks],
            "reads": [t.model_dump(mode="json") for t in plan.reads],
            "original_request": plan.request_source,
        }
        if plan.target_ref:
            pending["target_ref"] = plan.target_ref
            pending["target_key"] = anchor_key(
                proposal.activities[int(plan.target_ref.split("_")[1]) - 1]
            )
        replies.append(QUESTIONS.get(plan.ask, "어떤 조건을 바꿀까요?"))
    elif tasks:
        approved_queries = []
        for task in tasks:
            search_area = task.area or area
            unresolved_basis = unresolved_alias or private_anchor(search_area)
            if unresolved_basis or relational_area(search_area):
                search_area = ""
            explicit_area_now = (
                task.area
                and not relational_area(task.area)
                and norm(task.area) in norm(body.messages[-1].content)
            )
            if task.anchor_ref and not unresolved_basis and not explicit_area_now:
                anchor = proposal.activities[int(task.anchor_ref.split("_")[1]) - 1]
                search_area = anchor.place
            elif not search_area:
                anchors = [
                    c
                    for c in session.selected_candidates()
                    if session.selected_usage.get(c.ref) in {"anchor", "reference"}
                ]
                if len(anchors) == 1:
                    search_area = address_area(anchors[0].address, allow_road=True)
            if not search_area or search_area.startswith("https://"):
                pending = {
                    "field": "region",
                    "resume": plan.operation,
                    "searches": [t.model_dump() for t in tasks],
                }
                replies.append(QUESTIONS["region"])
                break
            exact = task.target if task.mode == "exact_name" else ""
            # An optional broad category must not erase a literal menu/service goal.
            category = task.category_retrieval and broad_goal(task.target)
            retrieval = LABELS[task.kind] if category else task.target
            scope = SearchScope(
                area=search_area,
                kinds=[task.kind] if task.kind != "any" else [],
                exact_name=exact,
                name_kind=task.kind,
                search_only=plan.operation == "search",
            )
            session.policy = PlacePolicy(
                scope,
                body.messages[-1].content,
                queries=[(task.kind, retrieval, task.target)],
                category_targets={(task.kind, task.target)} if category else (),
                excluded=working.get("dialogue", {}).get("excluded_kinds", []),
                rejected=working.get("dialogue", {}).get("rejected_places", []),
            )
            approved_queries.append((task.kind, retrieval, task.target))
            await execute(
                "search_places",
                {
                    "mode": task.mode,
                    "name": exact,
                    "query": retrieval,
                    "kind": task.kind,
                    "area": search_area,
                },
            )
        # Display all executed targets; per-search policy already filtered each candidate.
        scope = SearchScope(
            area=area,
            # Each task was already filtered independently. A general literal
            # task must not disappear behind a different task's concrete kind.
            kinds=[]
            if any(t.kind == "any" for t in tasks)
            else list(dict.fromkeys(t.kind for t in tasks)),
            search_only=plan.operation == "search",
        )
        session.policy = PlacePolicy(
            scope,
            queries=approved_queries,
            category_targets={
                (t.kind, t.target) for t in tasks if t.category_retrieval and broad_goal(t.target)
            },
            excluded=working.get("dialogue", {}).get("excluded_kinds", []),
            rejected=working.get("dialogue", {}).get("rejected_places", []),
        )
        # One optional relevance call; always reserve a call for requested plan generation.
        if any(t.category_retrieval and broad_goal(t.target) for t in tasks):
            reviewed = False
            if plan.operation == "search" or stats.counts["model_calls"] < 2:
                reviewed = await enrich_candidates(session, io)
            if (
                plan.operation == "search"
                and not reviewed
                and session.relevance_pool
                and not session.visible_candidates()
            ):
                # Unexamined provider results are not a verified empty search.
                # Preserve the request/state and expose the existing retry flow.
                raise HTTPException(502, "ai_selection_failed")
        if not pending and plan.operation == "search":
            replies.append(candidate_reply(session))
    for query in plan.weather:
        await execute("get_weather", query.model_dump())
    if plan.weather:
        replies.append(weather_reply(session.weather, []))
    for query in plan.reads if plan.operation != "clarify" else []:
        if query.name == "read_shared_calendar":
            target = query.date.resolve(today) if query.date else None
            if not target:
                pending = {
                    "field": "date",
                    "resume": "answer",
                    "searches": [],
                    "reads": [r.model_dump(mode="json") for r in plan.reads],
                }
            reply, receipt = await read_schedule(
                ScheduleRead(date=target) if target else ScheduleRead(question=QUESTIONS["date"]),
                store,
                stats,
            )
        else:
            reply, receipt = await read_plan(
                {"title": query.title, "plan_id": query.plan_id},
                body.messages[-1].content,
                before,
                body.version,
                today,
                store,
                stats,
            )
        replies.append(reply)
        reports.extend(receipt)
    if plan.inspect:
        reply, receipt = inspect_current_course(proposal)
        replies.append(reply)
        reports.extend(receipt)
    replacement = None
    if plan.operation == "edit" and not pending:
        preference_only = plan.preferences.changed and not (
            values or plan.title is not None or plan.preparation is not None or plan.activity_edits
        )
        replacement = (
            edit_proposal(proposal, plan, values) if proposal and not preference_only else None
        )
        replies.append(
            "검색에서 제외할 장소와 업종을 반영했어요."
            if preference_only
            else "요청한 항목만 코스 초안에 반영했어요."
            if proposal
            else "요청한 조건을 반영했어요."
        )
    elif plan.operation == "plan" and not pending:
        if not working.get("date"):
            pending = {
                "field": "date",
                "resume": "plan",
                "searches": [t.model_dump() for t in tasks],
            }
            replies.append(QUESTIONS["date"])
        elif (
            not tasks
            and not body.chosen_places
            and session.selected_candidates()
            and all(
                session.selected_usage.get(c.ref) == "anchor" for c in session.selected_candidates()
            )
        ):
            pending = {"field": "target", "resume": "plan", "searches": []}
            replies.append("선택한 장소를 기준으로 어떤 활동을 하고 싶나요?")
        elif (
            not session.candidates
            or tasks
            and any(not items for items in session.searches.values())
        ):
            replies.append(candidate_reply(session))
        else:
            session.require_plan = True
            session.append_only = plan.plan_mode == "append"
            if tasks:
                session.activity_limit = len(tasks)
                session.requested_activities = [t.target for t in tasks]
            if body.brief:
                session.initial_activities = body.brief.activities
                if not body.brief.recommend:
                    session.activity_limit = len(body.brief.activities)
            state = DialogueState(intent="plan")
            directive = Directive(state, scope, intent="plan")
            messages = [
                {"role": "system", "content": api.SYSTEM},
                {
                    "role": "user",
                    "content": model_context(
                        StoredContext.model_validate(working),
                        scope,
                        directive,
                        session,
                        len(body.selected_places),
                        today,
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "approved_operation": "plan",
                            "plan_mode": plan.plan_mode,
                            "activity_targets": [t.target for t in tasks],
                            "current_proposal": proposal.model_dump() if proposal else None,
                            "current_request": body.messages[-1].content,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            # No next tool loop: direct_final only permits a structured final answer.
            replacement = verified_single_plan(
                session, tasks, working, body, proposal, plan.plan_mode, values
            )
            if replacement is None:
                answer = await api.complete(
                    settings, messages, session, client=client, budget=budget, stats=stats, io=io
                )
                replacement = answer.plan
                extra_checks = answer.checks
            else:
                stats.counts["direct_verified_plans"] = 1
            replies.append(
                "코스 초안을 정리했어요. 장소와 시간을 확인해 주세요."
                if replacement
                else "코스 초안을 완성하지 못했어요. 확인 사항을 살펴봐 주세요."
            )
    if replacement is not None and plan.operation == "plan" and "activities" not in values:
        # A completed new course replaces the old activity goals too. Derive
        # only from the already validated course, never the model's context.
        values["activities"] = [activity.title for activity in replacement.activities]
    if plan.operation == "answer":
        if plan.answer == "date" and plan.query_date:
            resolved = plan.query_date.resolve(today)
            weekday = "월화수목금토일"[date.fromisoformat(resolved).weekday()]
            replies.insert(0, f"{resolved} ({weekday}요일)이에요.")
        elif plan.answer == "status":

            def display(key):
                value = working.get(key)
                if value is None or value == "" or value == []:
                    return "미정"
                if key == "budget":
                    return f"{value:,}원"
                if isinstance(value, list):
                    return " → ".join(value)
                return str(value)

            replies.insert(
                0,
                "정한 조건\n"
                + "\n".join(
                    f"• {label}: {display(key)}"
                    for key, label in (
                        ("date", "날짜"),
                        ("region", "지역"),
                        ("budget", "예산"),
                        ("transport", "이동수단"),
                        ("activities", "활동"),
                    )
                ),
            )
        elif plan.answer == "help":
            replies.insert(
                0,
                "장소 검색·코스 초안 작성/수정·공동 일정 조회·날씨 확인을 도와줘요. "
                "저장과 확정은 직접 눌러주세요.",
            )
        elif not replies:
            replies.append(plan.reply or "원하는 날짜·지역이나 활동을 알려주세요.")
    if plan.selected and not tasks and plan.operation != "plan":
        replies.append(selected_reply(session))
    reply = join_replies(replies) or "바꿀 조건이나 찾을 장소를 알려주세요."
    stats.stage("validate")
    outcome = session.resolution
    search_reports = [r for r in session.reports if r["name"] == "search_places"]
    if pending:
        outcome = "unresolved"
    elif search_reports:
        successful = sum(r.get("count", 0) > 0 for r in search_reports)
        failed = sum(r["status"] == "failed" for r in search_reports)
        outcome = (
            "partial"
            if (successful and (failed or successful < len(search_reports)))
            else "ready"
            if successful
            else "failed"
            if failed
            else "empty"
        )
    if pending:
        prior = (before.get("turn_engine") or {}).get("pending") or {}
        original = prior.get("original_request") if plan.act == "slot_answer" else None
        pending.setdefault("original_request", original or body.messages[-1].content)
    context = project(
        before,
        plan,
        values,
        body.version,
        pending=pending,
        scope=scope if tasks else None,
        spec=spec,
        outcome=outcome,
        restored_places=restored_places,
    )
    stats.counts.update(
        control_version=2,
        executed_tools=len(session.reports) + len(reports),
        tool_calls=session.calls,
        planned_tools=len(tasks) + len(plan.weather),
    )
    answer = api.ChatResult(
        reply=reply,
        plan=replacement,
        context=context,
        checks=list(
            dict.fromkeys(
                extra_checks
                + (check_course(replacement or proposal) if replacement or proposal else [])
                + window_checks(replacement or proposal, context.intake)
            )
        )[:16],
        tools=(reports + session.reports)[:9],
        weather=session.weather,
        prompt_version=api.PROMPT_VERSION,
        prompt_sha256=api.PROMPT_SHA256,
    )
    return answer, session.visible_candidates()
