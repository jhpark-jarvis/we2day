"""User-grounded search refinements and terminal answers, never background promises."""

import re

from we2day_api.ai_place_policy import explicit_area, generic_name, kinds, norm


def search_phrase(text):
    """Normalize discourse only for search parsing; preserve the original message."""
    return re.sub(
        r"^(?:(?:흠|음|어|아|그럼|그러면|혹시|대신|좋아|일단)(?:[.,…!?]+|\s+)\s*)+",
        "",
        text.strip(),
    )


def refinement(text):
    # These are search requests, not claims that a venue serves a particular menu.
    if re.search(r"[\"'‘“]|제목|날짜|예산|시간|이동|추가\s*조건|기능|코스|플랜|날씨", text):
        return None
    value = search_phrase(text)
    match = re.fullmatch(
        r"([가-힣A-Za-z0-9 ]{2,50}?)\s*(?:은|는|을|를|이|가|도)?\s*(?:좀\s*)?"
        r"(?:없나|없을까|있나|있을까|먹고\s*싶|가고\s*싶|찾아\s*줘|추천해\s*줘)"
        r"(?:요|해|어|어요|싶어)?[.!?？\s]*",
        value,
    )
    if not match:
        return None
    query = match[1].strip()
    area = explicit_area(query)
    if area:
        query = re.sub(
            r"^" + re.escape(area) + r"\s*(?:근처|주변|인근|주위)?(?:에서|에)?\s*", "", query
        ).strip()
    query = re.sub(r"^(?:근처|주변|인근|주위)(?:에서|에)?\s*", "", query).strip()
    detected = kinds(query)
    if generic_name(query):
        return None
    specific = [k for k in detected if k != "restaurant"]
    kind = specific[0] if len(specific) == 1 else detected[0] if len(detected) == 1 else None
    return {"version": 1, "query": query, "kind": kind} if kind else None


def saved_refinement(context, scope):
    value = context.get("place_search")
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    query, kind = value.get("query"), value.get("kind")
    if (
        not isinstance(query, str)
        or not re.fullmatch(r"[가-힣A-Za-z0-9 ]{2,50}", query)
        or kind not in scope.kinds
        or len(scope.kinds) != 1
        or scope.exact_name
    ):
        return None
    return {"version": 1, "query": query, "kind": kind}


def result_question(text):
    return bool(
        re.fullmatch(
            r"(?:이제|그래서|그럼|혹시)?(?:찾았어|찾았나요|찾았니|검색됐어|검색했어|결과나왔어|결과는|어떻게됐어|다됐어)(?:요)?",
            re.sub(r"[\s.!?？]", "", text),
        )
    )


def continuation(text):
    return result_question(text) or bool(
        re.fullmatch(
            r"(?:다시|한번더|한번만더)(?:해줘|찾아줘|추천해줘|해볼래|해)?",
            re.sub(r"[\s.!?？]", "", text),
        )
    )


def pending_promise(reply):
    plain = re.sub(r"[\"'‘“][^\"'’”]*[\"'’”]", "", reply)
    return bool(
        re.search(
            r"(?:찾을게|검색할게|확인할게|정리할게|진행할게|알려드릴게)"
            r"|(?:검색|확인|정리|준비|생성)(?:하고\s*있|\s*중)"
            r"|찾는\s*중|"
            r"(?:찾아|검색해|확인해|정리해|만들어|알아봐|준비해)\s*(?:볼게|드릴게|줄게|둘게|보겠|드리겠)"
            r"|(?:잠시만?|조금만|잠깐)\s*기다려|기다려\s*주(?:세요|십시오)",
            plain,
        )
    )


def grounded_query(query, latest):
    return bool(
        query and re.fullmatch(r"[가-힣A-Za-z0-9 ]{2,50}", query) and norm(query) in norm(latest)
    )
