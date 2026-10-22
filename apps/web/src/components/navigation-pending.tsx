"use client";
import { useLinkStatus } from "next/link";

export function NavigationPending() {
  const { pending } = useLinkStatus();
  return pending ? (
    <span className="navigation-pending" role="status">
      <span className="sr-only">이동 중</span>
    </span>
  ) : null;
}
