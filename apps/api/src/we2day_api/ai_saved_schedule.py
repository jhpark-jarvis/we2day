"""Explicit shared-date reads, rendered locally. No business data enters model input."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from fastapi import HTTPException

from we2day_api.ai_dialogue import date_value

DATE_TOKEN = re.compile(
    r"(?<!\d)(?:(20\d{2}|2100)-(\d{2})-(\d{2})(?!\d)|"
    r"(?:(20\d{2}|2100)년\s*)?(\d{1,2})월\s*(\d{1,2})일)"
)
LIMIT = 10
PLAN_SELECT = (
    "id,appointment_id,draft_title:content->>title,draft_date:content->>date,"
    "draft_activities:content->activities,published_title:published_content->>title,"
    "published_date:published_content->>date,activities:published_content->activities"
)


@dataclass(frozen=True)
class ScheduleRead:
    date: str = ""
    question: str = ""
    reason: str = ""


def request_read(text, context, version, today):
    previous = context.get("schedule_read")
    previous = previous if isinstance(previous, dict) and previous.get("basis") == version else {}
    # Mutations and recommendations retain the planner's existing explicit action contract.
    if re.search(
        r"만들|등록(?:해|하|할)|추가|삭제|수정|바꿔|변경|추천|제안|짜\s*줘|저장해|확정해|"
        r"현재\s*(?:제안|초안|코스)|지금\s*(?:제안|초안|코스)",
        text,
    ):
        return None
    schedule = bool(re.search(r"일정|약속|코스|플랜", text))
    date_only = DATE_TOKEN.sub("", text)
    date_only = re.sub(
        r"오늘|내일|모레|어제|그날|(?:이번|다음)\s*주|[월화수목금토일]요일", "", date_only
    )
    date_reply = (
        previous
        and date_only != text
        and bool(re.fullmatch(r"(?:그럼|은|는|에|로|으로|이야|야|요|[.!?？\s])*", date_only))
    )
    retry = previous and re.fullmatch(r"(?:다시|재조회|다시\s*확인해\s*줘)[.!?\s]*", text)
    if not schedule and not date_reply and not retry:
        return None
    if schedule and not re.search(
        r"브리핑|조회|보여|불러|확인|알려|있|없|어떻게|뭐|무슨|정리|요약|"
        r"저장된|저장한|등록된|오늘|내일|모레|어제|이번\s*주|다음\s*주|요일|\d월|\d{4}-\d{2}-\d{2}",
        text,
    ):
        return None
    if re.search(r"개인\s*(?:일정|약속)", text):
        return ScheduleRead(
            question=("여기서는 공동 약속과 코스만 조회해요. 개인 일정은 달력에서 확인해 주세요.")
        )
    return schedule_date(text, context, version, today)


def schedule_date(text, context, version, today):
    """Date validation shared by legacy intent and model-selected reads."""
    previous = context.get("schedule_read")
    previous = previous if isinstance(previous, dict) and previous.get("basis") == version else {}
    values = set()
    for m in DATE_TOKEN.finditer(text):
        year, month, day = (m[1], m[2], m[3]) if m[1] else (m[4], m[5], m[6])
        try:
            values.add(date(int(year or today.year), int(month), int(day)).isoformat())
        except ValueError:
            return ScheduleRead(
                question="날짜를 확인해 주세요. 조회할 날짜 하나를 알려주세요.",
                reason="invalid_date",
            )
    for word, shift in (("오늘", 0), ("내일", 1), ("모레", 2), ("어제", -1)):
        if word in text:
            values.add((today + timedelta(days=shift)).isoformat())
    if len(values) > 1 or re.search(r"또는|아니면|혹은|부터|까지|이번\s*주말|다음\s*주말", text):
        return ScheduleRead(
            question="어느 날짜의 공동 일정을 볼까요? 날짜 하나를 알려주세요.",
            reason="ambiguous_date",
        )
    if not values:
        value, question = date_value(text, today)
        if question:
            return ScheduleRead(question=question, reason="ambiguous_date")
        if value:
            values.add(value)
    target = next(iter(values), "")
    if not target and previous:
        target = previous.get("date", "")
    if not target:
        return ScheduleRead(
            question="어느 날짜의 공동 일정을 볼까요? 날짜를 알려주세요.", reason="missing_date"
        )
    try:
        parsed = date.fromisoformat(target)
        if not 2000 <= parsed.year <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        return ScheduleRead(
            question="날짜를 확인해 주세요. 조회할 날짜 하나를 알려주세요.", reason="invalid_date"
        )
    return ScheduleRead(date=target)


def plain(value, limit=140):
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


@dataclass(frozen=True)
class ScheduleSummary:
    reply: str
    count: int
    partial: bool


def summarize_schedule(target, appointments, plans):
    """Published courses belong to their shared appointment; drafts stay separately labelled."""
    lines, shown = [f"{target} 공동 일정"], 0
    clipped = len(appointments) > LIMIT or len(plans) > LIMIT
    appointments = [
        a for a in appointments[:LIMIT] if a.get("kind") == "shared" and a.get("date") == target
    ]
    linked = {str(a["id"]): a for a in appointments}
    published = {}
    drafts = []
    for p in plans[:LIMIT]:
        if p.get("published_date") == target:
            published.setdefault(str(p.get("appointment_id")), []).append(p)
        if not p.get("published_date") and p.get("draft_date") == target:
            drafts.append(p)
        elif p.get("draft_date") == target and (
            p.get("draft_date") != p.get("published_date")
            or p.get("draft_title") != p.get("published_title")
            or p.get("draft_activities") != p.get("activities")
        ):
            drafts.append(p)

    def add_course(p):
        nonlocal clipped
        activities = p.get("activities") or []
        if not isinstance(activities, list):
            raise ValueError("Invalid saved activities")
        for a in activities[:20]:
            if not isinstance(a, dict):
                raise ValueError("Invalid saved activity")
            line = "  · " + " ".join(
                filter(None, [plain(a.get("time"), 5), plain(a.get("title"), 100)])
            )
            if place := plain(a.get("place"), 160):
                line += " — " + place
            if sum(map(len, lines)) + len(line) > 3400:
                clipped = True
                break
            lines.append(line)

    for a in appointments:
        shown += 1
        line = " ".join(filter(None, [plain(a.get("time"), 5), plain(a.get("title"), 100)]))
        if place := plain(a.get("place"), 160):
            line += " — " + place
        if sum(map(len, lines)) + len(line) > 3400:
            clipped = True
            break
        lines.append("• " + line)
        for p in published.pop(str(a["id"]), []):
            add_course(p)
    for aid, courses in published.items():
        if aid in linked:
            continue
        for p in courses:
            shown += 1
            if sum(map(len, lines)) > 3200:
                clipped = True
                break
            lines.append("• 확정 코스: " + plain(p.get("published_title"), 100))
            add_course(p)
    for p in drafts:
        shown += 1
        if sum(map(len, lines)) > 3200:
            clipped = True
            break
        lines.append("• 미확정 초안: " + plain(p.get("draft_title"), 100))
        add_course({"activities": p.get("draft_activities")})
    if not shown:
        lines.append("저장된 공동 약속과 코스가 없어요. 개인 일정은 이 조회에 포함되지 않아요.")
    if clipped:
        lines.append("일부 일정만 표시했어요. 나머지는 일정·플랜 목록에서 확인해 주세요.")
    return ScheduleSummary("\n".join(lines), shown, clipped)


def render(target, appointments, plans):
    """Keep the original formatter contract for stored/internal callers."""
    result = summarize_schedule(target, appointments, plans)
    return result.reply, result.count


async def read_schedule(request, store, stats):
    if request.question:
        return request.question, []
    target = request.date
    try:
        with stats.span("tools"):
            appointments = await store.call(
                "GET",
                "appointments",
                params={
                    "select": "id,title,date,time,place,kind",
                    "date": f"eq.{target}",
                    "kind": "eq.shared",
                    "order": "time.asc.nullslast,id.asc",
                    "limit": str(LIMIT + 1),
                },
            )
            plans = await store.call(
                "GET",
                "date_plans",
                params={
                    "select": PLAN_SELECT,
                    "archived": "eq.false",
                    "or": f"(content->>date.eq.{target},published_content->>date.eq.{target})",
                    "order": "id.asc",
                    "limit": str(LIMIT + 1),
                },
            )
        if not isinstance(appointments, list) or not isinstance(plans, list):
            raise ValueError("Invalid saved schedule response")
        if any(not isinstance(p, dict) for p in appointments + plans):
            raise ValueError("Invalid saved schedule row")
        result = summarize_schedule(target, appointments, plans)
        return result.reply, [
            {
                "name": "read_shared_schedule",
                "count": result.count,
                "status": "partial" if result.partial else "ok" if result.count else "empty",
            }
        ]
    except (HTTPException, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        # Cancellation is intentionally not caught; lease/disconnect handling remains in _chat.
        return "저장된 공동 일정을 불러오지 못했어요. 잠시 후 다시 확인해 주세요.", [
            {"name": "read_shared_schedule", "count": 0, "status": "failed"}
        ]
