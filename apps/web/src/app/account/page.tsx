import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { signOut } from "@/app/actions/auth";
import { AuthSubmit } from "@/components/auth-submit";
import { PageHeading } from "@/components/page-heading";
import { ProfileSettings } from "@/components/profile-settings";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { createAuthClient } from "@/lib/auth/server";
import type { ProfileView } from "@/lib/profiles";

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
        <PageHeading>
          <h1>계정을 확인하지 못했어요</h1>
          <p className="muted">연결 상태를 확인하고 잠시 후 다시 시도해 주세요.</p>
        </PageHeading>
        <Link className="text-button" href="/account">
          다시 확인하기
        </Link>
      </section>
    );
  }
  const [identity, profiles] = await Promise.all([
    callApi<{ id: string }>("/auth/me"),
    callApi<ProfileView>("/profiles"),
  ]);
  const apiReady = identity.data?.id === data.user.id;
  const params = await searchParams;
  const name = profiles.data?.mine?.display_name;
  return (
    <section className="auth-panel">
      <PageHeading>
        <p className="eyebrow">YOUR ACCOUNT</p>
        <h1>내 계정</h1>
        <p className="muted">
          {name ? `${name}님, 반가워요.` : "반가워요. 사용할 이름을 등록해 주세요."}
        </p>
      </PageHeading>
      <dl className="detail-list">
        <div>
          <dt>이름</dt>
          <dd>{name || "이름 미설정"}</dd>
        </div>
        <div>
          <dt>로그인</dt>
          <dd>연결됨</dd>
        </div>
        <div>
          <dt>계정 상태</dt>
          <dd>{apiReady ? "계정 확인 완료" : "확인하지 못했어요. 잠시 후 다시 확인해 주세요."}</dd>
        </div>
      </dl>
      <ProfileSettings
        key={`${profiles.data?.mine?.version || 0}-${!!profiles.error}`}
        initial={profiles.data?.mine || null}
        loadError={profiles.error}
      />
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
      <section className="settings-section">
        <h2>로그아웃</h2>
        <p className="settings-hint">
          이 계정의 기기 알림도 해지돼요. 다시 사용하려면 각 기기에서 켜 주세요.
        </p>
        <div className="auth-options">
          <form action={signOut}>
            <AuthSubmit>로그아웃</AuthSubmit>
          </form>
        </div>
      </section>
      <Link href="/settings" className="text-button">
        설정으로 돌아가기
      </Link>
    </section>
  );
}
