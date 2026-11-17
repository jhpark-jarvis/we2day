"""Compact, effect-specific model outputs, compiled into the internal turn contract."""

from typing import Literal

from pydantic import Field

from we2day_api.ai_tools import WeatherArguments
from we2day_api.ai_turn_contract import (
    ActivityPatch,
    DateSpec,
    Delta,
    Preferences,
    ReadTask,
    SearchTask,
    Strict,
    TurnPlan,
)


class DateTurn(Strict):
    kind: Literal["date"]
    query_date: DateSpec


class StatusTurn(Strict):
    kind: Literal["status"]


class HelpTurn(Strict):
    kind: Literal["help"]


class ChatTurn(Strict):
    kind: Literal["chat"]
    reply: str = Field(min_length=1, max_length=1200)


class ReadTurn(Strict):
    kind: Literal["read"]
    reads: list[ReadTask] = Field(default_factory=list, max_length=2)
    weather: list[WeatherArguments] = Field(default_factory=list, max_length=2)
    selected: bool = False
    inspect: bool = False


class SearchTurn(Strict):
    preferences: Preferences = Field(default_factory=Preferences)
    kind: Literal["search"]
    searches: list[SearchTask] = Field(min_length=1, max_length=4)
    delta: Delta = Field(default_factory=Delta)
    reads: list[ReadTask] = Field(default_factory=list, max_length=2)
    weather: list[WeatherArguments] = Field(default_factory=list, max_length=2)
    selected: bool = False
    inspect: bool = False
    pending: Literal["preserve", "resolve"] = "preserve"


class PlanTurn(Strict):
    preferences: Preferences = Field(default_factory=Preferences)
    kind: Literal["plan"]
    searches: list[SearchTask] = Field(default_factory=list, max_length=4)
    delta: Delta = Field(default_factory=Delta)
    selected: bool = False
    plan_mode: Literal["replace", "append"] = "replace"
    reads: list[ReadTask] = Field(default_factory=list, max_length=2)
    weather: list[WeatherArguments] = Field(default_factory=list, max_length=2)
    inspect: bool = False
    pending: Literal["preserve", "resolve"] = "preserve"


class EditTurn(Strict):
    preferences: Preferences = Field(default_factory=Preferences)
    kind: Literal["edit"]
    searches: list[SearchTask] = Field(default_factory=list, max_length=4)
    delta: Delta = Field(default_factory=Delta)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    preparation: list[str] | None = Field(default=None, max_length=20)
    activity_edits: list[ActivityPatch] = Field(
        default_factory=list,
        max_length=20,
        description="Patches to existing timeline activities by ref. Time-only changes go here "
        "as {ref, operation:update, time:HH:mm}; never put these arguments in delta.activities.",
    )
    pending: Literal["preserve", "resolve"] = "preserve"
    suppress_resume: bool = Field(
        default=False,
        description="True ONLY if user explicitly says not to resume the previous task.",
    )


class ResumeTurn(Strict):
    preferences: Preferences = Field(default_factory=Preferences)
    kind: Literal["resume"]
    searches: list[SearchTask] = Field(default_factory=list, max_length=4)
    delta: Delta = Field(default_factory=Delta)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    activity_edits: list[ActivityPatch] = Field(default_factory=list, max_length=20)
    selected: bool = False


class ClarifyTurn(Strict):
    kind: Literal["clarify"]
    target_ref: str = Field(default="", pattern=r"^(?:activity_(?:[1-9]|1[0-9]|20))?$")
    ask: Literal["date", "region", "target", "title", "budget", "transport", "activity_time"]
    resume: Literal["search", "plan", "edit", "answer"]
    searches: list[SearchTask] = Field(default_factory=list, max_length=4)
    reads: list[ReadTask] = Field(default_factory=list, max_length=2)
    delta: Delta = Field(default_factory=Delta)


class CancelTurn(Strict):
    kind: Literal["cancel"]


class WireTurn(Strict):
    decision: (
        DateTurn
        | StatusTurn
        | HelpTurn
        | ChatTurn
        | ReadTurn
        | SearchTurn
        | PlanTurn
        | EditTurn
        | ResumeTurn
        | ClarifyTurn
        | CancelTurn
    )


KINDS = {
    "date": DateTurn,
    "status": StatusTurn,
    "help": HelpTurn,
    "chat": ChatTurn,
    "read": ReadTurn,
    "search": SearchTurn,
    "plan": PlanTurn,
    "edit": EditTurn,
    "resume": ResumeTurn,
    "clarify": ClarifyTurn,
    "cancel": CancelTurn,
}


def decode_turn(value, *, request_source=""):
    if not isinstance(value, dict) or set(value) != {"decision"}:
        raise ValueError("Invalid decision envelope")
    item = value["decision"]
    if not isinstance(item, dict) or item.get("kind") not in KINDS:
        raise ValueError("Unknown decision kind")
    kind = item["kind"]
    payload = KINDS[kind].model_validate(item).model_dump(exclude={"kind"})
    if kind in {"date", "status", "help", "chat", "read"}:
        return TurnPlan.model_validate(
            {
                "act": "social" if kind == "chat" else "information",
                "operation": "answer",
                "answer": kind if kind in {"date", "status", "help"} else "conversation",
                **payload,
            }
        )
    return TurnPlan.model_validate(
        {
            "act": "slot_answer" if kind == "resume" else "request",
            "operation": kind,
            "request_source": request_source if kind == "clarify" else "",
            "pending": "resolve" if kind in {"resume", "cancel"} else "preserve",
            **payload,
        }
    )
