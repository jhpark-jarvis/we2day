"""Atomic activity edits inside one conversation; no tools or business writes."""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from we2day_api.plans import PlanContent


class ActivityEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["swap", "shift", "time"]
    targets: list[int] = Field(default_factory=list, max_length=20)
    minutes: int | None = Field(default=None, ge=0, le=1439)
    direction: Literal[-1, 1] = 1
    clock: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    turn_version: int = Field(default=0, ge=0)


class PendingFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # Values are copied only from a validated PlanContent, never from model context.
    values: dict[Literal["title", "date", "budget", "transport"], str | int] = Field(
        default_factory=dict, max_length=4
    )
    turn_version: int = Field(default=0, ge=0)


@dataclass
class EditResult:
    reply: str
    plan: PlanContent | None = None
    pending: ActivityEdit | None = None


def targets(text, count):
    if re.search(r"전체|전부|모든|모두", text):
        return list(range(count)), False
    group = re.search(r"(둘|셋|두\s*활동|세\s*활동)\s*(?:다|모두)?", text)
    if group and re.search(r"둘\s*다|셋\s*다|두\s*활동|세\s*활동", group[0]):
        size = 2 if re.search(r"둘|두", group[0]) else 3
        return (list(range(count)), False) if count == size else ([], False)
    found = []
    for index, pattern in enumerate(
        [
            r"첫\s*(?:번째|번|활동)|첫째",
            r"두\s*(?:번째|번|활동)|둘째",
            r"세\s*(?:번째|번|활동)|셋째",
            r"네\s*(?:번째|번|활동)|넷째",
        ]
    ):
        found.extend((m.start(), index) for m in re.finditer(pattern, text))
    found.extend((m.start(), count - 1) for m in re.finditer("마지막", text))
    found.extend(
        (m.start(), int(m[1]) - 1)
        for m in re.finditer(r"(?<!\d)(-?\d{1,3})\s*(?:번째|번)(?!\d)", text)
    )
    result = list(dict.fromkeys(i for _, i in sorted(found)))
    return result, any(not 0 <= i < count for i in result)


def duration(text):
    if re.search(r"[-+]\s*\d|\d+\.\d+", text):
        return None
    value = re.sub(r"한\s*시간", "1시간", text)
    value = re.sub(r"두\s*시간", "2시간", value)
    hours = re.findall(r"(?<![\d.])(\d+)\s*시간", value)
    minutes = re.findall(r"(?<![\d.])(\d+)\s*분", value)
    if len(hours) > 1 or len(minutes) > 1 or re.search(r"\d+\.\d+\s*(?:분|시간)", value):
        return None
    if not hours and not minutes:
        return None
    total = int(hours[0] if hours else 0) * 60 + int(minutes[0] if minutes else 0)
    return total if 0 <= total < 1440 else None


def edit_activities(text, proposal, previous, clock_value):
    if not proposal:
        return None
    previous = ActivityEdit.model_validate(previous) if previous else None
    if previous and re.fullmatch(r"\s*(?:취소해?\s*줘?|그대로\s*둬)[.!?]?\s*", text):
        return EditResult("변경을 취소했어요. 현재 코스는 그대로 둘게요.")
    swap = bool(re.search(r"순서|순번", text) and re.search(r"바꿔|교환|교체", text))
    shift = bool(re.search(r"미뤄|늦춰|당겨|앞당겨", text))
    indices, invalid = targets(text, len(proposal.activities))
    multiple_time = "시간" in text and len(indices) > 1 and bool(re.search(r"바꿔|변경|설정", text))
    operation = "swap" if swap else "shift" if shift else "time" if multiple_time else None
    if not operation and not previous:
        return None
    if operation and re.search(r"(?:제목|날짜|예산).{0,30}(?:바꿔|변경|수정)", text):
        return EditResult("활동 변경과 제목·날짜·예산 변경 중 무엇부터 진행할까요?")
    if not operation and previous and re.search(r"제목|날짜|예산|검색|찾아|코스.*만들", text):
        return None
    pending = ActivityEdit(operation=operation) if operation else previous.model_copy(deep=True)
    if indices:
        pending.targets = indices
    if invalid:
        pending.targets = []
        return EditResult(
            "유효한 활동 번호를 알려주세요. 현재 코스의 몇 번째 활동인가요?", pending=pending
        )
    if pending.operation == "shift":
        if operation:
            pending.direction = -1 if re.search(r"당겨|앞당겨", text) else 1
        amount = duration(text)
        if amount is not None:
            pending.minutes = amount
        elif operation:
            pending.minutes = None
    if pending.operation == "time":
        clocks = re.findall(
            r"(?<!\d)\d{1,2}:\d{2}(?!\d)|(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?", text
        )
        values = [clock_value(token)[0] for token in clocks]
        if len(values) > 1 and (None in values or len(set(values)) > 1):
            pending.clock = None
            return EditResult(
                "활동별 시간이 서로 달라요. 한 활동씩 지정하거나 공통 시간 하나를 알려주세요.",
                pending=pending,
            )
        clock, question = clock_value(text)
        if clock:
            pending.clock = clock
        elif question and not pending.clock:
            return EditResult(question, pending=pending)
    needed = 2 if pending.operation == "swap" else 1
    if len(pending.targets) < needed or pending.operation == "swap" and len(pending.targets) != 2:
        pending.targets = []
        return EditResult("어느 활동을 바꿀까요? 몇 번째 활동인지 알려주세요.", pending=pending)
    if any(not 0 <= i < len(proposal.activities) for i in pending.targets):
        return EditResult("현재 코스의 활동 번호를 다시 알려주세요.")
    if pending.operation == "shift" and pending.minutes is None:
        return EditResult("몇 분 옮길까요? 하루 미만의 분 또는 시간을 알려주세요.", pending=pending)
    updated = proposal.model_copy(deep=True)
    if pending.operation == "swap":
        first, second = pending.targets
        updated.activities[first], updated.activities[second] = (
            updated.activities[second],
            updated.activities[first],
        )
    else:
        for index in pending.targets:
            if pending.operation == "time":
                updated.activities[index].time = pending.clock
                continue
            current = updated.activities[index].time
            if current is None:
                return EditResult(
                    f"{index + 1}번째 활동의 시간이 미정이에요. 현재 시간을 먼저 정해 주세요."
                )
            hour, minute = map(int, current.split(":"))
            value = hour * 60 + minute + pending.direction * pending.minutes
            if not 0 <= value < 1440:
                return EditResult(
                    "시간 이동이 자정을 넘어 날짜가 바뀌어요. 날짜와 시간을 직접 지정해 주세요."
                )
            updated.activities[index].time = f"{value // 60:02}:{value % 60:02}"
    return EditResult(
        "요청한 활동만 수정했어요. 코스 초안에서 확인해 주세요.",
        PlanContent.model_validate(updated.model_dump()),
    )
