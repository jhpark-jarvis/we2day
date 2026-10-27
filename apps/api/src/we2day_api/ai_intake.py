"""Typed first-turn user conditions. Never accepts model, permission or private state."""

import re
from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from we2day_api.ai_dialogue import DialogueState, Directive, clock_value, negative_kinds
from we2day_api.ai_place_policy import SearchScope, requested_scope

CLOCK = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class PlanningBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str | None = Field(default=None, pattern=r"^(20\d{2}|2100)-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, pattern=CLOCK)
    end_time: str | None = Field(default=None, pattern=CLOCK)
    region: str = Field(default="", max_length=100)
    transport: Literal["", "자동차", "대중교통", "도보"] = ""
    activities: list[str] = Field(default_factory=list, max_length=8)
    recommend: bool = False
    budget: int | None = Field(default=None, ge=0, le=1_000_000_000)
    requirements: str = Field(default="", max_length=300)

    @field_validator("date")
    @classmethod
    def calendar_date(cls, value):
        if value:
            Date.fromisoformat(value)
        return value

    @field_validator("region", "requirements")
    @classmethod
    def trim(cls, value):
        return value.strip()

    @field_validator("activities")
    @classmethod
    def activity_names(cls, values):
        if any(not v.strip() or len(v) > 60 for v in values):
            raise ValueError("Invalid activity")
        trimmed = [v.strip() for v in values]
        if len(set(trimmed)) != len(trimmed):
            raise ValueError("Duplicate activity")
        return trimmed

    @model_validator(mode="after")
    def complete(self):
        if bool(self.activities) == self.recommend:
            raise ValueError("Choose activities or request recommendations")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("End must follow start on the same day")
        return self

    def message(self):
        opening = (
            "입력한 조건으로 코스를 만들어줘."
            if self.date
            else "입력한 조건으로 장소 후보만 찾아줘. 날짜는 미정이야."
        )
        return "\n".join(
            [
                opening,
                f"날짜: {self.date or '미정'}",
                f"시간대: {self.start_time or '미정'} ~ {self.end_time or '미정'}",
                f"지역: {self.region or '직접 선택한 저장 장소'}",
                f"이동수단: {self.transport or '미정'}",
                f"활동: {' → '.join(self.activities) if self.activities else '자유롭게 추천'}",
                f"예산: {format(self.budget, ',') + '원' if self.budget is not None else '미정'}",
                f"추가 조건: {self.requirements or '없음'}",
            ]
        )


class IntakeState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    data: PlanningBrief
    pending: Literal["start_time", "end_time"] | None = None
    turn_version: int = Field(default=0, ge=0)


def start_brief(brief, context):
    state = DialogueState.model_validate(context.get("dialogue") or {}).model_copy(deep=True)
    state.pending, state.append_pending, state.cleared_date = None, False, brief.date is None
    state.excluded_kinds = sorted(negative_kinds(brief.requirements))
    scope = requested_scope(" ".join(brief.activities), SearchScope(area=brief.region))
    scope.search_only, scope.single_activity = brief.date is None, len(brief.activities) == 1
    intent = "plan" if brief.date else "search"
    result = Directive(state, scope, intent=intent, allowed_tools={"search_places"})
    result.slots.update(
        {
            key: getattr(brief, key)
            for key in ("date", "region", "transport", "budget", "activities", "requirements")
        }
    )
    result.slots["intake"] = IntakeState(data=brief).model_dump()
    if set(scope.kinds) & set(state.excluded_kinds):
        result.ask(
            "target", "선택한 활동과 피할 조건이 겹쳐요. 어느 활동을 남길까요?", resume=intent
        )
    state.intent = result.intent
    return result


def change_window(text, context):
    raw = context.get("intake")
    if not raw:
        return None
    stored = IntakeState.model_validate(raw).model_copy(deep=True)
    matched = re.search(r"(시작|종료|끝나는)\s*시간", text)
    if not matched and not stored.pending:
        return None
    multiple = len(re.findall(r"(시작|종료|끝나는)\s*시간", text)) > 1
    if multiple:
        stored.pending = None
        reply = "시작 시간 또는 종료 시간을 한 항목씩 알려주세요. 현재 시간대는 그대로 둘게요."
    elif stored.pending and re.fullmatch(r"\s*취소해?\s*줘?[.!?]?\s*", text):
        stored.pending = None
        reply = "시간대 변경을 취소했어요."
    else:
        if not matched and not re.fullmatch(r"[\d:시분\s오전후이야요.!?]+", text):
            return None
        target = (
            "start_time"
            if matched and matched[1] == "시작"
            else "end_time"
            if matched
            else stored.pending
        )
        clocks = re.findall(
            r"(?<!\d)\d{1,2}:\d{2}(?!\d)|(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?", text
        )
        values = [clock_value(token)[0] for token in clocks]
        clear = bool(matched and re.search(r"미정|없애|비워", text))
        value, question = (None, "") if clear else clock_value(text)
        if len(values) > 1 and (None in values or len(set(values)) > 1):
            question = "시간 하나를 알려주세요. 현재 시간대는 그대로 둘게요."
        stored.pending = target
        if question:
            reply = question
        else:
            candidate = stored.data.model_copy(deep=True)
            setattr(candidate, target, value)
            if (
                candidate.start_time
                and candidate.end_time
                and candidate.end_time <= candidate.start_time
            ):
                reply = "종료 시간은 시작 시간보다 늦어야 해요. 새 시간을 알려주세요."
            else:
                stored.data = PlanningBrief.model_validate(candidate.model_dump())
                stored.pending = None
                reply = "코스의 시간대를 수정했어요. 개별 활동 시간은 그대로 유지했어요."
    state = DialogueState.model_validate(context.get("dialogue") or {}).model_copy(deep=True)
    state.pending = None
    state.intent = "clarify" if stored.pending else "edit"
    directive = Directive(
        state,
        SearchScope.model_validate(context.get("search_scope") or {}),
        intent=state.intent,
        reply=reply,
    )
    directive.slots["intake"] = stored.model_dump()
    return directive


def window_checks(plan, stored):
    if not plan or not stored:
        return []
    data = stored.data
    result = []
    for index, activity in enumerate(plan.activities, 1):
        if activity.time and data.start_time and activity.time < data.start_time:
            result.append(f"{index}번째 활동이 정한 시작 시간 {data.start_time}보다 일러요.")
        if activity.time and data.end_time and activity.time > data.end_time:
            result.append(f"{index}번째 활동이 정한 종료 시간 {data.end_time}보다 늦어요.")
    return result[:16]
