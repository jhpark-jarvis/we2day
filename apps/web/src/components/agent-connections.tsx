"use client";
import { Copy, KeyRound, RefreshCw, X } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import {
  agentConnections,
  createAgentConnection,
  revokeAgentConnection,
} from "@/app/actions/agents";

export type AgentConnection = {
  can_manage?: boolean;
  id: string;
  label: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
};
export function AgentConnections({
  initial,
  initialError,
  endpoint,
}: {
  initial: AgentConnection[];
  initialError: string;
  endpoint: string;
}) {
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const [items, setItems] = useState(initial);
  const [canManage, setCanManage] = useState(false);
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState<{ id: string; key: string } | null>(null);
  const [notice, setNotice] = useState(initialError);
  const [pending, start] = useTransition();
  async function refresh() {
    const result = await agentConnections();
    if (result.data) setItems(result.data);
    if (result.error) setNotice(result.error);
  }
  return (
    <section aria-label="에이전트 연결 관리" className="settings-section">
      <div className="section-heading">
        <h2>연결 키</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="연결 목록 새로고침"
          disabled={pending}
          onClick={() =>
            start(async () => {
              setNotice("");
              await refresh();
            })
          }
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <p className="muted">
        기본 권한은 공동 일정·코스 조회와 새 초안 작성이에요. 관리 권한은 새 키에만 선택할 수
        있어요.
      </p>
      <p className="settings-hint">
        키는 30일 동안 유효하며 계정당 최대 5개예요. 연결할 에이전트가 준비됐을 때 발급하세요.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          start(async () => {
            setNotice("");
            const result = await createAgentConnection(label, canManage);
            if (result.error) setNotice(result.error);
            else if (result.data) {
              setSecret({ id: result.data.id, key: result.data.key });
              setLabel("");
              await refresh();
            }
          });
        }}
      >
        <div className="auth-field">
          <label htmlFor="agent-label">연결 이름</label>
          <input
            id="agent-label"
            maxLength={60}
            required
            value={label}
            disabled={!ready || pending || !!secret}
            placeholder="예: 나의 일정 도우미"
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <label className="settings-hint">
          <input
            type="checkbox"
            checked={canManage}
            disabled={!ready || pending || !!secret}
            onChange={(event) => setCanManage(event.target.checked)}
          />
          공동 일정·코스 관리 허용 (수정·확정·보관·독립 약속 삭제)
        </label>
        <p className="settings-hint">
          관리 키를 가진 도구는 공유 자료를 변경할 수 있어요. 개인 일정·사진·계정은 제외돼요.
        </p>
        <button
          type="submit"
          className="primary-button"
          disabled={!ready || pending || !!secret || !label.trim()}
        >
          <KeyRound size={16} aria-hidden="true" /> 연결 키 발급
        </button>
      </form>
      {secret && (
        <section className="plan-review" aria-label="새 연결 키">
          <div className="section-heading">
            <h3>지금 한 번만 확인할 수 있어요</h3>
            <button
              type="button"
              className="icon-button"
              aria-label="연결 키 닫기"
              onClick={() => setSecret(null)}
            >
              <X size={18} />
            </button>
          </div>
          <p>
            선택한 권한으로 둘의 일정·코스에 접근할 수 있어요. 신뢰하는 에이전트에만 직접
            전달하세요.
          </p>
          <div className="auth-field">
            <label htmlFor="new-agent-key">발급된 연결 키</label>
            <input
              id="new-agent-key"
              type="password"
              readOnly
              value={secret.key}
              autoComplete="off"
            />
          </div>
          <button
            type="button"
            className="text-button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(secret.key);
                setNotice("연결 키를 복사했어요.");
              } catch {
                setNotice("복사하지 못했어요. 입력란에서 키를 직접 복사해 주세요.");
              }
            }}
          >
            <Copy size={16} aria-hidden="true" /> 키 복사
          </button>
          <p className="settings-hint">
            닫거나 페이지를 벗어나면 다시 볼 수 없어요. 분실하면 폐기하고 새로 발급하세요.
          </p>
        </section>
      )}
      {notice && <p role="status">{notice}</p>}
      <p className="settings-hint">
        연결 주소: <code className="agent-endpoint">{endpoint}</code>
      </p>
      <div className="plan-list">
        {items.map((item) => {
          const expired = Date.parse(item.expires_at) <= Date.now();
          return (
            <article className="plan-review" key={item.id}>
              <div className="section-heading">
                <h3>{item.label}</h3>
                {!item.revoked_at && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={pending}
                    onClick={() =>
                      start(async () => {
                        const result = await revokeAgentConnection(item.id);
                        if (result.error) setNotice(result.error);
                        else {
                          if (secret?.id === item.id) setSecret(null);
                          setNotice("연결 키를 폐기했어요.");
                          await refresh();
                        }
                      })
                    }
                  >
                    폐기
                  </button>
                )}
              </div>
              <p className="settings-hint">
                {item.can_manage ? "조회·초안·관리" : "조회·초안"}
                {" · "}
                {item.revoked_at ? "폐기됨" : expired ? "만료됨" : "사용 가능"}
                {" · 만료 "}
                {new Date(item.expires_at).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" })}
              </p>
            </article>
          );
        })}
      </div>
      {!items.length && <p className="muted">발급한 연결 키가 없어요.</p>}
    </section>
  );
}
