"""Bounded, domain-independent search data. The model proposes; the server resolves."""

import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from we2day_api.ai_conversation_hints import guidance
from we2day_api.ai_place_policy import Kind, SearchScope, explicit_area, kinds, norm
from we2day_api.ai_search_followups import continuation, search_phrase


class SearchTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Kind = "any"
    query: str = Field(min_length=1, max_length=50, pattern=r"^[가-힣A-Za-z0-9 ]+$")


class SearchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    semantic: int = 1
    version: int = 1
    targets: list[SearchTarget] = Field(min_length=1, max_length=4)
    anchor_index: int | None = Field(default=None, ge=0, le=7)
    anchor_key: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")
    anchor_pending: bool = False
    area: str = Field(default="", max_length=100)
    result_kind: Kind = "any"
    query: str = Field(default="", max_length=50)
    kind: Kind = "any"

    @model_validator(mode="after")
    def compatibility_view(self):
        self.query = self.targets[0].query if len(self.targets) == 1 else ""
        self.kind = self.targets[0].kind if len(self.targets) == 1 else "any"
        return self


def anchor_key(activity):
    return hashlib.sha256((activity.title + "\n" + activity.place).encode()).hexdigest()


def place_name(activity):
    value = re.split(r"\s*\(|\s+·\s+", activity.place, maxsplit=1)[0]
    if re.search(r"https?://", value):
        return ""
    return " ".join(re.sub(r"[^가-힣A-Za-z0-9 ]", " ", value).split())[:50]


def saved_spec(context, scope=None):
    value = context.get("place_search")
    if not isinstance(value, dict) or value.get("semantic") != 1:
        return None
    try:
        spec = SearchSpec.model_validate(value)
    except ValidationError:
        return None
    if spec.version != 1 or spec.semantic != 1:
        return None
    if scope and (scope.exact_name or set(scope.kinds) != {t.kind for t in spec.targets}):
        return None
    return spec


def current_anchor(spec, proposal):
    if not spec or not spec.anchor_key or not proposal:
        return None
    found = [a for a in proposal.activities if anchor_key(a) == spec.anchor_key]
    return found[0] if len(found) == 1 else None


def search_queries(spec, proposal):
    anchor = current_anchor(spec, proposal)
    prefix = place_name(anchor) if anchor else ""
    return [(t.kind, f"{prefix} {t.query}".strip(), t.query) for t in spec.targets]


def address_fallback(activity):
    if not activity:
        return ""
    match = re.search(r"\(([^()]*)\)", activity.place)
    if not match:
        return ""
    tokens = match[1].split()
    roads = [t for t in tokens if re.fullmatch(r"[가-힣A-Za-z0-9]+(?:대로|로|길)", t)]
    local = [t for t in tokens if re.fullmatch(r"[가-힣]+(?:동|읍|면)(?:\d+가)?", t)]
    return next(iter(roads or local[-1:]), "")


def semantic_request(text, directive, proposal, before):
    """Route free-form venue requests, not nouns from a domain-specific dictionary."""
    if (
        guidance(text)
        or directive.place_followup
        or text.startswith("선택한 장소:")
        or re.search(r"제목|기능|사용법", text)
    ):
        return False
    if continuation(text):
        return False
    if area_only_request(text):
        return False
    spec = saved_spec(before)
    if (
        spec
        and spec.anchor_pending
        and directive.state.pending
        and directive.intent not in {"edit", "reject", "weather"}
    ):
        return True
    # These are linguistic actions, independent of which place the user requests.
    requested = bool(
        re.search(
            r"찾|검색|추천|알아\s*봐|보여\s*줘|알려|없나|없을까|있을까|먹고\s*싶|가고\s*싶", text
        )
    )
    relation = re.search(r"(.+?)(?:주변|근처|인근|주위)", text)
    related = bool(
        relation
        and (
            re.search(r"장소|선택한|고른|일정|\d+\s*번", relation[1])
            or proposal
            and any(
                norm(a.title) == norm(relation[1].strip())
                or norm(place_name(a)) == norm(relation[1].strip())
                for a in proposal.activities
            )
        )
    )
    if related and requested:
        return True
    # A safe fast path remains for an exact, plain category lookup. Rich requests
    # use semantic extraction even if an old parser happened to inherit a category.
    if directive.intent == "search" and requested and not directive.scope.exact_name:
        target_text = text.replace(explicit_area(text), "") if explicit_area(text) else text
        if len(kinds(text)) < 2 and re.search(r"랑|하고|그리고|(?:와|과|및)\s|[,，]", target_text):
            return True
        if directive.slots.get("place_search") or not directive.scope.kinds:
            return True
        if not kinds(text):
            return True
    if requested and directive.intent in {"chat", "clarify"}:
        return True
    return False


def area_only_request(text):
    area = explicit_area(text)
    return bool(
        area
        and re.fullmatch(
            re.escape(area) + r"\s*(?:(?:근처|주변|인근|주위)\s*)?(?:에서|으로|로|에)?\s*"
            r"(?:알아\s*봐|찾아|검색해|추천해)\s*(?:줘|주세요|줄래)(?:요)?[.!?\s]*",
            search_phrase(text),
        )
    )


def changed_area(text):
    value = search_phrase(
        re.split(r"(?:말고|아니라)(?=\s|$)|(?<![가-힣])대신(?=\s|$)", text)[-1].strip()
    )
    area = explicit_area(value)
    return (
        area
        if area
        and re.fullmatch(
            re.escape(area)
            + r"\s*(?:으로|로)?\s*(?:바꾸자|바꿔(?:줘)?|바꿀게|변경해(?:줘)?|할게|하자)[.!?\s]*",
            value,
        )
        else ""
    )


def scope_for(targets, area):
    return SearchScope(
        area=area, kinds=list(dict.fromkeys(t.kind for t in targets)), search_only=True
    )


def referenced_anchor(text, proposal, pending=False):
    """Resolve current activity references, independently of the target vocabulary."""
    from we2day_api.ai_edits import targets as indices

    relation = re.search(r"주변|근처|인근|주위", text)
    if not relation and not pending:
        return None, False
    prefix = text[: relation.start()].strip() if relation else text.strip()
    activities = proposal.activities if proposal else []
    numbered, invalid = indices(prefix, len(activities))
    if invalid or len(numbered) > 1:
        return None, True
    if len(numbered) == 1 and 0 <= numbered[0] < len(activities):
        return numbered[0], True
    active = set(kinds(prefix))
    matches = [
        i
        for i, a in enumerate(activities)
        if active.intersection(kinds(a.title))
        or norm(place_name(a))
        and norm(place_name(a)) in norm(prefix)
        or norm(a.title) == norm(prefix)
    ]
    if len(matches) == 1:
        return matches[0], True
    relative = pending or bool(re.search(r"장소|선택한|고른|일정|그곳|거기|이곳|아까|해당", prefix))
    if relative:
        return (0 if len(activities) == 1 else None), True
    return None, bool(matches)
