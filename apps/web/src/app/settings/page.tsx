import type { Metadata } from "next";
import { cookies } from "next/headers";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { PushSettings } from "@/components/push-settings";
import { PwaSettings } from "@/components/pwa-settings";
import { ThemePicker } from "@/components/theme-picker";
import { callApi } from "@/lib/api";
import { createAuthClient } from "@/lib/auth/server";
import type { ProfileView } from "@/lib/profiles";
import { resolveTheme, THEME_COOKIE } from "@/lib/theme";

export const metadata: Metadata = { title: "설정" };

async function accountView() {
  try {
    const client = await createAuthClient();
    if (!client) return { status: "unavailable" as const };
    const { data, error } = await client.auth.getUser();
    if (error) {
      return {
        status:
          "status" in error && [400, 401, 403].includes(error.status || 0)
            ? ("guest" as const)
            : ("unavailable" as const),
      };
    }
    if (!data.user) return { status: "guest" as const };
    const profiles = await callApi<ProfileView>("/profiles");
    return {
      status: "ready" as const,
      identity: profiles.data?.mine?.display_name || null,
    };
  } catch {
    return { status: "unavailable" as const };
  }
}

export default async function SettingsPage() {
  const [cookieStore, account] = await Promise.all([cookies(), accountView()]);
  const theme = resolveTheme(cookieStore.get(THEME_COOKIE)?.value);
  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">MAKE IT YOURS</p>
          <h1>설정</h1>
          <p className="muted">우리의 공간을 편안한 모습으로.</p>
        </div>
      </PageHeading>
      <section className="settings-section">
        <h2>화면 테마</h2>
        <p className="muted">마음에 드는 분위기를 골라보세요.</p>
        <ThemePicker initialTheme={theme} />
      </section>
      <section className="settings-section" aria-label="기록 관리">
        <h2>기록 관리</h2>
        <Link className="text-button" href="/settings/export">
          기록 내보내기
        </Link>
        <Link className="text-button" href="/settings/trash">
          사진 휴지통
        </Link>
        <p className="settings-hint">날짜와 사진 기록을 찾아 복구하거나 영구 삭제를 확인해요.</p>
      </section>
      <PwaSettings />
      <PushSettings />
      <section className="settings-section account-settings">
        <h2>시간 표시</h2>
        <p className="muted">일정에 함께 표시할 각자의 현지 시간대를 설정해요.</p>
        <Link className="text-button" href="/timezones">
          각자의 시간대
        </Link>
      </section>
      <section className="settings-section account-settings" aria-label="계정 설정">
        <h2>계정</h2>
        {account.status === "ready" ? (
          <>
            <p className="muted">
              {account.identity ? `${account.identity}님으로 로그인했어요.` : "로그인한 상태예요."}
            </p>
            <Link className="text-button" href="/account">
              계정 관리
            </Link>
          </>
        ) : account.status === "guest" ? (
          <>
            <p className="muted">로그인하고 둘의 공간을 이용해 보세요.</p>
            <Link className="text-button" href="/login">
              로그인
            </Link>
          </>
        ) : (
          <>
            <p className="muted">계정 상태를 확인하지 못했어요. 잠시 후 다시 확인해 주세요.</p>
            <Link className="text-button" href="/settings">
              다시 확인하기
            </Link>
          </>
        )}
      </section>
    </>
  );
}
