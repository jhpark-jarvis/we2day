import type { PlanContent } from "@/lib/plans";
import { reviewPlan } from "@/lib/timeline";

export function PlanChecks({ content }: { content: PlanContent }) {
  const result = reviewPlan(content);
  const money = (value: number) => `${value.toLocaleString("ko-KR")}원`;
  return (
    <section className="note-panel" aria-label="플랜 시간·예산 점검">
      <h2>시간·예산 살펴보기</h2>
      {!content.activities.length ? (
        <p>활동을 추가하면 시작 시각과 예상 비용을 살펴볼 수 있어요.</p>
      ) : (
        <>
          <p>
            {result.total === null ? "확인한 예상 비용" : "예상 비용 합계"} {money(result.known)}
            {content.budget !== null && ` · 전체 예산 ${money(content.budget)}`}
          </p>
          {result.unknown > 0 && (
            <p>비용 미정 {result.unknown}개 · 전체 비용과 예산 충족 여부는 아직 알 수 없어요.</p>
          )}
          {result.overBudget !== null && result.overBudget > 0 && (
            <p>확인한 비용만으로 예산보다 {money(result.overBudget)} 많아요.</p>
          )}
          {result.budgetIsComplete && result.overBudget === 0 && (
            <p>입력한 예상 비용이 전체 예산 이내예요.</p>
          )}
          {result.unknownTimes > 0 && <p>시작 시각 미정 {result.unknownTimes}개</p>}
          <ul>
            {result.timing.map((item) => (
              <li key={`${item.previous}:${item.index}`}>
                활동 {item.index + 1}의 시작 시각이 활동 {item.previous + 1}
                {item.same ? "과 같아요." : "보다 일러요."} 순서와 시각을 확인해 주세요.
              </li>
            ))}
          </ul>
          <p className="settings-hint">
            활동 소요 시간·이동 시간·장소 영업시간은 직접 확인해 주세요. 입력한 순서는 그대로
            유지돼요.
          </p>
        </>
      )}
    </section>
  );
}
