"""One semantic decision per turn. No sentence classifiers or mutable directives here."""

import copy
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from we2day_api.ai_place_policy import Kind, norm
from we2day_api.ai_tools import PlanningContext, WeatherArguments


def uncertain_fields(context):
    """Legacy free-text region has no trusted extraction provenance. Confirm once.

    Do not guess whether a sentence 'looks like' a place, and do not erase owner data.
    Explicit new deltas/forms may establish provenance; side questions cannot.
    """
    engine = context.get("turn_engine")
    if engine is not None:
        return set(engine.get("unverified_fields", []))
    return {"region"} if context.get("region") else set()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DateSpec(Strict):
    mode: Literal["absolute", "offset", "weekday"]
    value: str = Field(default="", max_length=10)
    days: int = Field(default=0, ge=-366, le=366)
    weekday: int = Field(default=0, ge=0, le=6)
    weeks: int = Field(default=0, ge=-52, le=52)
    source: str = Field(
        default="", max_length=500, description="Exact date phrase quoted from latest user."
    )

    def resolve(self, today):
        if self.source:
            from we2day_api.ai_dialogue import date_value

            parsed, question = date_value(self.source, today)
            if question:
                raise ValueError("Ambiguous date value")
            if parsed:
                result = date.fromisoformat(parsed)
                if not 2000 <= result.year <= 2100:
                    raise ValueError("Date out of range")
                return result.isoformat()
        if self.mode == "absolute":
            result = date.fromisoformat(self.value)
        elif self.mode == "offset":
            result = today + timedelta(days=self.days)
        else:
            result = today + timedelta(days=self.weekday - today.weekday() + self.weeks * 7)
        if not 2000 <= result.year <= 2100:
            raise ValueError("Date out of range")
        return result.isoformat()


Condition = Literal[
    "date", "region", "budget", "transport", "activities", "requirements", "start_time", "end_time"
]


class Delta(Strict):
    evidence: str = Field(default="", max_length=500)
    date: DateSpec | None = Field(
        default=None,
        description="A newly requested planning date; null preserves the current date.",
    )
    region: str | None = Field(default=None, max_length=100)
    budget: int | None = Field(default=None, ge=0, le=1_000_000_000)
    transport: Literal["자동차", "대중교통", "도보"] | None = None
    activities: list[str] | None = Field(
        default=None,
        max_length=8,
        description="New requested activity labels quoted from the user's words. Null preserves "
        "the current goals. NEVER activity refs, times, field names or serialized edit arguments; "
        "changing an existing activity uses activity_edits instead.",
    )
    requirements: str | None = Field(default=None, max_length=300)
    start_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    clear: list[Condition] = Field(default_factory=list, max_length=8)

    def values(self, today):
        values = self.model_dump(exclude={"evidence", "clear"}, exclude_none=True)
        if self.date:
            values["date"] = self.date.resolve(today)
        if set(values) & set(self.clear):
            raise ValueError("Conflicting effects")
        defaults = PlanningContext().model_dump()
        defaults.update(start_time=None, end_time=None)
        values.update({key: defaults[key] for key in self.clear})
        PlanningContext.model_validate(
            {k: v for k, v in values.items() if k in PlanningContext.model_fields}
        )
        return values


class SearchTask(Strict):
    target: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[가-힣A-Za-z0-9 ]+$",
        description="Exact original activity or venue phrase from user/current permitted goals. "
        "Never translate, paraphrase, combine spellings or replace it with a category label.",
    )
    kind: Kind = "any"
    mode: Literal["category", "exact_name"] = Field(
        default="category",
        description=(
            "category for any activity, facility type, food or service keyword, kept verbatim; "
            "exact_name only for a specific venue proper name provided by the user"
        ),
    )
    area: str = Field(default="", max_length=100)
    anchor_ref: str = Field(default="", pattern=r"^(?:activity_(?:[1-9]|1[0-9]|20))?$")
    category_retrieval: bool = False


class ReadTask(Strict):
    name: Literal["read_shared_calendar", "read_shared_plan"]
    date: DateSpec | None = None
    title: str = Field(default="", max_length=100)
    plan_id: str = Field(default="", max_length=36, pattern=r"^(?:[0-9a-fA-F-]{36})?$")


class Preferences(Strict):
    evidence: str = Field(default="", max_length=500)
    exclude_places: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=24
    )
    restore_places: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=24
    )
    exclude_kinds: list[Kind] = Field(default_factory=list, max_length=8)
    restore_kinds: list[Kind] = Field(default_factory=list, max_length=8)

    @property
    def changed(self):
        return bool(
            self.exclude_places or self.restore_places or self.exclude_kinds or self.restore_kinds
        )

    def apply(self, dialogue, restored=()):
        result = copy.deepcopy(dialogue)
        if not self.changed and not restored:
            return result
        for key, added, removed, maximum in (
            ("rejected_places", self.exclude_places, [*self.restore_places, *restored], 24),
            ("excluded_kinds", self.exclude_kinds, self.restore_kinds, 8),
        ):
            denied = {norm(v) for v in removed}
            values = [v for v in result.get(key, []) if norm(v) not in denied]
            for value in added:
                if norm(value) not in {norm(v) for v in values}:
                    values.append(value)
            result[key] = values[-maximum:]
        return result


