import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { signOut } from "@/app/actions/auth";
import { AuthSubmit } from "@/components/auth-submit";
import { createAuthClient } from "@/lib/auth/server";
import { usernameFromAddress } from "@/lib/auth/username";

export const metadata: Metadata = { title: "내 계정" };

export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const client = await createAuthClient();
  if (!client) redirect("/login");
  const { data, error } = await client.auth.getUser();
  if (!data.user || error) {
    if (!error || ("status" in error && [400, 401, 403].includes(error.status || 0))) {
      redirect("/login?error=session");
    }
    return (
      <section className="auth-panel">
        <h1>계정을 확인하지 못했어요</h1>
        <p className="muted">연결 상태를 확인하고 잠시 후 다시 시도해 주세요.</p>
        <Link className="text-button" href="/account">
          다시 확인하기
        </Link>
      </section>
    );
  }
  // getSession supplies the token only; getUser above and FastAPI both validate identity.
  const { data: sessionData } = await client.auth.getSession();
  let apiReady = false;
  if (sessionData.session) {
    try {
      const response = await fetch(
        `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}/auth/me`,
        {
          headers: { Authorization: `Bearer ${sessionData.session.access_token}` },
          cache: "no-store",
          signal: AbortSignal.timeout(8_000),
        },
      );
      if (response.ok) apiReady = (await response.json()).id === data.user.id;
    } catch {
      // Keep the confirmed web session usable while the API is unavailable.
    }
  }
  const params = await searchParams;
  const username = usernameFromAddress(data.user.email);
  const name = data.user.user_metadata?.full_name || data.user.user_metadata?.name;
  return (
    <section className="auth-panel">
      <p className="eyebrow">YOUR ACCOUNT</p>
      <h1>내 계정</h1>
      <p className="muted">{typeof name === "string" ? `${name}님, 반가워요.` : "반가워요."}</p>
      <dl className="detail-list">
        <div>
          <dt>{username ? "아이디" : "이메일"}</dt>
          <dd>{username || data.user.email || "이메일 제공 안 함"}</dd>
        </div>
        <div>
          <dt>로그인</dt>
          <dd>연결됨</dd>
        </div>
        <div>
          <dt>서버 연결</dt>
          <dd>{apiReady ? "계정 확인 완료" : "확인하지 못했어요. 잠시 후 다시 확인해 주세요."}</dd>
        </div>
      </dl>
      <Link className="text-button" href="/couple">
        둘의 공간 연결 · 초대
      </Link>
      {params.error === "push-revoke" && (
        <p className="error-message" role="alert">
          기기 알림을 해지하지 못했어요. 연결을 확인한 뒤 로그아웃을 다시 시도해 주세요.
        </p>
      )}
      {params.error === "signout" && (
        <p className="error-message" role="alert">
          로그아웃하지 못했어요. 다시 시도해 주세요.
        </p>
      )}
      <div className="auth-options">
        <form action={signOut}>
          <AuthSubmit>로그아웃</AuthSubmit>
        </form>
      </div>
      <Link href="/settings" className="text-button">
        설정으로 돌아가기
      </Link>
    </section>
  );
}
