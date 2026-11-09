"""Request-local place reads and human replies grounded in verified provider results."""

import json
import re

from we2day_api.ai_place_policy import (
    LABELS,
    SearchArguments,
    area_matches,
    explicit_area,
    kinds,
    norm,
    plain,
    relational_area,
)
from we2day_api.ai_relevance import enrich_candidates
from we2day_api.ai_search_spec import address_fallback, address_hint
from we2day_api.ai_tool_runtime import execute_batch


def private_anchor(area):
    value = norm(area)
    return not kinds(area) and bool(re.fullmatch(r"[가-힣A-Za-z0-9]{0,12}(?:집|회사|직장)", value))


def address_area(address, *, allow_road=False):
    if re.search(r"https?://|naver\.me/", address, re.I):
        return ""
    tokens = re.findall(
        r"(?<![가-힣])([가-힣]{2,12}(?:시|군|구|읍|면|동)(?:\d+가)?)(?=\s|$)",
        plain(address),
    )
    local = tokens[-2:]
    if allow_road and len(local) == 1 and local[0].endswith(("시", "군")):
        road = address_hint(address)
        if road:
            local.append(road)
    return " ".join(local)


def recover_followup_area(directive, history):
    """Repair an unresolved alias using only a recent explicit user area, never model prose."""
    if (
        directive.intent not in {"search", "plan", "select"} and not directive.place_followup
    ) or not (private_anchor(directive.scope.area) or relational_area(directive.scope.area)):
        return
    for message in reversed(history[-50:]):
        if message.role != "user":
            continue
        area = explicit_area(message.content)
        if area:
            if not private_anchor(area) and not relational_area(area):
                directive.scope.area = area
                directive.scope.exact_name, directive.scope.name_kind = "", "any"
                directive.slots["region"] = area
                if directive.state.pending and directive.state.pending.field == "region":
                    directive.state.pending = None
            return
        if re.search(r"(?:집|회사|직장)(?:에서|으로|로|\s*(?:근처|주변))", message.content):
            return


def verified_candidates(session):
    return [
        item
        for item in session.visible_candidates()
        if item.source == "naver" and item.ref in session.fresh_refs
    ]


def candidate_reply(session, followup=""):
    candidates = verified_candidates(session)
    failed = any(r["name"] == "search_places" and r["status"] == "failed" for r in session.reports)
    if not candidates:
        if session.resolution in {"not_allowed", "invalid_arguments", "budget_exhausted"}:
            return "이번 요청의 장소 검색을 실행하지 못했어요. 검색 조건을 다시 확인해 주세요."
        if failed:
            return "장소 검색을 완료하지 못했어요. 잠시 후 다시 시도해 주세요."
        if not session.searches:
            return "아직 실제 장소를 검색하지 못했어요. 검색할 지역이나 장소를 알려주세요."
        return "조건에 맞는 장소를 확인하지 못했어요. 정확한 이름이나 지역을 알려주세요."
    # One representative per requested kind in the saved human reply. The complete
    # ephemeral candidate list remains a separate response, never a stored cache.
    representatives, seen = [], set()
    for item in candidates:
        kind = session.candidate_kinds.get(item.ref, "any")
        if kind not in seen:
            seen.add(kind)
            representatives.append(item)
    heading = (
        "확정된 코스가 아니라, 현재 조건으로 확인한 장소 후보예요."
        if followup == "status"
        else "현재 조건으로 확인한 장소예요."
        if followup == "details"
        else "요청한 범위에 맞는 장소 후보를 확인해 주세요."
    )
    if session.policy.keyword:
        heading = (
            f"‘{session.policy.keyword}’ 검색 후보예요. 실제 메뉴·시설은 지도에서 확인해 주세요."
        )
    if session.resolution == "partial":
        # Candidate cards render the first line; keep partial success visible there too.
        heading = "요청한 조건 중 일부의 후보만 찾았어요."
    rows = [
        f"{i + 1}. {item.title}" + (f" — {item.address}" if item.address else "")
        for i, item in enumerate(representatives[:4])
    ]
    if failed:
        rows.append("일부 활동의 검색은 완료하지 못했어요.")
    elif session.resolution == "partial":
        rows.append("일부 활동은 조건에 맞는 후보를 확인하지 못했어요.")
    if any(item.match == "related" for item in candidates):
        rows.append(
            "관련 후보는 업종을 참고한 제안이에요. "
            "요청한 메뉴·시설 등은 지도에서 확인하고 직접 선택해 주세요."
        )
    return "\n".join([heading, *rows])


