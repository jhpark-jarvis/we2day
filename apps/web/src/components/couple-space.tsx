"use client";

import { useActionState } from "react";
import { acceptInvite, createCouple, createInvite } from "@/app/actions/couple";
import { AuthSubmit } from "@/components/auth-submit";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import type { Couple } from "@/lib/shared-calendar";

export function CoupleSpace({ couple }: { couple: Couple | null }) {
  const [created, createAction] = useActionState(createCouple, { error: "" });
  const [invited, inviteAction] = useActionState(createInvite, { error: "" });
  const [accepted, acceptAction] = useActionState(acceptInvite, { error: "" });

  return (
    <>
      <PageHeading>
        <p className="eyebrow">OUR SPACE</p>
        <h1>둘의 공간</h1>
      </PageHeading>
      {couple ? (
        <>
          <p className="note-panel" role="status">
            {couple.member_count === 2
              ? "두 사람이 연결되었어요. 이제 같은 약속을 함께 볼 수 있어요."
              : "내 공간이 준비되었어요. 초대 코드를 상대에게 전달해 주세요."}
          </p>
          {couple.member_count === 1 && (
            <>
              <form action={inviteAction} className="auth-options">
                <AuthSubmit>
                  {invited.token ? "새 초대 코드 만들기" : "초대 코드 만들기"}
                </AuthSubmit>
              </form>
              <p className="muted">
                코드는 24시간 동안 한 번 사용할 수 있어요. 새로 만들면 이전 코드는 만료돼요.
              </p>
              {invited.token && (
                <div className="invite-result">
                  <label htmlFor="invite-code">상대에게 전달할 코드</label>
                  <textarea
                    id="invite-code"
                    readOnly
                    value={invited.token}
                    rows={3}
                    onFocus={(event) => event.currentTarget.select()}
                  />
                  <p className="muted">
                    만료:{" "}
                    {new Intl.DateTimeFormat("ko-KR", {
                      timeZone: "Asia/Seoul",
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(invited.expires_at || ""))}
                  </p>
                </div>
              )}
              {invited.error && (
                <p role="alert" className="error-message">
                  {invited.error}
                </p>
              )}
            </>
          )}
          <Link className="text-button" href="/">
            일정 함께 보기
          </Link>
        </>
      ) : (
        <>
          <p className="muted">한 사람이 공간을 만들고, 다른 사람이 초대를 수락하면 연결돼요.</p>
          <form action={createAction} className="auth-options">
            <AuthSubmit>새 공간 만들기</AuthSubmit>
          </form>
          {created.error && (
            <p role="alert" className="error-message">
              {created.error}
            </p>
          )}
          <p className="auth-divider">초대 코드를 받았나요?</p>
          <form action={acceptAction} className="username-login">
            <div className="auth-field">
              <label htmlFor="received-code">받은 초대 코드</label>
              <input
                id="received-code"
                name="token"
                required
                maxLength={64}
                minLength={64}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
              />
            </div>
            <AuthSubmit>초대 수락하기</AuthSubmit>
            {accepted.error && (
              <p role="alert" className="error-message">
                {accepted.error}
              </p>
            )}
          </form>
        </>
      )}
    </>
  );
}
