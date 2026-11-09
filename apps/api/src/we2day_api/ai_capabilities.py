"""Static capability contracts. Caller data and authorization are never cached here."""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from we2day_api.ai_search_spec import CategoryHint
from we2day_api.ai_wire import compact_schema


class CalendarReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str = Field(
        default="",
        max_length=10,
        pattern=r"^(?:20\d{2}-\d{2}-\d{2}|2100-\d{2}-\d{2})?$",
        description="입력의 resolved_request_date를 복사. 날짜 미정이면 빈 값.",
    )


class PlanReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_id: str = Field(default="", max_length=36, pattern=r"^(?:[0-9a-fA-F-]{36})?$")
    title: str = Field(
        default="",
        max_length=100,
        description="저장 플랜의 순수 제목만. 이라고/라는/라고 등 조사와 요청 표현 제외.",
    )
    date: str = Field(
        default="",
        max_length=10,
        pattern=r"^(?:20\d{2}-\d{2}-\d{2}|2100-\d{2}-\d{2})?$",
        description="현재 요청에서 날짜도 직접 지정한 경우만. 제목만 지정하면 빈 값.",
    )


class ClarifyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: Literal["date", "region", "target", "selection", "unsupported", "save"]
    targets: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="지역 재질문 시 원래 장소·음식·시설 명사구. 다른 질문은 빈 배열.",
    )


class CourseProposalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["plan"] = "plan"
    area: str = Field(default="", max_length=100)
    targets: list[str] = Field(
        default_factory=list, max_length=4, description="활동 명사구만. 날짜·조사·요청 동사 제외."
    )
    category_hints: list[CategoryHint] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    description: str
    effect: Literal["read", "proposal", "control", "check"]
    view: Literal["server_only", "public", "selected", "current"]
    executor: Literal["schedule", "plan", "session", "planner", "clarify", "check"]
    selected_required: bool = False
    exposed: bool = True


CAPABILITIES = (
    Capability(
        "calendar.read",
        "read_shared_calendar",
        "저장된 공동 약속/코스 조회·브리핑. 오늘 뭐 잡혀 있어/어디 가기로 했지 등. "
        "date는 YYYY-MM-DD, 모르면 빈 값. 개인 일정 제외, 새 코스 제안과 구분. "
        "장소 검색도 함께 요청했으면 search_places도 별도 호출.",
        "read",
        "server_only",
        "schedule",
    ),
    Capability(
        "plan.read",
        "read_shared_plan",
        "사용자가 정확한 제목 또는 ID를 명시한 저장 플랜 읽기. 모호하면 빈 값으로 질문. "
        "오늘 코스 등 날짜 조회는 read_shared_calendar, 편집중 제안은 continue_planning.",
        "read",
        "server_only",
        "plan",
    ),
    Capability(
        "places.search",
        "search_places",
        "장소 후보 검색. exact_name은 사용자 고유 이름(name), category/nearby는 "
        "모든 원문 목표를 targets 배열로 전달, query는 첫 목표. "
        "업종kind(분류 없으면 any)·사용자가 알려준 지역area. "
        "현재 활동 주변 검색도 이 도구: anchor_ref에 해당 활동ref, 지역 모르면 빈값. 영업 미확인.",
        "read",
        "public",
        "session",
    ),
    Capability(
        "places.selected",
        "lookup_selected_places",
        "사용자가 이번 요청에 UI로 선택한 자주 가는 곳/위시만 읽기. "
        "미선택 별칭/전체목록/집주소를 추측하지 않음.",
        "read",
        "selected",
        "session",
        selected_required=True,
    ),
    Capability(
        "weather.read",
        "get_weather",
        "명시한 한국 공개 도시·날짜의 일별 예보. 구/주소 대신 도시. "
        "저장 일정 주소 자동 추출 금지. 도시 미정이면 ask_user region.",
        "read",
        "public",
        "session",
    ),
    Capability(
        "course.propose",
        "propose_course",
        "현재 대화에서 새 코스 제안 또는 활동 검색 범위를 구조화. "
        "operation=plan, targets는 사용자 원문 활동만. 실제 저장·확정 아님.",
        "proposal",
        "current",
        "planner",
    ),
    Capability(
        "dialogue.continue",
        "continue_planning",
        "현재 제안의 시간/비용/순서/장소 수정, 선택/되묻기 답변/재시도, 잡담·사용법. "
        "기능 설명·무엇을 할 수 있는지 묻는 질문도 포함. "
        "새 장소 후보/활동 주변 검색은 search_places. 일정 DB 조회도 해당 도구 사용. "
        "조건 질문의 답변/기존 검색 재시도는 계속 처리. 업무 저장은 사용자 버튼.",
        "control",
        "current",
        "planner",
    ),
    Capability(
        "dialogue.clarify",
        "ask_user",
        "필수 날짜/지역/대상/장소 선택이 없거나 미지원·실제 저장/확정 요청일 때 질문. "
        "장소 목표가 있으면 search_places의 지역을 비워 원래 검색을 보존.",
        "control",
        "current",
        "clarify",
    ),
    Capability(
        "course.validate",
        "validate_course",
        "현재 코스 초안의 비용 합계/예산·미정 비용·같은/역순 시각·중복/누락 장소 점검. "
        "인자는 빈 객체, 서버의 현재 초안만 검사. 실제 이동/영업 조회·수정/저장 없음.",
        "check",
        "current",
        "check",
    ),
)
BY_NAME = {c.name: c for c in CAPABILITIES}
SERVER_NAMES = frozenset(
    c.name for c in CAPABILITIES if c.executor in {"schedule", "plan", "check"}
)
SESSION_NAMES = frozenset(c.name for c in CAPABILITIES if c.executor == "session")
QUESTIONS = {
    "date": "어느 날짜의 공동 일정을 볼까요? 날짜 하나를 알려주세요.",
    "region": "어느 동네에서 찾아볼까요? 지역을 알려주거나 저장한 장소를 직접 선택해 주세요.",
    "target": (
        "공동 일정 조회와 코스·장소 찾기를 도와드릴 수 있어요. 날짜나 원하는 활동을 알려주세요."
    ),
    "selection": "저장한 장소에서 사용할 곳을 직접 선택해 주세요.",
    "unsupported": "이 기능은 위투 AI에서 아직 사용할 수 없어요. 해당 화면에서 확인해 주세요.",
    "save": "코스 초안을 확인한 뒤 초안 저장·확정 버튼을 눌러주세요.",
}


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capability_id: str
    status: Literal[
        "ok",
        "empty",
        "partial",
        "needs_input",
        "unavailable",
        "forbidden",
        "not_supported",
        "conflict",
        "cancelled",
        "budget_exhausted",
    ]
    complete: bool


