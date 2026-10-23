"use client";
import { Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { drawRoulette, readRouletteDraws, saveRoulette } from "@/app/actions/together";
import { RefreshButton } from "@/components/workspace-controls";
import type { RouletteDraw, RouletteWheel } from "@/lib/roulette";
import { zonedTimestamp } from "@/lib/timezones";
export function RouletteEditor({
  wheel: initialWheel,
  draws,
}: {
  wheel: RouletteWheel | null;
  draws: RouletteDraw[];
}) {
  const router = useRouter();
  const [wheel, setWheel] = useState(initialWheel);
  const [id] = useState(() => wheel?.id || crypto.randomUUID());
  const [title, setTitle] = useState(wheel?.title || "");
  const [lines, setLines] = useState(wheel?.candidates.join("\n") || "");
  const [archived, setArchived] = useState(wheel?.archived || false);
  const [history, setHistory] = useState(draws);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, start] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  const drawRequest = useRef<string | null>(null);
  const candidates = lines
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const dirty =
    !wheel ||
    title.trim() !== wheel.title ||
    JSON.stringify(candidates) !== JSON.stringify(wheel.candidates) ||
    archived !== wheel.archived;
  function draw() {
    if (!wheel || dirty || wheel.archived) return;
    if (!drawRequest.current) drawRequest.current = crypto.randomUUID();
    const requestId = drawRequest.current;
    start(async () => {
      const result = await drawRoulette(id, wheel.version, requestId);
      if (result.data) {
        setHistory((current) => [
          result.data as RouletteDraw,
          ...current.filter((v) => v.id !== result.data?.id),
        ]);
        drawRequest.current = null;
        setError("");
      } else {
        setError(result.error);
        setConflict(result.status === 409);
      }
    });
  }
  const editorForm = (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const signature = JSON.stringify([title, candidates, archived, wheel?.version || 0]);
        if (request.current?.signature !== signature)
          request.current = { signature, id: crypto.randomUUID() };
        const requestId = request.current.id;
        start(async () => {
          const result = await saveRoulette(
            id,
            title,
            candidates,
            archived,
            wheel?.version || 0,
            requestId,
          );
          if (result.data) {
            setWheel(result.data);
            setError("");
            router.push(`/roulette/${id}`);
            router.refresh();
          } else {
            setError(result.error);
            setConflict(result.status === 409);
          }
        });
      }}
    >
      <fieldset className="meeting-fields" disabled={pending || conflict}>
        <div className="auth-field">
          <label htmlFor="roulette-title">룰렛 이름</label>
          <input
            id="roulette-title"
            required
            maxLength={100}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="auth-field">
          <label htmlFor="roulette-candidates">후보 (한 줄에 하나, 2~20개)</label>
          <textarea
            id="roulette-candidates"
            required
            rows={6}
            maxLength={2200}
            value={lines}
            onChange={(e) => setLines(e.target.value)}
          />
        </div>
        <p className="settings-hint">
          후보는 각각 100자까지, 같은 이름은 한 번만 적어요. 수정 후 저장해야 새 후보로 뽑을 수
          있어요.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          룰렛 보관 (해제하면 복원)
        </label>
        <button className="primary-button" type="submit">
          룰렛 저장
        </button>
      </fieldset>
    </form>
  );
  return (
    <div className="plan-editor">
      {wheel && (
        <section aria-label="저장된 후보 뽑기">
          <RouletteDisc candidates={wheel.candidates} />
          <ol className="checklist-preview">
            {wheel.candidates.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ol>
          <button
            type="button"
            className="primary-button"
            disabled={pending || conflict || dirty || wheel.archived}
            onClick={draw}
          >
            {history.length ? "다시 뽑기" : "하나 뽑기"}
          </button>
          {dirty && <p className="settings-hint">작성한 변경 내용을 저장하면 뽑을 수 있어요.</p>}
          {wheel.archived && (
            <p className="settings-hint">보관을 해제하고 저장하면 다시 뽑을 수 있어요.</p>
          )}
          {history[0] && (
            <p role="status" className="roulette-result">
              선택 결과 · {history[0].candidates[history[0].selected_index]}
            </p>
          )}
          <RefreshButton
            label="최신 결과 불러오기"
            pending={pending}
            onClick={() =>
              start(async () => {
                try {
                  const result = await readRouletteDraws(id);
                  if (result.data) {
                    setHistory(result.data);
                    setError("");
                  } else setError(result.error);
                } catch {
                  setError("결과를 불러오지 못했어요. 작성 중인 후보는 유지돼요.");
                }
              })
            }
          />
        </section>
      )}
      {wheel ? (
        <details className="editor-disclosure">
          <summary>후보 수정</summary>
          {editorForm}
        </details>
      ) : (
        editorForm
      )}
      {error && (
        <p role="alert" className="error-message">
          {error}
          {conflict ? " 작성 내용은 유지돼요. 최신 결과를 확인해 주세요." : ""}
        </p>
      )}
      {conflict && (
        <button
          className="text-button"
          type="button"
          onClick={() => {
            if (window.confirm("작성 중인 후보를 버리고 저장된 내용을 불러올까요?"))
              window.location.reload();
          }}
        >
          작성 내용을 버리고 최신 룰렛 불러오기
        </button>
      )}
      {history.length > 0 && (
        <section>
          <h2>함께 뽑은 기록</h2>
          <ol className="roulette-history">
            {history.map((draw) => (
              <li key={draw.id}>
                <p>{draw.candidates[draw.selected_index]}</p>
                <small>{zonedTimestamp(draw.drawn_at, "Asia/Seoul")} · 한국 기준</small>
                <details>
                  <summary>당시 후보 {draw.candidates.length}개 보기</summary>
                  <ul>
                    {draw.candidates.map((v) => (
                      <li key={v}>{v}</li>
                    ))}
                  </ul>
                </details>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
function RouletteDisc({ candidates }: { candidates: string[] }) {
  return (
    <svg
      viewBox="0 0 240 240"
      className="roulette-disc"
      role="img"
      aria-label="후보마다 같은 크기로 나눈 선택 룰렛"
    >
      {candidates.map((candidate, index) => {
        const start = (index * 2 * Math.PI) / candidates.length - Math.PI / 2,
          end = ((index + 1) * 2 * Math.PI) / candidates.length - Math.PI / 2,
          mid = (start + end) / 2;
        return (
          <g key={candidate}>
            <path
              d={`M120 120 L${120 + 110 * Math.cos(start)} ${120 + 110 * Math.sin(start)} A110 110 0 0 1 ${120 + 110 * Math.cos(end)} ${120 + 110 * Math.sin(end)} Z`}
              fill={index % 2 ? "var(--line)" : "var(--accent)"}
              stroke="var(--surface)"
              strokeWidth="2"
            />
            <text
              x={120 + 74 * Math.cos(mid)}
              y={125 + 74 * Math.sin(mid)}
              textAnchor="middle"
              fill={index % 2 ? "var(--foreground)" : "white"}
            >
              {index + 1}
            </text>
          </g>
        );
      })}
      <circle cx="120" cy="120" r="22" fill="var(--surface)" />
      <text x="120" y="126" textAnchor="middle" fill="var(--foreground)">
        ?
      </text>
    </svg>
  );
}

export function RouletteCreate() {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        type="button"
        ref={trigger}
        className="icon-button roulette-create-trigger"
        aria-label="룰렛 만들기"
        title="룰렛 만들기"
        aria-haspopup="dialog"
        onClick={() => dialog.current?.showModal()}
      >
        <Plus size={22} aria-hidden="true" />
      </button>
      <dialog
        ref={dialog}
        className="roulette-create-dialog"
        onClose={() => trigger.current?.focus()}
        aria-labelledby="roulette-create-title"
      >
        <div className="section-heading roulette-create-heading">
          <h2 id="roulette-create-title">룰렛 만들기</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="룰렛 작성 닫기"
            title="닫기"
            onClick={() => dialog.current?.close()}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <RouletteEditor wheel={null} draws={[]} />
      </dialog>
    </>
  );
}
