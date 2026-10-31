"""Versioned location questions. Saved IDs remain explicit, request-local selections."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from we2day_api.ai_conversation_hints import guidance
from we2day_api.ai_dialogue import social_turn
from we2day_api.ai_place_answers import private_anchor
from we2day_api.ai_place_policy import SearchScope, explicit_area, kinds, relational_area
from we2day_api.ai_search_spec import SearchSpec, area_only_request


class LocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    basis: int = Field(ge=0)
    operation: Literal["search", "plan"] = "search"
    scope: SearchScope
    search: SearchSpec | None = None


def pending_location(context, version):
    try:
        value = LocationRequest.model_validate(context.get("location_request"))
        return value if value.basis == version else None
    except ValidationError:
        return None


def location_answer(text):
    """An answer supplies an area; it never claims to resolve/geocode a private alias."""
    labelled = re.fullmatch(r"(?:지역|동네)\s*:\s*(.{1,100})", text.strip())
    value = labelled[1] if labelled else text.strip()
    value = re.sub(r"[.!?？]+$", "", value).strip()
    value = re.sub(r"(?:이야|야|에서|으로|로|근처|주변)$", "", value).strip()
    if (
        not re.fullmatch(r"[가-힣A-Za-z0-9]+(?:\s+[가-힣A-Za-z0-9]+){0,4}", value)
        or len(value) > 100
        or private_anchor(value)
        or relational_area(value)
        or kinds(value)
        or re.search(r"모르|몰라|미정|아직|아무|어디|여기|거기|글쎄|없어|취소|해제", value)
        or not labelled
        and re.search(
            r"찾|검색|추천|알려|알아|보여|해줘|있나|있을까|없나|없을까|\d.*(?:원|시)", value
        )
    ):
        return ""
    return value


def resume_location(directive, body, before):
    pending = pending_location(before, body.version)
    if not pending:
        return False
    text = body.messages[-1].content.strip()
    if social_turn(text) or guidance(text):
        return False
    selected_answer = bool(body.selected_places) and bool(
        re.fullmatch(r"(?:선택한 장소|이곳)\s*주변에서\s*찾아줘[.!?\s]*", text)
    )
    if not selected_answer and (
        directive.intent in {"edit", "weather", "reject"}
        or re.search(r"날짜|예산|시간|제목|교통|이동수단", text)
    ):
        return False
    area = "" if selected_answer else location_answer(text)
    if not area and area_only_request(text):
        area = explicit_area(text)
    if not selected_answer and not area:
        if private_anchor(explicit_area(text)):
            return False
        if not re.search(r"찾|검색|추천|알아|보여|있나|있을까|없나|없을까", text):
            directive.scope = pending.scope.model_copy(deep=True)
            if pending.search:
                directive.slots["place_search"] = pending.search.model_dump()
            directive.ask(
                "region",
                "검색할 동네를 알려주거나 자주 가는 곳에서 기준 장소를 골라주세요.",
                resume=pending.operation,
            )
            return True
        return False
    scope = pending.scope.model_copy(deep=True)
    scope.area = area if area else pending.scope.area
    directive.scope = scope
    directive.intent = directive.state.intent = pending.operation
    directive.reply, directive.plan = "", None
    directive.state.pending = None
    directive.allowed_tools = {"search_places"}
    if selected_answer:
        directive.allowed_tools.add("lookup_selected_places")
    directive.slots.update(location_request=None, activity_edit=None, pending_fields=None)
    if area:
        directive.slots["region"] = area
    if pending.search:
        search = pending.search.model_copy(deep=True)
        search.area = scope.area
        search.anchor_index, search.anchor_key, search.anchor_pending = None, "", False
        directive.slots["place_search"] = search.model_dump()
    if pending.operation == "plan" and not before.get("date"):
        directive.ask("date", "어느 날짜의 코스로 정할까요? 날짜를 알려주세요.", resume="plan")
    return True


def project_location(result, before, directive, body, cancelled):
    """Persist only the requested task, not saved-record IDs or a list of private places."""
    pending = directive.state.pending
    if (
        not cancelled
        and pending
        and pending.field == "region"
        and pending.resume in {"search", "plan"}
    ):
        raw = result.get("place_search")
        try:
            search = SearchSpec.model_validate(raw) if raw else None
        except ValidationError:
            search = None
        result["location_request"] = LocationRequest(
            basis=body.version + 1,
            operation=pending.resume,
            scope=directive.scope,
            search=search,
        ).model_dump()
    elif not cancelled and directive.intent == "chat" and pending_location(before, body.version):
        value = pending_location(before, body.version)
        value.basis = body.version + 1
        result["location_request"] = value.model_dump()
    else:
        result["location_request"] = None
