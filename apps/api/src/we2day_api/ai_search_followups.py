"""User-grounded search refinements and terminal answers, never background promises."""

import re

from we2day_api.ai_place_policy import explicit_area, generic_name, kinds, norm, relational_area


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
            r"^" + re.escape(area) + r"\s*(?:근처|주변|인근|주위)?\s*", "", query
        ).strip()
    detected = kinds(query)
    food = bool(
        re.search(
            r"요리|음식|국물|국밥|찌개|라멘|라면|우동|쌀국수|파스타|피자|초밥|고깃집|샌드위치",
            query,
        )
    )
    if generic_name(query) and not food:
        return None
    kind = (
        "cafe"
        if food and "cafe" in detected and set(detected) <= {"cafe", "restaurant"}
        else detected[0]
        if len(detected) == 1
        else "restaurant"
        if food and not detected
        else None
    )
    return {"version": 1, "query": query, "kind": kind} if kind else None


def parking_request(text, previous=None):
    value = search_phrase(text)
    if value.startswith("선택한 장소:"):
        return None
    if re.search(r"[\"'‘“]|제목|기능|검색하지|찾지|필요\s*없|주차장.*(?:말고|제외|빼|없애)", value):
        return None
    direct = bool(re.search(r"주차장|주차\s*시설", value))
    pending = isinstance(previous, dict) and previous.get("query", "").endswith("주차장")
    if not direct and not pending:
        return None
    if not direct and (
        continuation(value) or re.search(r"찾|추천|검색|바꿔|변경|예산|날짜|고마|감사|취소", value)
    ):
        return None
    prefix = re.split(r"주변|근처|인근|주위|주차장|주차\s*시설", value)[0]
    return {
        "kinds": kinds(prefix),
        "relative": pending
        or bool(re.search(r"(?<!\d)[1-8]\s*번", prefix))
        or bool(
            re.search(r"이후\s*일정|선택한|고른|식사\s*장소|식당|카페|거기|그곳|그\s*주변", prefix)
        ),
        "area": explicit_area(value),
        "number": re.search(r"(?<!\d)([1-8])\s*번", prefix),
        "anchor": prefix.strip(),
    }


def parking_scope(request, proposal, current_area):
    """Resolve an explicit course anchor, never use relational words as geography."""
    activities = list(proposal.activities) if proposal else []
    named = [
        a
        for a in activities
        if norm(request["anchor"]) in {norm(a.title), norm(re.split(r"\s*\(", a.place)[0])}
    ]
    relative = request["relative"] or bool(named)
    if request["area"] and not relative:
        return request["area"], "주차장", ""
    if request["number"]:
        index = int(request["number"][1]) - 1
        activities = activities[index : index + 1]
    elif request["kinds"]:
        activities = [a for a in activities if any(k in kinds(a.title) for k in request["kinds"])]
    elif named:
        activities = named
    if not relative and not request["kinds"]:
        return current_area, "주차장", ""
    if len(activities) != 1 or not activities[0].place:
        return (
            current_area,
            "주차장",
            "어느 장소 주변의 주차장을 찾을까요? 활동 번호나 장소를 알려주세요.",
        )
    place = activities[0].place
    name = re.split(r"\s*\(|\s+·\s+", place, maxsplit=1)[0].strip()
    if re.search(r"https?://", name):
        return (
            current_area,
            "주차장",
            "기준 장소의 이름이나 동네를 알려주세요. 공유 링크만으로 주변 위치를 확인할 수 없어요.",
        )
    name = " ".join(re.sub(r"[^가-힣A-Za-z0-9 ]", " ", name).split())
    if not name:
        return current_area, "주차장", "기준 장소의 이름이나 동네를 알려주세요."
    if not current_area or relational_area(current_area):
        address = re.search(r"\(([^()]*)\)", place)
        if address:
            tokens = re.findall(r"[가-힣]{2,12}(?:시|군|구|읍|면|동)(?:\d+가)?(?=\s|$)", address[1])
            current_area = " ".join(tokens[-2:]) or current_area
    return current_area, f"{name[:44]} 주차장", ""


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


def parking_fallback(query, proposal):
    if not query.endswith(" 주차장") or not proposal:
        return ""
    for activity in proposal.activities:
        name = re.split(r"\s*\(|\s+·\s+", activity.place, maxsplit=1)[0].strip()
        name = " ".join(re.sub(r"[^가-힣A-Za-z0-9 ]", " ", name).split())
        if query != f"{name[:44]} 주차장":
            continue
        address = re.search(r"\(([^()]*)\)", activity.place)
        if not address:
            return ""
        roads = [
            t for t in address[1].split() if re.fullmatch(r"[가-힣A-Za-z0-9]+(?:대로|로|길)", t)
        ]
        neighborhoods = [
            t for t in address[1].split() if re.fullmatch(r"[가-힣]+(?:동|읍|면)(?:\d+가)?", t)
        ]
        anchor = next(iter(roads or neighborhoods[-1:]), "")
        return f"{anchor} 주차장" if anchor else ""
    return ""


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
