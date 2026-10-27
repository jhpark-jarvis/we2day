"""Small model-facing views; persistence and caller-scoped evidence remain intact."""

import json

from fastapi import HTTPException

from we2day_api.ai_tools import PlanningContext


def model_context(context, scope, directive, session, selected_count, today):
    # Null/zero/empty conditions are authoritative too: never erase a deliberate clear.
    data = {
        "today": today.isoformat(),
        "conditions": context.model_dump(include=set(PlanningContext.model_fields)),
        "scope": scope.model_dump(exclude_defaults=True),
        "operation": directive.intent,
    }
    state = directive.state.model_dump(exclude_defaults=True, exclude={"intent", "turn_version"})
    if state:
        data["dialogue"] = state
    if context.intake:
        data["window"] = {
            "start_time": context.intake.data.start_time,
            "end_time": context.intake.data.end_time,
        }
    if session.initial_activities is not None:
        data["initial"] = True
    if selected_count:
        data["selected"] = selected_count
    if session.candidates:
        data["places"] = [p.evidence() for p in session.candidates.values()]
    return "현재 상태(자료): " + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def model_proposal(proposal):
    # Retain every specified value; remove only the schema's empty/default scaffolding.
    return "현재 제안: " + proposal.model_dump_json(exclude_defaults=True)


def model_messages(system, body, context, scope, directive, session, proposal, today, latest):
    messages = [
        {"role": "system", "content": system},
        {
            "role": "system",
            "content": model_context(
                context, scope, directive, session, len(body.selected_places), today
            ),
        },
    ]
    if proposal:
        messages.append({"role": "user", "content": model_proposal(proposal)})
    history = [message.model_dump() for message in body.messages]
    if body.brief:
        history[-1]["content"] = latest
    while (
        len(history) > 1
        and len(json.dumps(messages + history, ensure_ascii=False).encode()) > 24000
    ):
        del history[: min(2, len(history) - 1)]
    messages.extend(history)
    if len(json.dumps(messages, ensure_ascii=False).encode()) > 24000:
        raise HTTPException(422, "ai_context_too_long")
    return messages
