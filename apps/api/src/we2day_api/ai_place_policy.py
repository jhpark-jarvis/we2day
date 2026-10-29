"""Conservative, server-owned place constraints; no model-owned permissions or facts."""

import html
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from we2day_api.places import SearchInput

Kind = Literal[
    "any", "library", "cafe", "restaurant", "park", "museum", "cinema", "bowling", "escape", "craft"
]
WORDS = {
    "library": ("도서관", "자료실"),
    "cafe": ("카페", "커피", "다방"),
    "restaurant": ("식당", "음식점", "샌드위치", "점심", "저녁", "맛집", "식사", "밥집"),
    "park": ("공원", "산책", "수목원", "생태공원"),
    "museum": ("박물관", "미술관", "전시관", "전시회"),
    "cinema": ("영화", "극장"),
    "bowling": ("볼링",),
    "escape": ("방탈출",),
    "craft": ("공방", "원데이클래스"),
}
LABELS = {key: values[0] for key, values in WORDS.items()}


def plain(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def norm(value):
    return re.sub(r"[^\w가-힣]", "", unicodedata.normalize("NFKC", plain(value))).casefold()


def kinds(value):
    return [key for key, words in WORDS.items() if any(word in value for word in words)]


def generic_name(value):
    return norm(value) in {norm(word) for words in WORDS.values() for word in words}


class SearchArguments(SearchInput):
    mode: Literal["exact_name", "category", "nearby"] = "category"
    name: str = Field(default="", max_length=100)
    kind: Kind = "any"
    area: str = Field(default="", max_length=100)


class SearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kinds: list[Kind] = Field(default_factory=list, max_length=8)
    exact_name: str = Field(default="", max_length=100)
    name_kind: Kind = "any"
    area: str = Field(default="", max_length=100)
    search_only: bool = False
    single_activity: bool = False


def relational_area(text):
    return bool(
        re.search(
            r"(?:이후|이전|다음|이번|해당|현재).*일정|(?:식사|약속|선택한|고른|방문한).*장소"
            r"|^(?:선택한|고른|방문한)\s|^\d+\s*번|^(?:식사|식당|카페|약속|코스|일정)(?:\s|$)",
            text,
        )
    )


def explicit_area(text):
    nearby = re.search(r"근처|주변|인근|주위", text)
    if nearby:
        prefix = re.split(r"[,，.!?\n]", text[: nearby.start()])[-1].strip()
        prefix = re.sub(r"^(?:(?:그럼|그러면|이제|대신|그냥|다시|오늘은|내일은)\s+)+", "", prefix)
        if (
            re.fullmatch(r"[가-힣A-Za-z0-9]+(?:\s+[가-힣A-Za-z0-9]+){0,2}", prefix)
            and len(prefix) <= 50
            and not relational_area(prefix)
            and prefix
            not in {
                "이",
                "그",
                "저",
                "여기",
                "거기",
                "이곳",
                "그곳",
                "그럼",
                "그러면",
                "이제",
                "대신",
                "그냥",
                "선택한 장소",
                "저장한 장소",
            }
            and not generic_name(prefix)
        ):
            return prefix
    areas = re.findall(
        r"(?<![가-힣])([가-힣]{2,10}(?:시|구|군|동|읍|면))"
        r"(?:에서|으로|로|에|의)?(?=[\s,.!?]|$)",
        text,
    )
    return next(
        (
            a
            for a in areas
            if not a.endswith(
                ("다시", "잠시", "혹시", "친구", "도구", "문구", "입구", "출구", "농구", "지구")
            )
        ),
        "",
    )


def area_matches(area, address):
    # Match administrative tokens, never a substring such as 양주 inside 남양주.
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", plain(area))
    words = re.findall(r"[가-힣A-Za-z0-9]+", plain(address))
    suffix = r"(?:특별자치시|특별시|광역시|특별자치도|시|군|구|읍|면|동|리)(?:\d+가)?"
    return bool(tokens) and all(
        any(
            norm(token) == norm(word)
            or re.fullmatch(re.escape(token) + suffix, word)
            or token.endswith(("동", "로"))
            and re.fullmatch(re.escape(token) + r"\d+가", word)
            for word in words
        )
        for token in tokens
    )


def requested_scope(text, previous=None, chosen=()):
    scope = (previous or SearchScope()).model_copy(deep=True)
    # Explicit UI choice is a new user decision, never an automatic selection by the model.
    if text.startswith("선택한 장소:") and chosen:
        scope.exact_name = chosen[-1].title
        scope.kinds = kinds(scope.exact_name)
        if not scope.kinds and scope.exact_name.endswith("숲"):
            scope.kinds = ["park"]
        scope.name_kind = scope.kinds[0] if len(scope.kinds) == 1 else "any"
        scope.search_only = False
        return scope
    positive = text
    for words in WORDS.values():
        for word in words:
            positive = re.sub(
                re.escape(word)
                + r"(?:는|은|도|를|을)?\s*(?:나중에?|말고|제외|찾지|검색하지|추가하지)",
                "",
                positive,
            )
    limited = re.search(r"(?:먼저|우선)\s*([^,.!?\n]{1,60}?만)", positive)
    active = kinds(limited[1] if limited else positive)
    nearby = bool(re.search(r"주변|근처|인근|주위", text))
    if active:
        if set(active) != set(scope.kinds) or nearby:
            scope.exact_name, scope.name_kind = "", "any"
        scope.kinds = active
    if re.search(r"아무\s*(?:곳|활동)|자유롭게|제한\s*없이|다른\s*종류", text):
        scope.kinds, scope.exact_name, scope.name_kind = [], "", "any"
    if limited or re.search(
        r"후보만|검색|찾아|장소만|보여\s*줘|보여주세요|고르지\s*마|선택하지\s*마", text
    ):
        scope.search_only = True
    no_plan = bool(re.search(r"(?:코스|플랜).*?(?:말고|나중|아직|않|마\b|마세요)", text))
    if no_plan:
        scope.search_only = True
    elif re.search(r"코스.*(?:짜|만들|제안|반영)|플랜.*(?:짜|만들|제안)|선택한 장소", text):
        scope.search_only = False
    if re.search(r"(?:한\s*가지|하나|1개|한\s*개)\s*(?:활동)?\s*만", text):
        scope.single_activity = True
    elif len(active) > 1 or re.search(r"추가해|추가하|함께\s*넣|둘\s*다", text):
        scope.single_activity = False
    area = explicit_area(text)
    if area:
        if norm(area) != norm(scope.area):
            scope.exact_name, scope.name_kind = "", "any"
        scope.area = area
    target = None
    if not nearby:
        match = re.search(
            r"검색어(?:는|를)?\s*[\"'‘’“”]?([가-힣A-Za-z0-9 ]{2,50}?)"
            r"(?:[\"'‘’“”]|\s+한\s*단어|\s+그대로|(?:으로|로)\s*(?:만|다시))",
            text,
        )
        if match:
            target = match[1].strip()
        else:
            match = re.search(r"[\"'‘“]([^\"'’”]{2,60})[\"'’”]", positive)
            if match and ("검색" in text or "찾" in text):
                target = match[1]
            else:
                names = re.findall(
                    r"(?<![가-힣])([가-힣A-Za-z0-9]{2,24}(?:숲|공원|도서관|박물관|미술관|수목원))(?:에서|으로|에|로|만|을|를)?(?=[\s,.!?]|$)",
                    positive,
                )
                names = list(
                    dict.fromkeys(
                        n
                        for n in names
                        if n not in {"공공도서관", "작은도서관", "근린공원", "생태공원"}
                    )
                )
                if len(names) == 1:
                    target = names[0]
    if target and not generic_name(target):
        scope.exact_name = target[:100]
        target_kinds = kinds(target)
        if not target_kinds and target.endswith("숲"):
            target_kinds = ["park"]
        scope.name_kind = target_kinds[0] if len(target_kinds) == 1 else "any"
        if not scope.kinds:
            scope.kinds = target_kinds
    return scope


class PlacePolicy:
    def __init__(self, scope=None, user_text="", *, rejected=(), excluded=(), keyword=""):
        self.scope = scope or SearchScope()
        self.user_text = user_text
        self.blocked = 0
        self.rejected = {norm(name) for name in rejected}
        self.excluded = set(excluded)
        self.keyword = keyword

    def forbidden(self, title, kind="any"):
        return norm(title) in self.rejected or kind in self.excluded

    def prepare(self, values, evidence_addresses=()):
        args = SearchArguments.model_validate(values).model_copy()
        query_kinds = kinds(args.query)
        if args.kind == "any":
            allowed = self.scope.kinds or query_kinds
            if len(allowed) == 1:
                args.kind = allowed[0]
            elif self.scope.exact_name and self.scope.name_kind != "any":
                args.kind = self.scope.name_kind
        if self.scope.kinds and args.kind not in self.scope.kinds:
            self.blocked += 1
            return None, "outside_requested_scope"
        if args.kind in self.excluded:
            return None, "excluded_activity_kind"
        target = self.scope.exact_name
        if args.mode == "exact_name" and generic_name(args.name):
            args.mode, args.name = "category", ""
        if target and (self.scope.name_kind in {"any", args.kind} or args.kind == "any"):
            args.mode, args.name, args.query = "exact_name", target, target
        elif args.mode == "exact_name":
            if not args.name or norm(args.name) not in norm(self.user_text):
                self.blocked += 1
                return None, "unconfirmed_place_name"
            args.query = args.name
        elif (
            any(kind != args.kind for kind in query_kinds)
            and args.kind != "any"
            and not (self.keyword and norm(args.query) == norm(self.keyword))
        ):
            self.blocked += 1
            return None, "mixed_activity_query"
        if self.scope.area:
            # A tool argument cannot replace the latest explicit user area with an older one.
            args.area = self.scope.area
        elif args.area:
            evidence = self.user_text + " ".join(evidence_addresses)
            if norm(args.area) not in norm(evidence):
                return None, "unconfirmed_area"
            self.scope.area = args.area
        if self.keyword and args.mode != "exact_name":
            args.query = self.keyword
        if args.mode != "exact_name" and args.area and norm(args.area) not in norm(args.query):
            args.query = f"{args.area} {args.query}"[:100]
        return args, None

    def relevant(self, item, args):
        title, category = plain(item.title), plain(item.category)
        if self.keyword.endswith("주차장") and not re.search(r"주차장|주차시설", title + category):
            return False
        if self.forbidden(title, args.kind):
            return False
        name_match = not args.name or norm(title) == norm(args.name)
        # A park suffix is an explicit name variant, never a café/office with the name as prefix.
        if args.name and args.kind == "park":
            name_match = norm(title) in {norm(args.name), norm(args.name) + "공원"}
        if args.mode == "exact_name" and not name_match:
            return False
        if args.area and not area_matches(args.area, item.address + " " + item.roadAddress):
            return False
        if args.kind != "any":
            source = category or title
            aliases = {
                "restaurant": (
                    "음식점",
                    "식당",
                    "샌드위치",
                    "한식",
                    "양식",
                    "일식",
                    "중식",
                    "분식",
                ),
                "park": ("공원", "수목원", "산책로", "자연", "숲"),
                "museum": ("박물관", "미술관", "전시"),
            }
            if not any(word in source for word in aliases.get(args.kind, WORDS[args.kind])):
                return False
        elif args.mode != "exact_name":
            terms = [norm(t) for t in args.query.split() if len(norm(t)) >= 2]
            if terms and not any(
                t in norm(title + item.address + item.roadAddress + category) for t in terms
            ):
                return False
        return True

    def accepts(self, title, kind="any"):
        scope = self.scope
        if kind == "any" and scope.exact_name and norm(title) == norm(scope.exact_name):
            kind = scope.name_kind
        if self.forbidden(title, kind):
            return False
        if scope.exact_name and scope.name_kind in {"any", kind}:
            return norm(title) in {norm(scope.exact_name), norm(scope.exact_name) + "공원"}
        return not scope.kinds or kind in scope.kinds
