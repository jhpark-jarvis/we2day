"use client";
import { Pencil } from "lucide-react";

import { useRouter } from "next/navigation";
import { useCallback, useState, useTransition } from "react";
import { AnniversaryForm } from "@/components/anniversary-form";
import { useAnniversaryDay } from "@/components/anniversary-summary";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { RefreshButton } from "@/components/workspace-controls";
import { type Anniversary, type AnniversaryList, countdown, kinds } from "@/lib/anniversaries";

export function AnniversaryWorkspace({
  data,
  error,
}: {
  data: AnniversaryList | null;
  error: string;
}) {
  const router = useRouter();
  const [refreshing, startRefresh] = useTransition();
  const [editing, setEditing] = useState<{ anniversary?: Anniversary; requestId: string } | null>(
    null,
  );
  useAnniversaryDay(data?.as_of);
  const saved = useCallback(() => {
    setEditing(null);
    startRefresh(() => router.refresh());
  }, [router]);
  const reload = () => {
    setEditing(null);
    startRefresh(() => router.refresh());
  };
  const hasRelationship = !!data?.items.some((item) => item.kind === "relationship");
  if (editing && data)
    return (
      <AnniversaryForm
        {...editing}
        today={data.as_of}
        hasRelationship={hasRelationship}
        onSaved={saved}
        onCancel={() => setEditing(null)}
        onReload={reload}
      />
    );
  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR DAYS</p>
          <h1>우리의 기념일</h1>
          <p className="muted">함께한 시간과 앞으로의 특별한 날.</p>
        </div>
      </PageHeading>
      <div className="calendar-toolbar">
        {data && (
          <button
            className="primary-button"
            type="button"
            onClick={() => setEditing({ requestId: crypto.randomUUID() })}
          >
            기념일 추가하기
          </button>
        )}
        <RefreshButton label="기념일 새로고침" pending={refreshing} onClick={reload} />
      </div>
      {error && (
        <p className="error-message" role="alert">
          기념일을 불러오지 못했어요. {error}
        </p>
      )}
      {data && (
        <>
          <p className="muted anniversary-caption">{data.as_of} · 한국 날짜 기준 · 양력</p>
          {data.items.length === 0 && (
            <p className="empty-state">우리의 시작이나 생일을 기록해 보세요.</p>
          )}
          <ul className="anniversary-list" aria-label="기념일 목록">
            {data.items.map((item) => (
              <li key={item.id}>
                <div>
                  <small className="muted">
                    {kinds[item.kind]} · {item.annual ? "매년" : "한 번"}
                  </small>
                  <h2>{item.title}</h2>
                  <p className="muted">
                    {item.kind === "birthday" ? `${item.month}월 ${item.day}일` : item.date}
                    {item.annual && ` · 다음 ${item.next_date}`}
                  </p>
                  {item.together_days !== null && (
                    <p>함께한 {item.together_days.toLocaleString("ko-KR")}일</p>
                  )}
                </div>
                <div className="anniversary-count">
                  <strong>{countdown(item.days_until)}</strong>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={`${item.title} 수정`}
                    onClick={() =>
                      setEditing({ anniversary: item, requestId: crypto.randomUUID() })
                    }
                  >
                    <Pencil size={18} aria-hidden="true" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <p className="settings-hint">
            기기 알림과 자동 기념일 알림은{" "}
            <Link className="inline-link" href="/settings">
              설정
            </Link>
            에서 직접 켤 수 있어요.
          </p>
        </>
      )}
    </>
  );
}
