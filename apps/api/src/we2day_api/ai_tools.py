"""Read-only, caller-scoped AI tools. Provider results are request-local evidence."""

import html
import json
import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_serializer,
)

from we2day_api.ai_capabilities import definitions
from we2day_api.ai_dialogue import DialogueState
from we2day_api.ai_edits import ActivityEdit, PendingFields
from we2day_api.ai_intake import IntakeState
from we2day_api.ai_place_policy import PlacePolicy, SearchArguments, SearchScope, kinds, source_kind
from we2day_api.places import fetch_places, straight_line_m
from we2day_api.plans import Activity, PlanContent


class SelectedPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["favorite", "wish"]
    id: UUID
    usage: Literal["reference", "anchor", "include"] = "reference"

    @model_serializer(mode="wrap")
    def legacy_reference(self, handler):
        value = handler(self)
        if self.usage == "reference":
            value.pop("usage", None)
        return value


class ChosenPlace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    address: str = Field(default="", max_length=180)
    destination: str = Field(default="", max_length=200)


class PlanningContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str | None = Field(default=None, pattern=r"^(20\d{2}|2100)-\d{2}-\d{2}$")
    region: str = Field(default="", max_length=100)
    transport: str = Field(default="", max_length=40)
    budget: int | None = Field(default=None, ge=0, le=1_000_000_000)
    activities: list[str] = Field(default_factory=list, max_length=8)
    requirements: str = Field(default="", max_length=300)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value

    @field_validator("activities")
    @classmethod
    def valid_activities(cls, values):
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("Invalid activities")
        return values


class Candidate(ChosenPlace):
    ref: str = Field(max_length=40)
    source: Literal["naver", "selected", "user"]
    match: Literal["direct", "related"] = "direct"

    def evidence(self):
        # Canonical destination is server-only resolution data, duplicated in title/address.
        return self.model_dump(exclude={"destination"})


class ModelActivity(Activity):
    place_ref: str = Field(default="", max_length=40)
    clear_place: bool = False


class ModelPlan(PlanContent):
    activities: list[ModelActivity] = Field(default_factory=list, max_length=8)


class StoredContext(PlanningContext):
    # Trusted owner-scoped stored data; opaque future fields survive a version rollback.
    model_config = ConfigDict(extra="allow", strict=True)
    search_scope: SearchScope = Field(default_factory=SearchScope)
    dialogue: DialogueState = Field(default_factory=DialogueState)
    activity_edit: ActivityEdit | None = None
    pending_fields: PendingFields | None = None
    intake: IntakeState | None = None


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str = Field(min_length=1, max_length=4000)
    plan: ModelPlan | None = None
    context: PlanningContext | None = None


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan: ModelPlan


class WeatherArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    city: str = Field(min_length=2, max_length=40, pattern=r"^[가-힣a-zA-Z -]+$")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class WeatherSummary(BaseModel):
    city: str = Field(max_length=100)
    date: str
    min_celsius: float | None = Field(default=None, ge=-100, le=70)
    max_celsius: float | None = Field(default=None, ge=-100, le=70)
    rain_probability_percent: float | None = Field(default=None, ge=0, le=100)


