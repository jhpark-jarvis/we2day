"use client";

import { useTransition } from "react";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";

export default function PageError({ retry }: { error: unknown; retry: () => void }) {
  const [pending, startTransition] = useTransition();
  return (
    <section className="auth-panel" aria-busy={pending}>
      <PageHeading>
        <p className="eyebrow">WE2DAY</p>
        <h1>화면을 불러오지 못했어요</h1>
      </PageHeading>
      <p className="muted" role="alert">
        잠시 후 다시 시도해 주세요. 다른 메뉴로 이동할 수도 있어요.
      </p>
      <p className="settings-hint">저장 완료를 확인하지 못한 내용은 다시 확인해 주세요.</p>
      <div className="calendar-toolbar">
        <button
          type="button"
          className="primary-button"
          aria-busy={pending}
          disabled={pending}
          onClick={() => startTransition(retry)}
        >
          다시 시도
        </button>
        <Link href="/" className="text-button">
          일정
        </Link>
      </div>
    </section>
  );
}
