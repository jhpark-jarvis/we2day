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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from we2day_api.places import SearchInput, fetch_places
from we2day_api.plans import Activity, PlanContent


class SelectedPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["favorite", "wish"]
    id: UUID


class ChosenPlace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    address: str = Field(default="", max_length=180)


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


class ModelActivity(Activity):
    place_ref: str = Field(default="", max_length=40)


class ModelPlan(PlanContent):
    activities: list[ModelActivity] = Field(default_factory=list, max_length=8)


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


def fetch_weather(arguments: WeatherArguments) -> dict:
    target = date.fromisoformat(arguments.date)
    days = (target - datetime.now(ZoneInfo("Asia/Seoul")).date()).days
    if not 0 <= days <= 15:
        return {
            "error": "forecast_out_of_range",
            "notice": "오늘부터 15일 뒤까지만 예보 조회 가능.",
        }

    def get(client, url, params):
        with client.stream("GET", url, params=params) as response:
            if not response.is_success:
                raise HTTPException(503, "weather_unavailable")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 24000:
                    raise HTTPException(503, "weather_unavailable")
            return json.loads(raw)

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
    with httpx.Client(timeout=4, trust_env=False, follow_redirects=False) as client:
        geo = get(
            client,
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
        result = get(
            client,
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


def definition(name, description, arguments):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": arguments.model_json_schema(),
        },
    }


TOOLS = [
    definition(
        "get_weather",
        "한국 도시 일별 예보. 날씨 필요시만 사용. 구/주소 대신 시 이름(영문 권장).",
        WeatherArguments,
    ),
    definition(
        "search_places",
        "실제 장소 후보를 네이버 검색. 지역과 업종 포함. 영업상태/시간은 알 수 없음.",
        SearchInput,
    ),
    definition(
        "lookup_selected_places",
        "사용자가 이 요청에 명시 선택한 자주 가는 곳/위시만 읽기. 다른 DB 조회 불가.",
        EmptyArguments,
    ),
    definition(
        "validate_course",
        "제안 코스의 시간 순서·중복 장소·장소 누락 검사. 저장/확정하지 않음.",
        CheckArguments,
    ),
]


def clean(value: str, limit: int) -> str:
    value = html.unescape(re.sub(r"<[^>]*>", "", value))
    return " ".join("".join(c for c in value if ord(c) >= 32 and ord(c) != 127).split())[:limit]


def check_course(plan: PlanContent) -> list[str]:
    issues, seen, previous = [], set(), None
    for index, activity in enumerate(plan.activities, 1):
        if not activity.place.strip():
            issues.append(f"{index}번째 활동의 장소를 선택해 주세요.")
        else:
            key = re.sub(r"\s+", "", activity.place).casefold()
            if key in seen:
                issues.append(f"{index}번째 활동은 앞선 장소와 같아요.")
            seen.add(key)
        if activity.time:
            if previous and activity.time < previous:
                issues.append(f"{index}번째 활동 시간이 앞선 활동보다 빨라요.")
            previous = activity.time
    if not plan.activities:
        issues.append("활동을 추가해 주세요.")
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
    def __init__(self, settings, store, selected, chosen):
        self.settings, self.store, self.selected = settings, store, selected
        self.candidates: dict[str, Candidate] = {}
        self.reports: list[dict] = []
        self.searches: dict[str, list[dict]] = {}
        self.search_failures: set[str] = set()
        self.weather: list[WeatherSummary] = []
        self.weather_queries: dict[str, dict] = {}
        self.selected_result = None
        self.calls = 0
        for item in chosen:
            self.add(item.title, item.address, "user")

    def add(self, title, address, source):
        title, address = clean(title, 100), clean(address, 180)
        if not title:
            return None
        for candidate in self.candidates.values():
            if (candidate.title, candidate.address) == (title, address):
                return candidate
        ref = f"p{len(self.candidates) + 1}"
        candidate = Candidate(ref=ref, title=title, address=address, source=source)
        self.candidates[ref] = candidate
        return candidate

    def resolve(self, plan: ModelPlan) -> PlanContent:
        result = PlanContent.model_validate(plan.model_dump(exclude={"activities"}))
        for activity in plan.activities:
            content = activity.model_dump(exclude={"place_ref"})
            candidate = self.candidates.get(activity.place_ref)
            if candidate:
                # Canonical server evidence, never model-generated names/addresses/URLs.
                content["place"] = (
                    candidate.title + (f" · {candidate.address}" if candidate.address else "")
                )[:200]
            else:
                content["place"] = ""
            content["map_url"] = ""
            result.activities.append(Activity.model_validate(content))
        return result

    def execute(self, name: str, arguments) -> dict:
        self.calls += 1
        if self.calls > 8:
            return {"error": "tool_budget_exhausted"}
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
                result = fetch_weather(args)
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
                query = SearchInput.model_validate(arguments).query
                if query in self.searches:
                    if query in self.search_failures:
                        return {"error": "tool_unavailable"}
                    return {"items": self.searches[query]}
                if len(self.searches) >= 4:
                    return {"error": "search_budget_exhausted"}
                self.searches[query] = []
                results = fetch_places(self.settings, query)
                items = []
                for item in results.items:
                    candidate = self.add(item.title, item.roadAddress or item.address, "naver")
                    if candidate:
                        items.append(candidate.model_dump())
                self.searches[query] = items
                self.reports.append({"name": name, "status": "ok", "count": len(items)})
                return {"items": items, "notice": "검색 후보. 영업 여부/시간·이동시간은 미확인."}
            if name == "lookup_selected_places":
                EmptyArguments.model_validate(arguments)
                if self.selected_result is not None:
                    return {"items": self.selected_result}
                items = []
                for item in self.selected:
                    favorite = item.source == "favorite"
                    params = {
                        "id": f"eq.{item.id}",
                        "archived": "eq.false",
                        "limit": "1",
                        "select": "label,destination" if favorite else "title",
                    }
                    if not favorite:
                        params.update(kind="eq.place", done="eq.false")
                    rows = self.store.call(
                        "GET", "favorite_places" if favorite else "wishes", params=params
                    )
                    for row in rows:
                        candidate = self.add(
                            row.get("label", row.get("title", "")),
                            row.get("destination", ""),
                            "selected",
                        )
                        if candidate:
                            items.append(candidate.model_dump())
                self.selected_result = items
                self.reports.append({"name": name, "status": "ok", "count": len(items)})
                return {"items": items}
            if name == "validate_course":
                plan = CheckArguments.model_validate(arguments).plan
                issues = check_course(self.resolve(plan))
                self.reports.append({"name": name, "status": "ok", "count": len(issues)})
                return {"issues": issues, "saved": False}
            return {"error": "unknown_tool"}
        except (ValidationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            return {"error": "invalid_tool_arguments"}
        except httpx.HTTPError:
            self.reports.append({"name": name, "status": "failed", "count": 0})
            return {"error": "weather_unavailable"}
        except HTTPException as error:
            # Permission and provider exhaustion must not be hidden as empty successful searches.
            if error.status_code in (401, 403):
                raise
            self.reports.append({"name": name, "status": "failed", "count": 0})
            if name == "search_places":
                self.search_failures.add(query)
            return {
                "error": "tool_unavailable",
                "notice": "도구 실행 실패. 검색/조회를 완료했다고 말하지 마세요.",
            }
