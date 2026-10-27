"""Bounded current-conversation control. No preferences, business writes or model-owned state."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from we2day_api.ai_edits import edit_activities
from we2day_api.ai_place_policy import (
    WORDS,
    Kind,
    SearchScope,
    generic_name,
    kinds,
    norm,
    requested_scope,
)
from we2day_api.plans import PlanContent

Intent = Literal["search", "select", "plan", "edit", "reject", "clarify", "chat", "weather"]


class PendingChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: Literal["title", "date", "budget", "transport", "activity_time", "target", "region"]
    value: str = Field(default="", max_length=100)
    resume: Intent = "edit"


class DialogueState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Intent = "chat"
    rejected_places: list[str] = Field(default_factory=list, max_length=24)
    excluded_kinds: list[Kind] = Field(default_factory=list, max_length=10)
    pending: PendingChange | None = None
    turn_version: int = Field(default=0, ge=0)
    cleared_date: bool = False
    append_pending: bool = False


@dataclass
class Directive:
    state: DialogueState
    scope: SearchScope
    intent: Intent = "chat"
    slots: dict = field(default_factory=dict)
    reply: str = ""
    plan: PlanContent | None = None
    allowed_tools: set[str] = field(default_factory=set)

    def ask(self, name, reply, *, value="", resume="edit"):
        self.intent = self.state.intent = "clarify"
        self.state.pending = PendingChange(field=name, value=value, resume=resume)
        self.reply = reply
        self.plan = None
        self.allowed_tools.clear()


def explicit_date(text):
    matches = re.findall(r"(?<!\d)(20\d{2}|2100)-(\d{2})-(\d{2})(?!\d)", text)
    matches += re.findall(r"(20\d{2}|2100)년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    values = set()
    for year, month, day in matches:
        try:
            values.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            continue
    return values.pop() if len(values) == 1 else None


def date_value(text, today):
    # Alternatives are a question, corrections use the explicitly supplied replacement.
    dates = re.findall(
        r"(?:20\d{2}|2100)-\d{2}-\d{2}|(?:20\d{2}|2100)년\s*\d{1,2}월\s*\d{1,2}일", text
    )
    if len(set(dates)) > 1 and re.search(r"또는|아니면|혹은|둘\s*중|중에서", text):
        return None, "어느 날짜로 정할까요? 날짜 하나를 알려주세요."
    corrected = re.split(r"말고|아니라", text)[-1]
    value = explicit_date(corrected if len(dates) > 1 else text)
    if dates and value is None:
        return None, "유효한 날짜 하나를 알려주세요."
    if value:
        return value, ""
    if re.search(r"이번\s*주말|다음\s*주말", text):
        return None, "토요일과 일요일 중 어느 날짜로 정할까요?"
    for word, days in (("모레", 2), ("내일", 1), ("오늘", 0)):
        if word in corrected:
            return (today + timedelta(days=days)).isoformat(), ""
    weekdays = {
        "월요일": 0,
        "화요일": 1,
        "수요일": 2,
        "목요일": 3,
        "금요일": 4,
        "토요일": 5,
        "일요일": 6,
    }
    for word, day in weekdays.items():
        if word in corrected and re.search(r"이번\s*주|다음\s*주", corrected):
            shift = 7 if re.search(r"다음\s*주", corrected) else 0
            return (today + timedelta(days=day - today.weekday() + shift)).isoformat(), ""
    return None, ""


def negative_kinds(text):
    """Explicit venue-kind negations; preserve '빼지 말고' and other double negatives."""
    found = set()
    negative = re.compile(
        r"말고|아니라|나중|별로|싫|그만|안\s*(?:가|갈|찾)|"
        r"빼(?!지\s*말)|제외(?!하지\s*마)|넣지\s*마|가지\s*마|"
        r"검색하지\s*(?:마|말)|찾지\s*(?:마|말)"
    )
    for kind, words in WORDS.items():
        for word in words:
            for match in re.finditer(re.escape(word), text):
                tail = re.split(r"[.!?\n]", text[match.end() :], maxsplit=1)[0][:45]
                stop = negative.search(tail)
                if not stop:
                    continue
                between = tail[: stop.start()]
                for labels in WORDS.values():
                    for label in labels:
                        between = between.replace(label, "")
                between = re.sub(r"활동|일정|방문|만", "", between)
                between = re.sub(r"하고|그리고|(?:[은는을를이가와과랑도및,\s])", "", between)
                if not between:
                    found.add(kind)
    return found


def positive_text(text, denied):
    value = text
    for kind in denied:
        for word in WORDS[kind]:
            value = value.replace(word, "")
    return value


def place_names(proposal, chosen):
    names = [item.title for item in chosen]
    if proposal:
        names += [
            re.split(r"\s+\(| · ", a.place, maxsplit=1)[0] for a in proposal.activities if a.place
        ]
    return list(dict.fromkeys(n for n in names if n))


def rejected_names(text, known):
    names = list(known)
    names += re.findall(r"[\"'‘“]([^\"'’”]{2,100})[\"'’”]", text)
    extracted = re.findall(
        r"(?<![가-힣])([가-힣A-Za-z0-9]{2,30}?)(?:은|는|을|를)?\s*(?:말고|제외|빼|별로|싫)", text
    )
    names += [re.sub(r"(?:활동|일정)?만$", "", n) for n in extracted]
    denied, restored = [], []
    for name in dict.fromkeys(names):
        if (
            not name
            or generic_name(name)
            or name
            in {
                "그거",
                "그곳",
                "다른곳",
                "여기",
                "장소",
                "코스",
                "활동",
                "제목",
                "날짜",
                "예산",
            }
        ):
            continue
        if name not in text:
            continue
        tail = text.split(name, 1)[1].lstrip("'’”\" ")
        if re.match(
            r"(?:은|는|을|를)?\s*(?:빼지\s*마|제외하지\s*마|제외\s*취소|다시\s*(?:포함|넣|가도))",
            tail,
        ):
            restored.append(name)
        elif re.match(r"(?:은|는|을|를)?\s*(?:말고|제외|빼|별로|싫)", tail):
            denied.append(name)
    return denied, restored


def activity_index(text, count):
    if "마지막" in text:
        return count - 1
    for token, number in (
        ("첫", 0),
        ("두", 1),
        ("둘", 1),
        ("세", 2),
        ("셋", 2),
        ("네", 3),
        ("넷", 3),
    ):
        if re.search(token + r"\s*(?:번째|번|활동|일정)", text):
            return number if number < count else None
    match = re.search(r"(?<!\d)(-?\d{1,3})\s*(?:번째|번|활동|일정)", text)
    if match:
        return int(match[1]) - 1 if 1 <= int(match[1]) <= count else None
    if re.search(r"번째|\d\s*번", text):
        return None
    return 0 if count == 1 else None


def activity_target(text, proposal):
    index = activity_index(text, len(proposal.activities))
    if index is not None:
        return index
    if re.search(r"번째|-?\d+\s*(?:번|활동|일정)", text):
        return None
    found = [
        i
        for i, a in enumerate(proposal.activities)
        if a.title in text or a.place and re.split(r"\s+\(| · ", a.place, maxsplit=1)[0] in text
    ]
    return found[0] if len(found) == 1 else None


def clock_value(text):
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if match:
        return f"{int(match[1]):02}:{match[2]}", ""
    match = re.search(r"(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?", text)
    if not match:
        return None, "새 시간을 알려주세요. 예: 오후 3시 또는 15:00."
    hour, minute = int(match[2]), int(match[3] or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None, "유효한 시간을 알려주세요."
    if not match[1] and 1 <= hour <= 12:
        return None, "오전과 오후 중 언제인가요? 예: 오후 3시."
    if match[1]:
        if not 1 <= hour <= 12:
            return None, "오전·오후 시간은 1시부터 12시로 알려주세요."
        hour = hour % 12 + (12 if match[1] == "오후" else 0)
    return f"{hour:02}:{minute:02}", ""


def money_value(text):
    if re.search(r"달러|USD|유로|EUR|엔화|인당|각자|[$€¥]", text, re.I):
        return None
    matches = list(re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(만\s*원?|천\s*원?|원)", text))
    if not matches:
        match = re.search(
            r"예산(?:은|을|이)?\s*(\d[\d,]*)(?![\d,])(?=\s*(?:으로|로|$|[.!?]))", text
        )
        return int(match[1].replace(",", "")) if match else None
    match = matches[-1]
    return int(
        Decimal(match[1].replace(",", ""))
        * {"만원": 10000, "만": 10000, "천원": 1000, "천": 1000, "원": 1}[match[2].replace(" ", "")]
    )


def analyze(text, context, proposal, chosen, today, *, selected=False):
    state = DialogueState.model_validate(context.get("dialogue") or {}).model_copy(deep=True)
    old_pending = state.pending
    state.pending = None
    previous_scope = SearchScope.model_validate(context.get("search_scope") or {})
    directive = Directive(state, previous_scope.model_copy(deep=True))
    if context.get("pending_fields"):
        directive.slots["pending_fields"] = None
    compound = edit_activities(text, proposal, context.get("activity_edit"), clock_value)
    if compound:
        state.pending = None
        state.append_pending = False
        directive.slots["activity_edit"] = (
            compound.pending.model_dump() if compound.pending else None
        )
        directive.intent = state.intent = "edit" if compound.plan else "clarify"
        directive.reply, directive.plan = compound.reply, compound.plan
        if compound.plan:
            directive.slots["activities"] = [a.title for a in compound.plan.activities][:8]
        return directive
    if context.get("activity_edit"):
        directive.slots["activity_edit"] = None
        old_pending = None
    if (old_pending or state.append_pending) and re.fullmatch(
        r"\s*(?:아니[,.]?\s*)?(?:취소해?\s*줘?|그대로\s*둬|변경하지\s*마)[.!?]?\s*", text
    ):
        state.intent = "chat"
        state.append_pending = False
        directive.reply = "현재 코스는 그대로 둘게요."
        return directive
    denied_kinds = negative_kinds(text)
    positive = positive_text(text, denied_kinds)
    active = kinds(positive)
    state.excluded_kinds = list(
        dict.fromkeys([k for k in state.excluded_kinds if k not in active] + sorted(denied_kinds))
    )
    known = place_names(proposal, chosen)
    rejected, restored = rejected_names(text, known)
    state.rejected_places = [
        n for n in state.rejected_places if norm(n) not in {norm(v) for v in restored}
    ]
    state.rejected_places = list(dict.fromkeys(state.rejected_places + rejected))[-24:]
    if directive.scope.exact_name and norm(directive.scope.exact_name) in {
        norm(n) for n in rejected
    }:
        directive.scope.exact_name, directive.scope.name_kind = "", "any"
    selection = text.startswith("선택한 장소:") and bool(chosen)
    if selection:
        state.rejected_places = [
            n for n in state.rejected_places if norm(n) != norm(chosen[-1].title)
        ]
        selected_kind = kinds(chosen[-1].title) or (
            ["park"] if chosen[-1].title.endswith("숲") else []
        )
        state.excluded_kinds = [k for k in state.excluded_kinds if k not in selected_kind]
    searching = re.sub(r"검색하지\s*(?:마|말)|검색\s*말고|찾지\s*(?:마|말)", "", positive)
    search = bool(re.search(r"검색|찾아|찾아봐|찾아줄|후보|추천", searching))
    search = search or bool(active and re.search(r"보여\s*줘", searching))
    search = search or bool(active and re.search(r"보고\s*싶|찾자", searching))
    search = search or bool(
        denied_kinds
        and active
        and previous_scope.kinds
        and not re.search(r"빼\s*줘|제외해|삭제해|없애", text)
    )
    plan_request = any(
        re.search(r"(?:코스|플랜).*(?:짜|만들|반영|제안|추천)", clause)
        and not re.search(r"(?:코스|플랜).{0,10}(?:만들지|짜지|반영하지|아직|말고|나중)", clause)
        for clause in re.split(r"[.!?\n]", positive)
    )
    edit_request = bool(re.search(r"바꿔|바꾸|변경|수정|고쳐|으로\s*해\s*줘|로\s*해\s*줘", text))
    adding = bool(
        proposal
        and re.search(r"추가|넣어|포함", positive)
        and (active or re.search(r"활동|장소", positive))
    )
    title_field = bool(re.search(r"제목|(?:코스|플랜)\s*(?:이름|명칭)", text))
    date_field = bool(re.search(r"날짜|일자", text))
    time_field = "시간" in text
    budget_field = bool(re.search(r"예산|총액|전체\s*비용", text))
    transport_field = bool(re.search(r"이동\s*수단|교통|자동차|자가용|대중교통|도보", text))
    weather = bool(re.search(r"날씨|예보|비\s*오|우천", text))
    remove = bool(re.search(r"빼\s*줘|제외해|삭제해|없애", text)) and not bool(
        re.search(r"빼지\s*마|제외하지\s*마", text)
    )
    if selection:
        directive.intent = "select"
    elif adding:
        directive.intent = "plan"
    elif proposal and (
        edit_request or remove and not search or old_pending and old_pending.resume == "edit"
    ):
        directive.intent = "edit"
    elif plan_request or old_pending and old_pending.resume in {"plan", "select"}:
        directive.intent = old_pending.resume if old_pending else "plan"
    elif search:
        directive.intent = "search"
    elif rejected or denied_kinds:
        directive.intent = "reject"
    elif weather:
        directive.intent = "weather"
    elif re.search(r"그거|그것|그곳|두\s*번째|둘\s*중", text) and re.search(
        r"빼|골라|정해|선택", text
    ):
        directive.ask("target", "어느 장소나 활동을 말하나요? 이름을 알려주세요.", resume="search")
    state.intent = directive.intent
    if adding:
        state.append_pending = not bool(rejected or denied_kinds or edit_request)
        directive.slots["activities"] = list(
            dict.fromkeys(
                context.get("activities", [])
                + [next((w for w in WORDS[k] if w in positive), WORDS[k][0]) for k in active]
            )
        )[:8]
    elif directive.intent == "edit" or plan_request and not selection:
        state.append_pending = False
    if directive.intent in {"search", "plan", "select"}:
        directive.scope = requested_scope(positive, directive.scope, chosen)
        if adding:
            old_kinds = {k for activity in proposal.activities for k in kinds(activity.title)}
            new_kinds = [k for k in active if k not in old_kinds]
            if new_kinds:
                directive.scope.kinds = new_kinds
            if norm(directive.scope.exact_name) in {norm(n) for n in known}:
                directive.scope.exact_name, directive.scope.name_kind = "", "any"
            directive.scope.single_activity = False
        if directive.scope.exact_name and norm(directive.scope.exact_name) in {
            norm(n) for n in state.rejected_places
        }:
            directive.scope.exact_name, directive.scope.name_kind = "", "any"
        directive.scope.kinds = [k for k in directive.scope.kinds if k not in state.excluded_kinds]
        if not directive.scope.area and context.get("region"):
            directive.scope.area = context["region"]
        if directive.scope.area:
            directive.slots["region"] = directive.scope.area
        if directive.intent == "search":
            directive.scope.search_only = True
    check_date = (
        directive.intent != "edit" or date_field or old_pending and old_pending.field == "date"
    )
    value, date_question = date_value(text, today) if check_date else (None, "")
    if value:
        directive.slots["date"] = value
        state.cleared_date = False
    if date_question and (directive.intent in {"plan", "edit", "select"} or date_field):
        directive.ask("date", date_question, resume="edit" if proposal else "plan")
    if re.search(r"날짜(?:는|를|가)?\s*(?:아직\s*)?(?:미정|나중|정하지|취소)", text):
        directive.slots["date"] = None
        state.cleared_date = True
    if budget_field:
        value = money_value(text)
        if value is not None and 0 <= value <= 1_000_000_000:
            directive.slots["budget"] = value
    transports = list(
        re.finditer(r"자동차|자가용|차로|운전|대중교통|버스|지하철|도보|걸어서", text)
    )
    if transports and not (
        directive.intent == "edit" and title_field and not re.search(r"이동\s*수단", text)
    ):
        last = transports[-1][0]
        directive.slots["transport"] = (
            "대중교통"
            if last in {"대중교통", "버스", "지하철"}
            else "도보"
            if last in {"도보", "걸어서"}
            else "자동차"
        )
    if directive.intent == "edit" and not directive.reply:
        updated = proposal.model_copy(deep=True)
        changed = False
        if old_pending and context.get("pending_fields"):
            for name, value in context["pending_fields"]["values"].items():
                setattr(updated, name, value)
            updated = PlanContent.model_validate(updated.model_dump())
            changed = True
        pending_field = old_pending.field if old_pending and old_pending.resume == "edit" else ""
        if remove or pending_field == "target" and old_pending.value == "remove":
            index = activity_target(text, proposal)
            if index is None and denied_kinds:
                matching = [
                    i
                    for i, a in enumerate(proposal.activities)
                    if set(kinds(a.title)) & denied_kinds
                ]
                index = matching[0] if len(matching) == 1 else None
            if index is None:
                directive.ask(
                    "target",
                    "어느 활동을 뺄까요? 활동 이름이나 몇 번째인지 알려주세요.",
                    value="remove",
                )
            else:
                activity = updated.activities.pop(index)
                name = re.split(r"\s+\(| · ", activity.place, maxsplit=1)[0]
                if name and not generic_name(name):
                    state.rejected_places = list(dict.fromkeys(state.rejected_places + [name]))[
                        -24:
                    ]
                directive.slots["activities"] = [a.title for a in updated.activities]
                changed = True
        if title_field or pending_field == "title":
            match = re.search(r"[\"'‘“]([^\"'’”]{1,100})[\"'’”]", text)
            if match:
                title = match[1]
            else:
                match = re.search(
                    r"(?:제목|이름|명칭)(?:만|을|은|는)?\s*(.{1,100}?)(?:으로|로)\s*(?:바꿔|바꾸|변경|수정|해\s*줘)",
                    text,
                )
                title = (
                    match[1].strip() if match else text.strip() if pending_field == "title" else ""
                )
            if title:
                updated.title, changed = title, True
            else:
                directive.ask("title", "어떤 제목으로 바꿀까요? 새 제목을 알려주세요.")
        if date_field or pending_field == "date":
            if directive.slots.get("date"):
                updated.date, changed = directive.slots["date"], True
            else:
                directive.ask(
                    "date", date_question or "어느 날짜로 바꿀까요? 날짜 하나를 알려주세요."
                )
        if budget_field or pending_field == "budget":
            value = directive.slots.get("budget", money_value(text))
            if value is not None and 0 <= value <= 1_000_000_000:
                updated.budget, changed = value, True
                directive.slots["budget"] = value
            else:
                directive.ask("budget", "전체 예산을 원 단위로 얼마로 정할까요?")
        if transport_field and "transport" in directive.slots:
            updated.transport, changed = directive.slots["transport"], True
        if time_field or pending_field == "activity_time":
            value, question = clock_value(text)
            if pending_field == "activity_time" and old_pending.value and value is None:
                value, question = old_pending.value, ""
            index = activity_target(text, updated)
            if question:
                directive.ask("activity_time", question)
            elif index is None:
                directive.ask(
                    "activity_time",
                    "어느 활동의 시간인가요? 몇 번째 활동인지 알려주세요.",
                    value=value,
                )
            else:
                updated.activities[index].time, changed = value, True
        fields = {
            name: getattr(updated, name)
            for name in ("title", "date", "budget", "transport")
            if getattr(updated, name) != getattr(proposal, name)
        }
        if directive.reply:
            for name in ("date", "budget", "transport", "activities"):
                directive.slots.pop(name, None)
            if fields:
                directive.slots["pending_fields"] = {"values": fields, "turn_version": 0}
        else:
            if changed:
                directive.plan = PlanContent.model_validate(updated.model_dump())
                directive.slots.update({k: v for k, v in fields.items() if k != "title"})
                directive.reply = "요청한 항목만 수정했어요. 코스 초안에서 확인해 주세요."
            else:
                directive.ask("target", "어느 항목을 어떻게 바꿀까요? 변경할 내용을 알려주세요.")
    if directive.intent in {"plan", "select"} and not directive.reply:
        known_date = directive.slots.get("date", context.get("date")) or (
            proposal.date if proposal and not state.cleared_date else None
        )
        if not known_date:
            directive.ask(
                "date", "어느 날짜의 코스로 정할까요? 날짜를 알려주세요.", resume=directive.intent
            )
        else:
            directive.slots["date"] = known_date
            directive.scope.search_only = False
    if (
        directive.intent == "search"
        and not directive.reply
        and not directive.scope.area
        and not directive.scope.exact_name
        and not selected
    ):
        directive.ask(
            "region", "어느 지역에서 찾아볼까요? 동네나 지역을 알려주세요.", resume="search"
        )
    if directive.intent in {"search", "plan"} and not directive.reply:
        directive.allowed_tools.add("search_places")
    if weather and not directive.reply:
        directive.allowed_tools.add("get_weather")
    if directive.intent == "reject" and not directive.reply:
        directive.reply = "이번 대화에서는 제외할게요. 다른 후보가 필요하면 알려주세요."
    if directive.intent == "chat":
        if re.search(r"고마워|고맙|감사", text):
            directive.reply = "좋아요. 더 정하거나 바꾸고 싶은 내용이 있으면 알려주세요."
        elif re.search(r"어떤\s*도움|무슨\s*일|뭘\s*할\s*수|어떤\s*기능", text):
            directive.reply = "장소 후보를 찾고, 조건을 정리해서 코스 초안을 함께 만들 수 있어요."
    state.intent = directive.intent
    return directive


def merge_context(previous, incoming, directive):
    result = dict(previous)
    for key, value in incoming.items():
        if key in {"dialogue", "search_scope", "date", "budget", "transport", "region"}:
            continue
        # Empty full-schema defaults cannot erase an explicitly known condition.
        if result.get(key) in (None, "", []) and value not in (None, "", []):
            result[key] = value
    result.update(directive.slots)
    result["search_scope"] = directive.scope.model_dump()
    result["dialogue"] = directive.state.model_dump()
    return result