def weather_requests(arguments: WeatherArguments):
    target = date.fromisoformat(arguments.date)
    days = (target - datetime.now(ZoneInfo("Asia/Seoul")).date()).days
    if not 0 <= days <= 15:
        return {
            "error": "forecast_out_of_range",
            "notice": "오늘부터 15일 뒤까지만 예보 조회 가능.",
        }

    # GeoNames does not index every Korean alias; use public names, never guessed coordinates.
    aliases = {
        "서울": "Seoul",
        "부산": "Busan",
        "인천": "Incheon",
        "대구": "Daegu",
        "대전": "Daejeon",
        "광주": "Gwangju",
        "울산": "Ulsan",
        "세종": "Sejong",
        "수원": "Suwon",
        "의정부": "Uijeongbu",
        "양주": "Yangju",
        "남양주": "Namyangju",
        "성남": "Seongnam",
        "고양": "Goyang",
        "용인": "Yongin",
        "춘천": "Chuncheon",
        "강릉": "Gangneung",
        "속초": "Sokcho",
        "청주": "Cheongju",
        "전주": "Jeonju",
        "목포": "Mokpo",
        "여수": "Yeosu",
        "경주": "Gyeongju",
        "포항": "Pohang",
        "창원": "Changwon",
        "제주": "Jeju",
        "서귀포": "Seogwipo",
        "구리": "Guri",
    }
    city_name = re.sub(r"(?:특별자치시|특별시|광역시|시)$", "", arguments.city.strip())
    query = aliases.get(city_name, arguments.city)
    # Public city lookup only; no arbitrary URLs, user JWT, provider keys or house coordinates.
    geo = yield (
        "https://geocoding-api.open-meteo.com/v1/search",
        {
            "name": query,
            "countryCode": "KR",
            "language": "ko",
            "count": 5,
        },
    )
    cities = [c for c in geo.get("results", []) if c.get("country_code") == "KR"]
    if not cities:
        return {
            "error": "city_not_found",
            "notice": "시/군 이름을 확인해 주세요. 주소 검색이 아닙니다.",
        }
    city = cities[0]
    latitude, longitude = float(city["latitude"]), float(city["longitude"])
    if not (32 <= latitude <= 40 and 124 <= longitude <= 133):
        raise ValueError("Invalid city coordinates")
    result = yield (
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": arguments.date,
            "end_date": arguments.date,
            "timezone": "Asia/Seoul",
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max",
        },
    )
    daily = result["daily"]
    if daily["time"] != [arguments.date]:
        raise ValueError("Invalid forecast date")
    summary = WeatherSummary(
        city=clean(city["name"], 100),
        date=arguments.date,
        min_celsius=daily["temperature_2m_min"][0],
        max_celsius=daily["temperature_2m_max"][0],
        rain_probability_percent=daily["precipitation_probability_max"][0],
    )
    return {
        "forecast": summary.model_dump(),
        "notice": "도시 대표 지점 일별 예보이며 확정 날씨가 아님.",
        "source": "https://open-meteo.com/",
        "license": "CC BY 4.0",
    }


def fetch_weather(arguments: WeatherArguments) -> dict:
    steps = weather_requests(arguments)
    try:
        action = next(steps)
        with httpx.Client(timeout=4, trust_env=False, follow_redirects=False) as client:
            while True:
                with client.stream("GET", action[0], params=action[1]) as response:
                    if not response.is_success:
                        raise HTTPException(503, "weather_unavailable")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 24000:
                            raise HTTPException(503, "weather_unavailable")
                action = steps.send(json.loads(raw))
    except StopIteration as done:
        return done.value


TOOLS = definitions(
    {
        "get_weather": WeatherArguments,
        "search_places": SearchArguments,
        "lookup_selected_places": EmptyArguments,
    }
)


def clean(value: str, limit: int) -> str:
    value = html.unescape(re.sub(r"<[^>]*>", "", value))
    return " ".join("".join(c for c in value if ord(c) >= 32 and ord(c) != 127).split())[:limit]


def course_summary(plan: PlanContent) -> dict:
    costs = [a.cost for a in plan.activities if a.cost is not None]
    total = sum(costs)
    unknown = len(plan.activities) - len(costs)
    return {
        "known_cost_total": total if costs else None,
        "known_cost_count": len(costs),
        "unknown_cost_count": unknown,
        "cost_complete": bool(plan.activities) and not unknown,
        "over_budget": bool(costs) and plan.budget is not None and total > plan.budget,
        "within_budget": (
            total <= plan.budget
            if plan.activities and not unknown and plan.budget is not None
            else None
        ),
        "untimed_activity_count": sum(a.time is None for a in plan.activities),
        "travel_time_verified": False,
        "stay_time_verified": False,
    }


