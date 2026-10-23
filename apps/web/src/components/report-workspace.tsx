"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { saveReport } from "@/app/actions/reports";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { RefreshButton } from "@/components/workspace-controls";
import type { DatePlan } from "@/lib/plans";
import type { DateReport, ReportContent } from "@/lib/reports";

export function ReportWorkspace({
  plan,
  userId,
  initialReports,
  initialError,
  today,
}: {
  plan: DatePlan;
  userId: string;
  initialReports: DateReport[];
  initialError: string;
  today: string;
}) {
  const router = useRouter();
  const [refreshing, startRefresh] = useTransition();
  const own = initialReports.find((item) => item.author_id === userId) || null;
  const [report, setReport] = useState(own);
  const [content, setContent] = useState<ReportContent>(
    own?.content || {
      summary: "",
      visits: [],
      actual_cost: null,
      highlights: "",
      next_time: "",
      revisit: null,
    },
  );
  const [visits, setVisits] = useState(content.visits.join("\n"));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();
  const newerOwn = !!own && own.version > (report?.version || 0);
  const request = useRef<{ signature: string; id: string } | null>(null);
  const snapshot = report?.plan_snapshot || plan.published_content;
  const ready = !!report || (!!snapshot && snapshot.date <= today);
  const draft = {
    ...content,
    visits: visits
      .split("\n")
      .map((v) => v.trim())
      .filter(Boolean),
  };
  function save(shared: boolean) {
    const signature = JSON.stringify([draft, shared, report?.version || 0]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    setError("");
    setNotice("");
    startTransition(async () => {
      const result = await saveReport(plan.id, draft, shared, report?.version || 0, requestId);
      if (result.data) {
        setReport(result.data);
        setNotice(
          shared
            ? "이 회고를 상대와 공유했어요."
            : "나만 보는 초안으로 저장했어요. 공유 중이었다면 상대에게 더 이상 표시되지 않아요.",
        );
      } else {
        setError(
          result.status === 409
            ? "다른 화면에서 회고가 바뀌었어요. 입력을 확인한 뒤 최신 페이지를 불러와 주세요."
            : result.error,
        );
        setConflict(result.status === 409);
      }
    });
  }
  return (
    <section className="plan-editor report-workspace">
      <Link className="text-button" href="/plans">
        ← 플랜으로
      </Link>
      <p className="status-chip">{report?.shared ? "공유 중" : "나만 보기"}</p>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR DATE REPORT</p>
          <h1>데이트 회고</h1>
          <p className="muted">
            {snapshot?.title || plan.content.title} · {snapshot?.date || plan.content.date}
          </p>
        </div>
      </PageHeading>
      {snapshot && (
        <details className="plan-review">
          <summary>기준이 된 확정 플랜 보기</summary>
          <p>
            {snapshot.title} · {snapshot.date} · 예산{" "}
            {snapshot.budget === null ? "미정" : `${snapshot.budget.toLocaleString()}원`}
          </p>
          <ol>
            {snapshot.activities.map((a, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: Immutable report snapshot has no activity IDs.
              <li key={`${i}:${a.title}`}>
                {a.time || "시간 미정"} · {a.title}
                {a.place && ` / ${a.place}`}
              </li>
            ))}
          </ol>
          <p className="settings-hint">
            처음 회고를 저장한 확정 내용을 보존해요. 플랜은 실제 방문 기록과 별개예요.
          </p>
        </details>
      )}
      {!ready && (
        <p className="note-panel">플랜을 확정하고 해당 날짜가 되면 회고를 작성할 수 있어요.</p>
      )}
      {ready && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const submitter = (event.nativeEvent as SubmitEvent)
              .submitter as HTMLButtonElement | null;
            save(submitter?.value === "share");
          }}
        >
          <p className="settings-hint">
            {report?.shared ? "현재 상대와 공유 중이에요." : "기본은 나만 보는 초안이에요."} 각자의
            회고는 작성한 사람만 수정할 수 있어요.
          </p>
          <fieldset
            className="meeting-fields"
            disabled={pending || refreshing || conflict || newerOwn || !!initialError}
          >
            <div className="auth-field">
              <label htmlFor="report-summary">오늘의 한 줄</label>
              <textarea
                id="report-summary"
                required
                maxLength={2000}
                rows={3}
                value={content.summary}
                onChange={(e) => setContent({ ...content, summary: e.target.value })}
              />
            </div>
            <details className="optional-fields">
              <summary>방문 장소 (선택)</summary>
              <div className="auth-field">
                <label htmlFor="report-visits">
                  직접 확인한 방문 장소 (한 줄에 하나, 최대 20개)
                </label>
                <textarea
                  id="report-visits"
                  maxLength={4020}
                  rows={3}
                  value={visits}
                  onChange={(e) => setVisits(e.target.value)}
                />
              </div>
            </details>
            <details className="optional-fields">
              <summary>지출 (선택)</summary>
              <div className="auth-field">
                <label htmlFor="report-cost">기록한 총지출 (원, 모르면 비워두기)</label>
                <input
                  id="report-cost"
                  type="number"
                  min={0}
                  max={1000000000}
                  step={1}
                  value={content.actual_cost ?? ""}
                  onChange={(e) =>
                    setContent({
                      ...content,
                      actual_cost: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                />
              </div>
            </details>
            {snapshot?.budget !== null && content.actual_cost !== null && snapshot && (
              <p className="settings-hint">
                계획 예산 대비 {content.actual_cost - snapshot.budget > 0 ? "+" : ""}
                {(content.actual_cost - snapshot.budget).toLocaleString()}원 · 작성자가 입력한
                총액이며 정산 내역은 아니에요.
              </p>
            )}
            <div className="auth-field">
              <label htmlFor="report-highlights">좋았던 순간</label>
              <textarea
                id="report-highlights"
                maxLength={2000}
                rows={3}
                value={content.highlights}
                onChange={(e) => setContent({ ...content, highlights: e.target.value })}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="report-next">다음에 바꾸고 싶은 점</label>
              <textarea
                id="report-next"
                maxLength={2000}
                rows={3}
                value={content.next_time}
                onChange={(e) => setContent({ ...content, next_time: e.target.value })}
              />
            </div>
            <details className="optional-fields">
              <summary>재방문 (선택)</summary>
              <div className="auth-field">
                <label htmlFor="report-revisit">다시 가고 싶나요?</label>
                <select
                  id="report-revisit"
                  value={content.revisit === null ? "" : content.revisit ? "yes" : "no"}
                  onChange={(e) =>
                    setContent({
                      ...content,
                      revisit: e.target.value === "" ? null : e.target.value === "yes",
                    })
                  }
                >
                  <option value="">아직 정하지 않았어요</option>
                  <option value="yes">다시 가고 싶어요</option>
                  <option value="no">다른 곳을 가고 싶어요</option>
                </select>
              </div>
            </details>
            <div className="calendar-toolbar">
              <button className="primary-button" type="submit" value="private">
                {report?.shared ? "공유 철회하고 개인 저장" : "개인 초안 저장"}
              </button>
              <button className="text-button" type="submit" value="share">
                {report?.shared ? "수정한 내용 공유" : "이 내용을 상대와 공유"}
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {(initialError || error) && (
        <p role="alert" className="error-message">
          {initialError || error}
        </p>
      )}
      {newerOwn && (
        <p role="alert" className="note-panel">
          다른 화면에서 저장한 최신 회고가 있어요. 작성 중인 내용은 유지했어요. 필요한 내용을 따로
          보관한 뒤 최신 페이지를 불러와 주세요.
        </p>
      )}
      {(conflict || newerOwn) && (
        <a className="text-button" href={`/plans/${plan.id}/report`}>
          작성 내용을 버리고 최신 페이지 불러오기
        </a>
      )}
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
      <h2>상대가 공유한 회고</h2>
      <RefreshButton
        label="회고 새로고침"
        pending={refreshing}
        disabled={pending}
        onClick={() => startRefresh(() => router.refresh())}
      />
      <p className="settings-hint">상대의 공유 내용을 갱신해요. 작성 중인 내 내용은 유지해요.</p>
      {initialReports
        .filter((item) => item.author_id !== userId)
        .map((item) => (
          <article className="plan-review" key={item.author_id}>
            <p className="eyebrow">상대의 회고 · {item.plan_snapshot.date}</p>
            <h3>{item.content.summary}</h3>
            <p>실제 방문: {item.content.visits.join(" · ") || "아직 기록하지 않았어요"}</p>
            <p>
              기록한 총지출:{" "}
              {item.content.actual_cost === null
                ? "미기록"
                : `${item.content.actual_cost.toLocaleString()}원`}
            </p>
            <p>좋았던 순간: {item.content.highlights || "미작성"}</p>
            <p>다음에는: {item.content.next_time || "미작성"}</p>
            <p>
              다시 방문:{" "}
              {item.content.revisit === null
                ? "미정"
                : item.content.revisit
                  ? "희망"
                  : "다른 곳 희망"}
            </p>
          </article>
        ))}
      {!initialError && !initialReports.some((item) => item.author_id !== userId) && (
        <p className="muted">상대가 공유한 회고가 아직 없어요.</p>
      )}
      <Link className="text-button" href={`/memories?date=${snapshot?.date || plan.content.date}`}>
        이 날짜의 사진 보기
      </Link>
    </section>
  );
}