def model_result(name, data):
    """Only already-approved tool evidence crosses the model boundary."""
    capability = BY_NAME.get(name)
    if capability is None or capability.view == "server_only":
        raise ValueError("No model projection for this capability")
    error = data.get("error")
    status = "ok"
    if error:
        status = (
            "budget_exhausted"
            if "budget" in error
            else "forbidden"
            if "not_allowed" in error
            else "not_supported"
            if error == "unknown_tool"
            else "needs_input"
            if error
            in {
                "invalid_tool_arguments",
                "unconfirmed_area",
                "unconfirmed_place_name",
                "outside_requested_query",
            }
            else "unavailable"
        )
    elif data.get("items") == []:
        status = "empty"
    result = CapabilityResult(
        capability_id=capability.id, status=status, complete=status in {"ok", "empty"}
    )
    return {**data, **result.model_dump()}


@lru_cache(maxsize=8)
def _definition_json(models):
    """Only static classes/metadata; no caller, selected IDs or business data."""
    return {
        name: json.dumps(
            compact_schema(model.model_json_schema()), ensure_ascii=False, separators=(",", ":")
        )
        for name, model in models
    }


def definitions(models, names=None, *, selected=True):
    selected_names = set(models) if names is None else set(names)
    if selected_names - BY_NAME.keys():
        raise ValueError("Unregistered capability")
    templates = _definition_json(tuple(models.items()))
    return [
        {
            "type": "function",
            "function": {
                "name": c.name,
                "description": c.description,
                "parameters": json.loads(templates[c.name]),
            },
        }
        for c in CAPABILITIES
        if c.name in selected_names and c.exposed and (selected or not c.selected_required)
    ]


def batch_definition(models, *, selected):
    """One native call can cover independent tasks without provider parallel-call support."""
    tasks = [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"const": tool["function"]["name"], "type": "string"},
                "arguments": tool["function"]["parameters"],
            },
            "required": ["name", "arguments"],
            "description": tool["function"]["description"],
        }
        for tool in definitions(models, selected=selected)
    ]
    return {
        "type": "function",
        "function": {
            "name": "select_capabilities",
            "description": "List ALL independently requested tasks, one to four, in one call. "
            "Each task names an allowed capability and supplies its typed arguments. No prose.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"oneOf": tasks},
                    }
                },
                "required": ["tasks"],
            },
        },
    }
