import type { Metadata } from "next";
import { signIn } from "@/app/actions/auth";
import { AuthSubmit } from "@/components/auth-submit";
import Link from "@/components/progress-link";
import { UsernameLoginForm } from "@/components/username-login-form";
import { getAuthConfig } from "@/lib/auth/config";

export const metadata: Metadata = { title: "로그인" };

const errors: Record<string, string> = {
  unavailable: "지금은 이 로그인 방법을 사용할 수 없어요.",
  start: "로그인 연결을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.",
  callback:
    "로그인을 완료하지 못했어요. 취소했거나 연결 시간이 지났을 수 있어요. 다시 시도해 주세요.",
  session: "로그인이 필요해요. 다시 연결해 주세요.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; notice?: string }>;
}) {
  const config = getAuthConfig();
  const enabled = config?.providers || [];
  const params = await searchParams;
  const error = params.error ? errors[params.error] : undefined;
  return (
    <section className="auth-panel">
      <p className="eyebrow">OUR DAYS, TOGETHER</p>
      <h1>둘의 시간에 로그인</h1>
      <p className="muted">
        {config?.passwordEnabled
          ? "지정된 아이디와 비밀번호로 로그인하세요."
          : "사용하던 계정으로 편하게 시작하세요."}
      </p>
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {params.notice === "signed-out" && (
        <p className="settings-hint" role="status">
          로그아웃했어요.
        </p>
      )}
      {config?.passwordEnabled && <UsernameLoginForm />}
      {config?.passwordEnabled && enabled.length > 0 && (
        <p className="auth-divider">또는 다른 계정으로</p>
      )}
      {enabled.length > 0 && (
        <div className="auth-options">
          {enabled.map((provider) => (
            <form action={signIn} key={provider}>
              <input type="hidden" name="provider" value={provider} />
              <AuthSubmit>
                {provider === "google" ? "Google로 계속하기" : "카카오로 계속하기"}
              </AuthSubmit>
            </form>
          ))}
        </div>
      )}
      {!config?.passwordEnabled && enabled.length === 0 && (
        <p className="note-panel">로그인을 준비 중이에요. 잠시 후 다시 방문해 주세요.</p>
      )}
      <p className="settings-hint">로그인해도 서로의 기록이 자동으로 연결되지는 않아요.</p>
      <Link href="/" className="text-button">
        일정으로 돌아가기
      </Link>
    </section>
  );
}
