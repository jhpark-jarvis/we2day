"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { NavigationPending } from "@/components/navigation-pending";

export default function ProgressLink({ children, ...props }: ComponentProps<typeof Link>) {
  return (
    <Link {...props}>
      {children}
      <NavigationPending />
    </Link>
  );
}
