"use client";

import { CalendarDays, Heart, Images, Settings2 } from "lucide-react";
import { usePathname } from "next/navigation";
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
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <header className="app-header">
        <Wordmark />
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
                pathname === "/wishlist" ||
                pathname === "/today" ||
                pathname === "/reminders" ||
                pathname.startsWith("/calendar")
              : href === "/together"
                ? pathname === "/together" ||
                  pathname === "/checklists" ||
                  pathname === "/goals" ||
                  pathname.startsWith("/questions") ||
                  pathname.startsWith("/roulette")
                : pathname.startsWith(href) ||
                  (href === "/settings" &&
                    ["/timezones", "/account", "/couple", "/login"].includes(pathname));
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}>
              <Icon size={19} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
