"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { type AnniversaryList, countdown } from "@/lib/anniversaries";
import { seoulToday } from "@/lib/calendar";

export function useAnniversaryDay(day?: string) {
  const router = useRouter();
  useEffect(() => {
    if (!day) return;
    const check = () => {
      if (document.visibilityState === "visible" && seoulToday() !== day) router.refresh();
    };
    const timer = window.setInterval(check, 60_000);
    document.addEventListener("visibilitychange", check);
    check();
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [day, router]);
}

export function AnniversarySummary({ data }: { data: AnniversaryList | null }) {
  useAnniversaryDay(data?.as_of);
  const relationship = data?.items.find((item) => item.kind === "relationship");
  const upcoming = data?.items.find((item) => item.days_until >= 0 && item.kind !== "relationship");
  return (
    <section className="anniversary-summary" aria-label="디데이와 기념일 요약">
      <div>
        <p className="muted">OUR DAYS</p>
        <strong>
          {!data
            ? "우리의 기념일"
            : relationship?.together_days
              ? `함께한 ${relationship.together_days.toLocaleString("ko-KR")}일`
              : relationship
                ? `${relationship.title} ${countdown(relationship.days_until)}`
                : data.items.length
                  ? "우리의 기념일"
                  : "함께 기억할 날을 등록해 보세요"}
        </strong>
        {upcoming && (
          <p>
            {upcoming.title} · {countdown(upcoming.days_until)}
          </p>
        )}
      </div>
      <Link className="text-button" href="/anniversaries">
        기념일 관리
      </Link>
    </section>
  );
}