def check_course(plan: PlanContent) -> list[str]:
    issues, seen, previous, times = [], set(), None, {}
    for index, activity in enumerate(plan.activities, 1):
        if not activity.place.strip():
            issues.append(f"{index}번째 활동의 장소를 선택해 주세요.")
        else:
            # Keep punctuation/address/branch identity; collapse formatting only.
            key = re.sub(r"\s+", "", clean(activity.place, 200)).casefold()
            if key in seen:
                issues.append(f"{index}번째 활동은 앞선 장소와 같아요.")
            seen.add(key)
        if activity.time:
            if activity.time in times:
                issues.append(
                    f"{index}번째 활동은 {times[activity.time]}번째 활동과 같은 시각이에요."
                )
            times.setdefault(activity.time, index)
            if previous and activity.time < previous:
                issues.append(f"{index}번째 활동 시간이 앞선 활동보다 빨라요.")
            previous = activity.time
    if not plan.activities:
        issues.append("활동을 추가해 주세요.")
    summary = course_summary(plan)
    if summary["over_budget"]:
        issues.append(
            f"입력한 활동비 합계 {summary['known_cost_total']:,}원이 "
            f"전체 예산 {plan.budget:,}원을 넘어요."
        )
    if summary["known_cost_count"] and summary["unknown_cost_count"]:
        issues.append(
            f"확인된 활동비는 {summary['known_cost_total']:,}원이며, "
            f"{summary['unknown_cost_count']}개 활동의 비용은 미정이에요."
        )
    return issues[:16]


def place_options(store, source: str, offset: int = 0):
    table = "favorite_places" if source == "favorite" else "wishes"
    params = {
        "select": "id,label,destination" if source == "favorite" else "id,title",
        "archived": "eq.false",
        "order": "id.asc",
        "limit": "50",
        "offset": str(offset),
    }
    if source == "wish":
        params.update(kind="eq.place", done="eq.false")
    rows = store.call("GET", table, params=params)
    return [
        {
            "source": source,
            "id": row["id"],
            "title": row.get("label", row.get("title", "")),
            "address": row.get("destination", ""),
        }
        for row in rows
    ]


