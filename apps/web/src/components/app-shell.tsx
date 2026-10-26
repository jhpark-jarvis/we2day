"use client";

import { CalendarDays, Heart, Images, Settings2 } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { PageHeadingTarget } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { Wordmark } from "@/components/wordmark";

const navigation = [
  { href: "/", label: "일정", icon: CalendarDays },
  { href: "/together", label: "함께", icon: Heart },
  { href: "/memories", label: "기록", icon: Images },
  { href: "/settings", label: "설정", icon: Settings2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [headingTarget, setHeadingTarget] = useState<HTMLDivElement | null>(null);
  const defaultTitle = routeTitle(pathname);
  return (
    <PageHeadingTarget.Provider value={headingTarget}>
      <div className="app-shell">
        <a className="skip-link" href="#main">
          본문으로 이동
        </a>
        <header className="app-header">
          <Wordmark />
          <div ref={setHeadingTarget} className="page-title-slot">
            <div className="page-heading-fallback">
              <h1>{defaultTitle}</h1>
            </div>
          </div>
        </header>
        <main id="main" className="app-main">
          {children}
        </main>
        <nav className="app-navigation" aria-label="주요 메뉴">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/"
                ? pathname === "/" ||
                  pathname === "/preview" ||
                  pathname === "/anniversaries" ||
                  pathname.startsWith("/plans") ||
                  pathname === "/today" ||
                  pathname === "/reminders" ||
                  pathname.startsWith("/calendar")
                : href === "/together"
                  ? pathname === "/together" ||
                    pathname === "/wishlist" ||
                    pathname === "/checklists" ||
                    pathname === "/goals" ||
                    pathname.startsWith("/questions") ||
                    pathname.startsWith("/roulette")
                  : pathname.startsWith(href) ||
                    (href === "/settings" &&
                      ["/timezones", "/account", "/couple", "/login"].includes(pathname));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                onClick={() => {
                  if (href === "/" && pathname === "/")
                    window.dispatchEvent(new Event("we2day:calendar-home"));
                }}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </PageHeadingTarget.Provider>
  );
}

function routeTitle(pathname: string) {
  if (pathname === "/") return "함께할 날들";
  const titles: Record<string, string> = {
    preview: "함께할 날들",
    plans: "데이트 플랜",
    today: "데이트 코스",
    anniversaries: "기념일",
    calendar: "캘린더 내보내기",
    wishlist: "위시리스트",
    together: "함께",
    checklists: "목록",
    goals: "목표",
    questions: "질문",
    roulette: "룰렛",
    memories: "기록",
    settings: "설정",
    account: "내 계정",
    couple: "둘의 공간",
    timezones: "각자의 시간대",
    reminders: "다가오는 일정",
    login: "로그인",
  };
  return titles[pathname.split("/")[1]] || "WE2DAY";
}