class ActivityPatch(Strict):
    ref: str = Field(pattern=r"^activity_(?:[1-9]|1[0-9]|20)$")
    operation: Literal["update", "delete", "move", "shift", "swap"] = "update"
    offset_minutes: int | None = Field(default=None, ge=-1439, le=1439)
    swap_with: str = Field(default="", pattern=r"^(?:activity_(?:[1-9]|1[0-9]|20))?$")
    to_index: int | None = Field(default=None, ge=0, le=19)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    cost: int | None = Field(default=None, ge=0, le=1_000_000_000)
    clear: list[Literal["time", "cost", "place"]] = Field(default_factory=list, max_length=3)


class TurnPlan(Strict):
    version: Literal[1] = 1
    act: Literal["information", "request", "slot_answer", "social"]
    operation: Literal["answer", "search", "plan", "edit", "clarify", "cancel", "resume"] = Field(
        description="answer for facts; search for candidates; plan for generation; "
        "edit for explicit patches; clarify ONLY when information is missing; "
        "resume for an answer to the open pending question."
    )
    answer: Literal["conversation", "date", "status", "help"] = "conversation"
    reply: str = Field(default="", max_length=1200)
    query_date: DateSpec | None = Field(
        default=None,
        description="Required for answer=date; DateSpec object with mode, never an ISO string.",
    )
    delta: Delta = Field(default_factory=Delta)
    searches: list[SearchTask] = Field(
        default_factory=list,
        max_length=4,
        description="Actual required place searches. For a NEW plan without chosen/selected "
        "place evidence, this must not be empty. Preserve correct searches during schema repair.",
    )
    weather: list[WeatherArguments] = Field(default_factory=list, max_length=2)
    reads: list[ReadTask] = Field(default_factory=list, max_length=2)
    selected: bool = False
    inspect: bool = False
    pending: Literal["preserve", "resolve"] = "preserve"
    ask: Literal[
        "", "date", "region", "target", "title", "budget", "transport", "activity_time"
    ] = ""
    resume: Literal["search", "plan", "edit", "answer"] = "search"
    title: str | None = Field(default=None, min_length=1, max_length=100)
    preparation: list[str] | None = Field(default=None, max_length=20)
    activity_edits: list[ActivityPatch] = Field(default_factory=list, max_length=20)
    plan_mode: Literal["replace", "append"] = "replace"
    preferences: Preferences = Field(default_factory=Preferences)
    suppress_resume: bool = False
    target_ref: str = Field(default="", pattern=r"^(?:activity_(?:[1-9]|1[0-9]|20))?$")
    request_source: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def effects(self):
        changed = (
            bool(self.delta.model_dump(exclude_defaults=True, exclude={"evidence"}))
            or self.preferences.changed
        )
        edited = self.title is not None or self.preparation is not None or self.activity_edits
        if self.act in {"information", "social"} and (
            changed or edited or self.pending != "preserve" or self.operation != "answer"
        ):
            raise ValueError("Information cannot change planning state")
        if self.operation == "answer" and (changed or edited or self.searches):
            raise ValueError("Answer cannot change conditions or search")
        if self.answer == "date" and self.operation == "answer" and not self.query_date:
            raise ValueError("Date answers require query_date with DateSpec mode")
        if edited and self.operation not in {"edit", "resume"}:
            raise ValueError("Only edits may patch the proposal")
        if self.act == "slot_answer" and self.operation != "resume":
            raise ValueError("Slot answers require operation=resume; server binds the pending task")
        if self.searches and self.operation not in {"search", "plan", "clarify", "resume", "edit"}:
            raise ValueError("Search requires a search/planning task")
        if self.operation == "clarify" and self.ask == "activity_time" and not self.target_ref:
            raise ValueError("Activity clarification requires a target reference")
        if self.operation == "clarify" and not self.ask:
            raise ValueError("Clarification requires its field")
        if (
            self.operation == "clarify"
            and self.ask == "region"
            and self.resume == "search"
            and not self.searches
            and not self.delta.activities
            and not self.request_source
        ):
            raise ValueError("Location clarification must retain original search targets")
        if self.operation == "cancel" and (
            changed
            or edited
            or self.searches
            or self.reads
            or self.weather
            or self.selected
            or self.inspect
        ):
            raise ValueError("Cancellation cannot execute other effects")
        if len(self.searches) + len(self.weather) + len(self.reads) + self.inspect > 4:
            raise ValueError("Task budget exceeded")
        return self
