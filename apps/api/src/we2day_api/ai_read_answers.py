"""Factual read rendering and fair bounded composition, without another inference."""


def join_replies(parts, limit=4000):
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len("\n\n".join(parts)) <= limit:
        return "\n\n".join(parts)
    allowance = (limit - 2 * (len(parts) - 1)) // len(parts)
    suffix = "\n… 일부 내용만 표시했어요."
    return "\n\n".join(
        p if len(p) <= allowance else p[: allowance - len(suffix)].rstrip() + suffix for p in parts
    )


def weather_reply(items, errors=()):
    def measured(value, unit):
        return "미확인" if value is None else f"{value:g}{unit}"

    summary = "\n".join(
        f"{w.date} {w.city} 예보 · 최저 {measured(w.min_celsius, '°C')} / "
        f"최고 {measured(w.max_celsius, '°C')} · "
        f"강수 확률 {measured(w.rain_probability_percent, '%')}"
        for w in items
    ) + ("\n도시 대표 지점의 일별 예보예요." if items else "")
    if errors:
        notice = (
            "요청한 날짜는 예보 제공 범위를 벗어나 날씨를 확인할 수 없어요."
            if "forecast_out_of_range" in errors
            else "날씨를 조회할 도시를 확인해 주세요."
            if "city_not_found" in errors
            else "일부 날씨를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."
        )
        summary = join_replies([summary, notice])
    return summary


def selected_reply(session):
    selected = session.selected_candidates()
    if selected:
        return "선택한 장소 조회\n" + "\n".join(
            f"• {p.title}" + (f" — {p.address}" if p.address else "") for p in selected
        )
    if any(
        r["name"] == "lookup_selected_places" and r["status"] == "failed" for r in session.reports
    ):
        return "선택한 장소를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."
    return "선택한 장소 조회\n현재 선택에서 확인된 장소가 없어요. 저장 장소를 다시 선택해 주세요."
