"use client";
import Link from "@/components/progress-link";

export function Wordmark() {
  return (
    <Link
      className="wordmark"
      href="/"
      aria-label="WE2DAY 홈"
      onClick={() => window.dispatchEvent(new Event("we2day:calendar-home"))}
    >
      WE<span className="wordmark-accent">2</span>DAY
    </Link>
  );
}
