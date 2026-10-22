import type { Metadata } from "next";
import { CalendarWorkspace } from "@/components/calendar-workspace";
import { seoulToday } from "@/lib/calendar";

export const metadata: Metadata = {
  title: "화면 미리보기",
  robots: { index: false, follow: false },
};

export default function PreviewPage() {
  return <CalendarWorkspace today={seoulToday()} preview />;
}
