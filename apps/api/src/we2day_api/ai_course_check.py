"""Deterministic current-proposal inspection. No model-supplied plan or business I/O."""

from we2day_api.ai_tools import check_course, course_summary


def inspect_current_course(proposal):
    if proposal is None:
        return "먼저 코스 초안을 만들어 주세요. 현재 대화의 초안만 점검할 수 있어요.", [
            {"name": "validate_course", "status": "needs_input", "count": 0}
        ]
    summary = course_summary(proposal)
    checks = check_course(proposal)
    lines = ["현재 코스 점검"]
    total = summary["known_cost_total"]
    lines.append(f"입력된 활동비 합계: {total:,}원" if total is not None else "입력된 활동비: 미정")
    if proposal.budget is not None:
        lines.append(f"전체 예산: {proposal.budget:,}원")
    if summary["unknown_cost_count"]:
        lines.append(f"비용 미정: {summary['unknown_cost_count']}개 활동")
    if summary["untimed_activity_count"]:
        lines.append(f"시각 미정: {summary['untimed_activity_count']}개 활동")
    lines.extend("• " + issue for issue in checks)
    if not checks:
        lines.append("확인된 검사 항목에서 추가 문제는 없어요.")
    lines.append("실제 가격·영업·이동/체류 시간은 확인하지 않았어요.")
    return "\n".join(lines), [{"name": "validate_course", "status": "ok", "count": len(checks)}]
