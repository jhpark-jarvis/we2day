"""Request-local place reads and human replies grounded in verified provider results."""

import json
import re

from we2day_api.ai_place_policy import LABELS, explicit_area, kinds, norm, plain
from we2day_api.ai_tool_runtime import execute_batch


def private_anchor(area):
    value = norm(area)
    return not kinds(area) and bool(re.fullmatch(r"[가-힣A-Za-z0-9]{0,12}(?:집|회사|직장)", value))


def address_area(address):
    if re.search(r"https?://|naver\.me/", address, re.I):
        return ""
    tokens = re.findall(
        r"(?<![가-힣])([가-힣]{2,12}(?:시|군|구|읍|면|동)(?:\d+가)?)(?=\s|$)",
        plain(address),
    )
    return " ".join(tokens[-2:])


def recover_followup_area(directive, history):
    """Repair an unresolved alias using only a recent explicit user area, never model prose."""
    if not directive.place_followup or not private_anchor(directive.scope.area):
        return
    for message in reversed(history[-10:]):
        if message.role != "user":
            continue
        area = explicit_area(message.content)
        if area:
            if not private_anchor(area):
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
    rows = [
        f"{i + 1}. {item.title}" + (f" — {item.address}" if item.address else "")
        for i, item in enumerate(representatives[:4])
    ]
    missing = set(session.policy.scope.kinds) - set(session.candidate_kinds.values())
    if failed:
        rows.append("일부 활동의 검색은 완료하지 못했어요.")
    elif missing:
        rows.append("일부 활동은 조건에 맞는 후보를 확인하지 못했어요.")
    return "\n".join([heading, *rows])


def claims_place_search(reply):
    # Positive completion claims only; an honest '검색하지 못했어요' must stay intact.
    return bool(
        re.search(
            r"찾았(?:어요|습니다|어)|찾아봤(?:어요|습니다|어)|검색했(?:어요|습니다|어)|검색(?:을)?\s*완료했|장소(?:를|들을)?\s*확인했",
            reply,
        )
    )


async def read_candidate_request(directive, session, io):
    """Use the existing bounded tool executor; never discover unselected records."""
    if directive.reply or (
        directive.intent not in {"search", "plan", "select"} and not directive.place_followup
    ):
        return
    if directive.place_followup and session.previous_plan:
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
    if private_anchor(area):
        if not session.selected:
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
        session.allowed_tools.add("lookup_selected_places")
        await execute_batch(
            session, [{"function": {"name": "lookup_selected_places", "arguments": "{}"}}], io
        )
        anchors = [
            p
            for p in session.candidates.values()
            if p.source == "selected" and norm(p.title) == norm(area)
        ]
        areas = {address_area(p.address) for p in anchors} - {""}
        if len(areas) != 1:
            directive.ask(
                "region",
                "선택한 장소의 동네 주소를 확인할 수 없어요. 검색할 동네나 지역을 알려주세요.",
                resume="search",
            )
            return
        session.policy.scope.area = area = areas.pop()
        directive.slots["region"] = area
    initial_plan = directive.intent == "plan" and session.initial_activities is not None
    if directive.intent != "search" and not directive.place_followup and not initial_plan:
        return
    if not area and not session.policy.scope.exact_name:
        # A selected place URL is not a geocoding result or nearby-search coordinate.
        if session.selected:
            directive.ask("region", "선택한 장소 근처의 어느 동네에서 찾아볼까요?", resume="search")
        return
    requested = session.policy.scope.kinds or (
        [session.policy.scope.name_kind] if session.policy.scope.exact_name else []
    )
    if not requested or len(requested) > 4:
        return
    calls = []
    for kind in requested:
        name = session.policy.scope.exact_name
        exact = bool(name and session.policy.scope.name_kind in {kind, "any"})
        args = {
            "query": name if exact else f"{area} {LABELS.get(kind, '장소')}",
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
    if initial_plan and set(requested) <= set(session.candidate_kinds.values()):
        # Typed intake already determines these reads. Compose once from real evidence
        # instead of asking the model to rediscover the search arguments.
        session.direct_final = True
    else:
        directive.reply = candidate_reply(session, directive.place_followup)
