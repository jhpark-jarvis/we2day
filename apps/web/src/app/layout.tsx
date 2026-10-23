import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import { AppShell } from "@/components/app-shell";
import { PwaRegistration } from "@/components/pwa-registration";
import { resolveTheme, THEME_COOKIE } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "WE2DAY", template: "%s · WE2DAY" },
  description: "함께할 약속과 함께한 날을 담는 둘의 일정 공간.",
  applicationName: "WE2DAY",
  appleWebApp: { capable: true, title: "WE2DAY", statusBarStyle: "default" },
  icons: { icon: "/pwa-icon/192?v=brand2", apple: "/pwa-icon/180?v=brand2" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const theme = resolveTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <html lang="ko" data-theme={theme}>
      <body>
        <PwaRegistration />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