def claims_place_search(reply):
    # Positive completion claims only; an honest '검색하지 못했어요' must stay intact.
    return bool(
        re.search(
            r"찾았(?:어요|습니다|어)|찾아봤(?:어요|습니다|어)|검색했(?:어요|습니다|어)|검색(?:을)?\s*완료했|장소(?:를|들을)?\s*확인했|(?:저장한?\s*장소|장소가|검색\s*결과).{0,25}(?:확인되지|확인할\s*수\s*없|없어요|찾지\s*못)",
            reply,
        )
    )


async def read_candidate_request(directive, session, io):
    """Use the existing bounded tool executor; never discover unselected records."""
    if directive.reply or (
        directive.intent not in {"search", "plan", "select"} and not directive.place_followup
    ):
        return
    if (
        directive.place_followup
        and session.previous_plan
        and not session.policy.keyword
        and not getattr(session, "followup_of_search", False)
    ):
        places = [a.place for a in session.previous_plan.activities if a.place]
        directive.reply = (
            (
                "현재 대화에서 만든 코스 제안이에요.\n"
                if directive.place_followup == "status"
                else "현재 코스 제안에 있는 장소예요.\n"
            )
            + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(places))
            if places
            else "현재 코스에는 확인할 장소가 없어요. 장소를 선택해 주세요."
        )
        return
    area = session.policy.scope.area
    if relational_area(area):
        directive.ask("region", "검색할 동네나 기준 장소를 알려주세요.", resume="search")
        session.resolution = "unresolved"
        return
    if session.selected and "lookup_selected_places" in session.allowed_tools:
        await execute_batch(
            session, [{"function": {"name": "lookup_selected_places", "arguments": "{}"}}], io
        )
        selected = session.selected_candidates()
        if not selected:
            if any(r["status"] == "failed" for r in session.reports):
                session.resolution = "failed"
                directive.reply = "선택한 장소를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."
                return
            session.resolution = "selection_required" if not session.reports else "unresolved"
            directive.ask(
                "region",
                "선택한 장소를 현재 목록에서 확인할 수 없어요. 다시 선택하거나 동네를 알려주세요.",
                resume="search",
            )
            return
        if getattr(session, "include_only", False):
            session.direct_final = True
            session.resolution = "ready"
            return
        if (
            not session.policy.scope.kinds
            and not session.policy.scope.exact_name
            and not session.policy.queries
            and session.initial_activities is None
            and not directive.place_followup
        ):
            # A location answer is not an activity choice. Keep the verified coarse
            # location and ask for the missing target before trying another search.
            if (
                len(selected) == 1
                and session.selected_usage.get(selected[0].ref) == "anchor"
                and (local := address_area(selected[0].address, allow_road=True))
            ):
                session.policy.scope.area = local
                directive.slots["region"] = local
            session.resolution = "unresolved"
            directive.ask(
                "target",
                "선택한 장소를 기준으로 어떤 활동을 하고 싶나요? 원하는 활동을 알려주세요.",
                resume="plan" if directive.intent == "plan" else "search",
            )
            return
        if getattr(session, "anchor_search", False):
            explicit = [p for p in selected if session.selected_usage.get(p.ref) == "anchor"]
            named = [p for p in selected if norm(p.title) == norm(area)]
            anchors = explicit or named or (selected if len(selected) == 1 else [])
            areas = {address_area(p.address) for p in anchors} - {""}
            if len(anchors) != 1 or len(areas) != 1:
                session.resolution = "ambiguous" if len(anchors) != 1 else "unresolved"
                directive.ask(
                    "region",
                    "주변을 검색할 기준 장소 한 곳의 동네 주소를 확인해 주세요. "
                    "공유 링크만으로는 동네를 알 수 없어요.",
                    resume="search",
                )
                return
            area = areas.pop()
            # A city-only road address is not a neighborhood or a radius lookup.
            if len(area.split()) == 1 and area.endswith(("시", "군")):
                fallback = next(
                    (
                        value
                        for value in getattr(session, "area_fallbacks", [])
                        if value
                        and not private_anchor(value)
                        and len(value.split()) > 1
                        and area_matches(value.split()[0], area)
                    ),
                    "",
                )
                road_area = (
                    address_area(anchors[0].address, allow_road=True)
                    if session.selected_usage.get(anchors[0].ref) == "anchor"
                    else area
                )
                if not fallback and road_area == area:
                    session.resolution = "unresolved"
                    directive.ask(
                        "region",
                        "선택한 주소에서 동네를 확인할 수 없어요. 검색할 동네를 알려주세요.",
                        resume="search",
                    )
                    return
                area = fallback or road_area
                directive.notices.append(
                    "주소에서 동네를 확인하지 못해, 이미 정한 지역에서 후보를 찾았어요."
                    if fallback
                    else "선택한 주소의 도로명을 기준으로 후보를 찾아요. 실제 반경 검색은 아니에요."
                )
            session.policy.scope.area = area
            directive.slots["region"] = area
    if private_anchor(area):
        if not session.selected:
            session.resolution = "selection_required"
            directive.ask(
                "region",
                (
                    "아직 실제 장소 후보를 확인하지 못했어요. "
                    if directive.place_followup == "status"
                    else ""
                )
                + "집 별칭만으로는 위치를 알 수 없어요. "
                "‘저장 장소’에서 해당 장소를 체크하거나 동네를 알려주세요.",
                resume="plan" if directive.intent == "plan" else "search",
            )
            return
        anchors = [p for p in session.selected_candidates() if norm(p.title) == norm(area)]
        areas = {address_area(p.address) for p in anchors} - {""}
        if len(areas) != 1:
            session.resolution = "unresolved"
            directive.ask(
                "region",
                "선택한 장소의 동네 주소를 확인할 수 없어요. 검색할 동네나 지역을 알려주세요.",
                resume="search",
            )
            return
        session.policy.scope.area = area = areas.pop()
        directive.slots["region"] = area
    initial_plan = directive.intent == "plan" and (
        session.initial_activities is not None or session.requested_activities is not None
    )
    if directive.intent != "search" and not directive.place_followup and not initial_plan:
        return
    if not area and not session.policy.scope.exact_name:
        # A selected place URL is not a geocoding result or nearby-search coordinate.
        if session.selected:
            directive.ask("region", "선택한 장소 근처의 어느 동네에서 찾아볼까요?", resume="search")
        else:
            directive.ask(
                "region",
                "어느 동네에서 찾아볼까요? 자주 가는 곳을 선택하거나 동네를 알려주세요.",
                resume="plan" if directive.intent == "plan" else "search",
            )
        return
    requested = session.policy.scope.kinds or (
        [session.policy.scope.name_kind] if session.policy.scope.exact_name else []
    )
    if not requested or len(requested) > 4:
        return
    calls = []
    queries = session.policy.queries or [
        (k, session.policy.keyword or f"{area} {LABELS.get(k, '장소')}", "") for k in requested
    ]
    for kind, query, _ in queries:
        name = session.policy.scope.exact_name
        exact = bool(name and session.policy.scope.name_kind in {kind, "any"})
        args = {
            "query": name if exact else query,
            "mode": "exact_name" if exact else "category",
            "name": name if exact else "",
            "kind": kind,
            "area": area,
        }
        calls.append(
            {
                "function": {
                    "name": "search_places",
                    "arguments": json.dumps(args, ensure_ascii=False),
                }
            }
        )
    await execute_batch(session, calls, io)
    fallback = address_fallback(getattr(session, "search_anchor", None))
    if (
        fallback
        and not verified_candidates(session)
        and all(r["status"] == "ok" for r in session.reports)
    ):
        extra = [(k, f"{fallback} {target}", target) for k, _, target in session.policy.queries]
        session.policy.queries.extend(extra)
        for kind, query, _ in extra:
            if len(session.searches) >= 4:
                break
            await execute_batch(
                session,
                [
                    {
                        "function": {
                            "name": "search_places",
                            "arguments": json.dumps(
                                {
                                    "query": query,
                                    "mode": "category",
                                    "kind": kind,
                                    "area": area,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    }
                ],
                io,
            )
        directive.notices.append(
            "기준 장소명으로 결과를 찾지 못해 저장된 주소의 도로·동네 범위에서 검색했어요. "
            "실제 거리와 이용 조건은 지도에서 확인해 주세요."
        )
    await enrich_candidates(session, io)
    failed = any(r["status"] == "failed" for r in session.reports)
    covered = set(session.candidate_kinds.values())
    complete = set(requested) <= covered
    if session.policy.queries:
        # Coverage belongs to the requested queries, not the provider's genre.
        # Two different free-form targets can legitimately have the same genre.
        required = {(k, t) for k, _, t in session.policy.queries}
        found = set()
        for key, items in session.searches.items():
            if not items:
                continue
            matched = session.policy.query_target(SearchArguments.model_validate_json(key))
            if matched:
                found.add(matched)
        complete = required <= found
    if session.resolution not in {"not_allowed", "invalid_arguments", "budget_exhausted"}:
        session.resolution = (
            ("partial" if covered else "failed")
            if failed
            else "ready"
            if complete
            else "partial"
            if covered
            else "empty"
        )
    direct_kinds = {
        session.candidate_kinds.get(c.ref, "any")
        for c in session.candidates.values()
        if c.match != "related"
    }
    if (
        initial_plan
        and complete
        and set(requested) <= direct_kinds
        and not any(c.match == "related" for c in verified_candidates(session))
    ):
        # Typed intake already determines these reads. Compose once from real evidence
        # instead of asking the model to rediscover the search arguments.
        session.direct_final = True
    else:
        directive.reply = candidate_reply(session, directive.place_followup)