class ToolSession:
    def __init__(self, settings, store, selected, chosen, policy=None):
        self.settings, self.store, self.selected = settings, store, selected
        self.policy = policy or PlacePolicy()
        self.candidate_kinds = {}
        self.previous_plan = None
        self.direct_final = False
        self.require_plan = False
        self.plan_date = None
        self.operation = None
        self.allowed_tools = None
        self.append_only = False
        self.plan_updates = {}
        self.needs_place_search = False
        self.candidates: dict[str, Candidate] = {}
        self.coordinates: dict[str, tuple[float, float]] = {}
        self.ambiguous_coordinates: set[str] = set()
        self.reports: list[dict] = []
        self.searches: dict[str, list[dict]] = {}
        self.search_reports: dict[str, dict] = {}
        self.search_failures: set[str] = set()
        self.weather: list[WeatherSummary] = []
        self.weather_queries: dict[str, dict] = {}
        self.selected_result = None
        self.selected_usage: dict[str, str] = {}
        self.resolution = "not_requested"
        self.calls = 0
        self.previous_places: dict[str, list[Candidate]] = {}
        self.chosen_candidate = None
        self.fresh_refs: set[str] = set()
        self.relevance_pool: list[tuple] = []
        self.relevance_attempted = False
        self.activity_limit: int | None = None
        self.initial_activities: list[str] | None = None
        self.requested_activities: list[str] | None = None
        for item in chosen:
            self.chosen_candidate = self.add(item.title, item.address, "user", item.destination)

    def add(self, title, address, source, destination="", *, coordinates=None):
        title, address = clean(title, 100), clean(address, 180)
        if not title:
            return None
        matches = [
            c
            for c in self.candidates.values()
            if (re.sub(r"\s+", "", c.title).casefold(), c.address.casefold())
            == (re.sub(r"\s+", "", title).casefold(), address.casefold())
        ]
        compatible = [
            c
            for c in matches
            if coordinates is None
            or c.ref not in self.coordinates
            or straight_line_m(self.coordinates[c.ref], coordinates) <= 25
        ]
        # Conflicting coordinates at the same name/address are ambiguous branches.
        if len(compatible) == 1:
            candidate = compatible[0]
            if coordinates is not None:
                self.coordinates.setdefault(candidate.ref, coordinates)
            return candidate
        ref = f"p{len(self.candidates) + 1}"
        if not destination:
            if source == "selected":
                destination = address or title
            else:
                # Match the existing editor/map handoff contract: name (address).
                postal = re.sub(r"\([^)]*\)", "", address).strip()[: max(0, 197 - len(title))]
                destination = f"{title} ({postal})" if postal else title
        candidate = Candidate(
            ref=ref,
            title=title,
            address=address,
            source=source,
            destination=clean(destination, 200),
        )
        self.candidates[ref] = candidate
        if coordinates is not None:
            self.coordinates[ref] = coordinates
        return candidate

    def ordered(self, candidates):
        anchors = [
            c for c in self.candidates.values() if self.selected_usage.get(c.ref) == "anchor"
        ]
        activity = getattr(self, "search_anchor", None)
        if not anchors and activity:
            anchors = [c for c in self.candidates.values() if c.destination == activity.place]
        if (
            len(anchors) != 1
            or anchors[0].ref not in self.coordinates
            or anchors[0].ref in self.ambiguous_coordinates
        ):
            return list(candidates)
        origin = self.coordinates[anchors[0].ref]
        if any(
            c.title == anchors[0].title
            and c.address == anchors[0].address
            and c.ref in self.coordinates
            and straight_line_m(origin, self.coordinates[c.ref]) > 25
            for c in self.candidates.values()
        ):
            return list(candidates)
        # Direct evidence always precedes unverified suggestions; unknown distances
        # retain provider order after known distances within the same evidence tier.
        return sorted(
            candidates,
            key=lambda c: (
                c.match == "related",
                c.ref not in self.coordinates,
                straight_line_m(origin, self.coordinates[c.ref])
                if c.ref in self.coordinates
                else 0,
            ),
        )

    def observe_coordinates(self, item):
        # An excluded anchor must stay excluded from candidates, yet its provider
        # coordinates may resolve an already explicit, exact name/address match.
        if item.coordinates is None:
            return
        identity = clean(item.title, 100), clean(item.roadAddress or item.address, 180)
        matches = [c for c in self.candidates.values() if (c.title, c.address) == identity]
        if len(matches) != 1:
            return
        ref = matches[0].ref
        if (
            ref in self.coordinates
            and straight_line_m(self.coordinates[ref], item.coordinates) > 25
        ):
            self.ambiguous_coordinates.add(ref)
        else:
            self.coordinates.setdefault(ref, item.coordinates)

    def order_search_results(self):
        for rows in self.searches.values():
            ordered = self.ordered([self.candidates[r["ref"]] for r in rows])
            order = {c.ref: index for index, c in enumerate(ordered)}
            rows.sort(key=lambda row: order[row["ref"]])

    def seed(self, activity):
        place = activity.place
        if activity.map_url:
            candidate = self.add(place or activity.title, "", "user", activity.map_url)
        elif " · " in place:
            title, address = place.split(" · ", 1)
            candidate = self.add(title, address, "user")
        else:
            selected = re.fullmatch(r"(.+?)\s+\(([^()]*)\)", place)
            candidate = (
                self.add(selected[1], selected[2], "user", place)
                if selected
                else self.add(activity.title, place, "user", place)
            )
        if candidate:
            self.previous_places.setdefault(activity.title, []).append(candidate)
        return candidate

    def resolve(self, plan: ModelPlan) -> PlanContent:
        result = PlanContent.model_validate(plan.model_dump(exclude={"activities"}))
        for activity in plan.activities:
            content = activity.model_dump(exclude={"place_ref", "clear_place"})
            candidate = None if activity.clear_place else self.candidates.get(activity.place_ref)
            if not candidate and not activity.clear_place:
                matches = [
                    c
                    for c in self.candidates.values()
                    if activity.place and activity.place in (c.destination, c.title)
                ]
                if len(matches) == 1:
                    candidate = matches[0]
                elif not activity.place and not activity.place_ref:
                    previous = self.previous_places.get(activity.title, [])
                    if len(previous) == 1:
                        candidate = previous[0]
            if candidate:
                if candidate.match == "related":
                    candidate = None
            if candidate:
                # Canonical server evidence, never model-generated names/addresses/URLs.
                content["place"] = candidate.destination
            else:
                content["place"] = ""
            content["map_url"] = ""
            if candidate and re.fullmatch(
                r"https://naver\.me/[A-Za-z0-9_-]{1,80}", candidate.destination
            ):
                content["map_url"] = candidate.destination
                content["place"] = candidate.title
            result.activities.append(Activity.model_validate(content))
        return result

    def visible_candidates(self):
        visible = []
        for item in self.candidates.values():
            if item.ref not in self.fresh_refs:
                continue
            if self.operation == "search" and self.selected_usage.get(item.ref) == "anchor":
                continue
            detected = kinds(item.title)
            kind = self.candidate_kinds.get(item.ref, detected[0] if len(detected) == 1 else "any")
            if self.policy.accepts(item.title, kind):
                visible.append(item)
        return self.ordered(visible)

    def selected_candidates(self):
        # Identity deduplication may reuse a current-course or freshly chosen
        # candidate. Explicit selection is a request-local role, not its origin.
        return [c for c in self.candidates.values() if c.ref in self.selected_usage]

    def guard_plan(self, model_plan, resolved):
        scope = self.policy.scope
        if self.operation in {"search", "reject", "clarify", "chat", "weather"}:
            return None, ["요청하지 않은 코스 변경은 반영하지 않았어요."] if resolved else []
        if scope.search_only:
            return None, ["지금은 장소 후보만 확인하고 있어요."]
        if not resolved:
            return resolved, []
        if any(
            c.match == "related"
            and (
                c.ref in {a.place_ref for a in model_plan.activities}
                or any(a.place in {c.title, c.destination} for a in resolved.activities)
            )
            for c in self.candidates.values()
        ):
            return None, ["조건 확인이 필요한 후보는 직접 선택한 뒤 코스에 반영해 주세요."]
        used = {a.place_ref for a in model_plan.activities}
        included = {ref for ref, usage in self.selected_usage.items() if usage == "include"}
        anchors = {ref for ref, usage in self.selected_usage.items() if usage == "anchor"}
        if included - used:
            return None, ["코스에 포함한 장소가 빠져 있어요. 선택한 장소를 확인해 주세요."]
        if anchors & used:
            return None, ["주변 기준점은 방문지로 자동 추가하지 않았어요."]
        if self.activity_limit and (
            len(resolved.activities) != self.activity_limit
            or any(not a.place for a in resolved.activities)
        ):
            return None, ["선택한 활동에 맞는 장소를 모두 확인한 뒤 코스에 반영할 수 있어요."]
        if scope.single_activity and len(resolved.activities) > 1:
            return None, ["요청한 활동 개수를 넘는 제안은 반영하지 않았어요."]
        previous = self.previous_plan.activities if self.previous_plan else []
        requested_order = self.requested_activities or self.initial_activities
        for index, (model, activity) in enumerate(
            zip(model_plan.activities, resolved.activities, strict=True)
        ):
            candidate = self.candidates.get(model.place_ref)
            detected = kinds(activity.title)
            actual_kind = self.candidate_kinds.get(
                model.place_ref, detected[0] if len(detected) == 1 else "any"
            )
            if requested_order:
                expected = kinds(requested_order[index])
                if expected and actual_kind not in expected:
                    return None, ["선택한 활동 순서와 맞지 않는 제안은 반영하지 않았어요."]
            if self.policy.forbidden(
                candidate.title if candidate else re.split(r"\s+\(", activity.place)[0], actual_kind
            ):
                return None, ["제외한 장소나 활동은 새 제안에 반영하지 않았어요."]
            if self.append_only and any(
                activity.place and (activity.place, activity.map_url) == (old.place, old.map_url)
                for old in previous
            ):
                continue
            if any(
                (activity.title, activity.place, activity.map_url)
                == (old.title, old.place, old.map_url)
                for old in previous
            ):
                continue
            candidate = self.candidates.get(model.place_ref)
            if not candidate and activity.place:
                candidate = next(
                    (c for c in self.candidates.values() if c.destination == activity.place), None
                )
            detected = kinds(activity.title)
            kind = self.candidate_kinds.get(
                candidate.ref if candidate else model.place_ref,
                detected[0] if len(detected) == 1 else "any",
            )
            if scope.kinds and (
                kind not in scope.kinds or any(k not in scope.kinds for k in detected)
            ):
                return None, ["요청한 활동 범위 밖의 제안은 반영하지 않았어요."]
            if candidate and not self.policy.accepts(candidate.title, kind):
                return None, ["요청한 장소와 다른 제안은 반영하지 않았어요."]
            if not candidate and scope.exact_name and scope.name_kind in {"any", kind}:
                return None, ["요청한 정확한 장소를 확인한 뒤 코스에 반영할 수 있어요."]
        if self.initial_activities is not None:
            # A time window is not an activity timestamp or a provider price quote.
            for activity in resolved.activities:
                activity.time, activity.cost = None, None
        if self.previous_plan is None:
            # Punctuation-only model padding is not a preparation item. Preserve user plans.
            resolved.preparation = [p for p in resolved.preparation if re.search(r"\w", p)]
        for name, value in self.plan_updates.items():
            setattr(resolved, name, value)
        resolved = PlanContent.model_validate(resolved.model_dump())
        return resolved, []

    def execute(self, name: str, arguments) -> dict:
        steps = self._execute_steps(name, arguments)
        try:
            action = next(steps)
            while True:
                try:
                    if action[0] == "places":
                        result = fetch_places(self.settings, action[1])
                    elif action[0] == "weather":
                        result = fetch_weather(action[1])
                    else:
                        result = self.store.call("GET", action[1], params=action[2])
                except Exception as error:
                    action = steps.throw(error)
                else:
                    action = steps.send(result)
        except StopIteration as done:
            self.order_search_results()
            return done.value

    def _execute_steps(self, name: str, arguments):
        self.calls += 1
        if self.calls > 8:
            self.resolution = "budget_exhausted"
            return {"error": "tool_budget_exhausted"}
        if self.allowed_tools is not None and name not in self.allowed_tools:
            self.resolution = "not_allowed"
            return {"error": "tool_not_allowed_for_current_request"}
        try:
            if isinstance(arguments, str):
                if len(arguments.encode()) > 12000:
                    raise ValueError("Arguments too large")
                arguments = json.loads(arguments)
            if name == "get_weather":
                args = WeatherArguments.model_validate(arguments)
                key = args.model_dump_json()
                if key in self.weather_queries:
                    return self.weather_queries[key]
                if len(self.weather_queries) >= 2:
                    return {"error": "weather_budget_exhausted"}
                self.weather_queries[key] = {"error": "weather_unavailable"}
                result = yield ("weather", args)
                self.weather_queries[key] = result
                if result.get("forecast"):
                    self.weather.append(WeatherSummary.model_validate(result["forecast"]))
                self.reports.append(
                    {
                        "name": name,
                        "status": "ok" if result.get("forecast") else "failed",
                        "count": int(bool(result.get("forecast"))),
                    }
                )
                return result
            if name == "search_places":
                args, denied = self.policy.prepare(
                    arguments, [item.address for item in self.candidates.values()]
                )
                if denied:
                    self.resolution = "not_allowed"
                    return {"error": denied, "notice": "현재 사용자 요청 범위에 맞게 검색하세요."}
                query = args.model_dump_json()
                if query in self.searches:
                    if query in self.search_failures:
                        return {"error": "tool_unavailable"}
                    return {"items": self.searches[query]}
                if len(self.searches) >= 4:
                    self.resolution = "budget_exhausted"
                    return {"error": "search_budget_exhausted"}
                self.searches[query] = []
                results = yield ("places", args.query)
                items = []
                for item in results.items:
                    self.observe_coordinates(item)
                    if not self.policy.relevant(item, args):
                        if args.mode != "exact_name" and self.policy.eligible(item, args):
                            self.relevance_pool.append((query, args, item))
                        continue
                    candidate = self.add(
                        item.title,
                        item.roadAddress or item.address,
                        "naver",
                        coordinates=item.coordinates,
                    )
                    if candidate:
                        self.fresh_refs.add(candidate.ref)
                        actual = source_kind(item.category)
                        self.candidate_kinds[candidate.ref] = (
                            actual if actual != "any" else args.kind
                        )
                        if not any(row["ref"] == candidate.ref for row in items):
                            items.append(candidate.evidence())
                self.searches[query] = items
                report = {"name": name, "status": "ok", "count": len(items)}
                self.reports.append(report)
                self.search_reports[query] = report
                return {
                    "items": items,
                    "notice": "관련 이름/업종/지역으로 거른 후보. 영업/시간·이동시간 미확인.",
                }
            if name == "lookup_selected_places":
                EmptyArguments.model_validate(arguments)
                if self.selected_result is not None:
                    return {"items": self.selected_result}
                items, rows_by_id = [], {}
                for source in ("favorite", "wish"):
                    ids = list(
                        dict.fromkeys(
                            str(item.id) for item in self.selected if item.source == source
                        )
                    )
                    if not ids:
                        continue
                    favorite = source == "favorite"
                    params = {
                        "id": "in.(" + ",".join(ids) + ")",
                        "archived": "eq.false",
                        "limit": str(len(ids)),
                        "select": "id,label,destination" if favorite else "id,title",
                    }
                    if not favorite:
                        params.update(kind="eq.place", done="eq.false")
                    rows = yield ("data", "favorite_places" if favorite else "wishes", params)
                    for row in rows:
                        if row.get("id") in ids:
                            rows_by_id[(source, row["id"])] = row
                for item in self.selected:
                    row = rows_by_id.get((item.source, str(item.id)))
                    if row:
                        candidate = self.add(
                            row.get("label", row.get("title", "")),
                            row.get("destination", ""),
                            "selected",
                        )
                        if candidate and candidate.evidence() not in items:
                            self.fresh_refs.add(candidate.ref)
                            self.selected_usage[candidate.ref] = item.usage
                            items.append(candidate.evidence())
                self.selected_result = items
                self.reports.append({"name": name, "status": "ok", "count": len(items)})
                return {"items": items}
            if name == "validate_course":
                plan = CheckArguments.model_validate(arguments).plan
                issues = check_course(self.resolve(plan))
                self.reports.append({"name": name, "status": "ok", "count": len(issues)})
                return {
                    "issues": issues,
                    "summary": course_summary(self.resolve(plan)),
                    "saved": False,
                }
            return {"error": "unknown_tool"}
        except (ValidationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            self.resolution = "invalid_arguments"
            return {"error": "invalid_tool_arguments"}
        except httpx.HTTPError:
            self.reports.append({"name": name, "status": "failed", "count": 0})
            self.resolution = "failed"
            if name == "search_places":
                self.search_failures.add(query)
            return {
                "error": "tool_unavailable" if name == "search_places" else "weather_unavailable"
            }
        except HTTPException as error:
            # Permission and provider exhaustion must not be hidden as empty successful searches.
            if error.status_code in (401, 403):
                raise
            self.reports.append({"name": name, "status": "failed", "count": 0})
            self.resolution = "failed"
            if name == "search_places":
                self.search_failures.add(query)
            return {
                "error": "tool_unavailable",
                "notice": "도구 실행 실패. 검색/조회를 완료했다고 말하지 마세요.",
            }
