"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ButtonHTMLAttributes, useTransition } from "react";

export function ServerRefresh({ label }: { label: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <RefreshButton
      label={label}
      pending={pending}
      onClick={() => startTransition(() => router.refresh())}
    />
  );
}

export function RefreshButton({
  label,
  pending = false,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; pending?: boolean }) {
  return (
    <button
      {...props}
      type="button"
      className="icon-button workspace-refresh"
      aria-label={label}
      title={label}
      aria-busy={pending}
      disabled={pending || disabled}
    >
      <RefreshCw size={18} aria-hidden="true" />
    </button>
  );
}

export function ArchiveToggle({
  archived,
  pending = false,
  onChange,
  label,
  currentLabel = "현재",
  archivedLabel = "보관함",
}: {
  archived: boolean;
  pending?: boolean;
  onChange: (archived: boolean) => void;
  label: string;
  currentLabel?: string;
  archivedLabel?: string;
}) {
  return (
    <fieldset className="list-view-toggle" aria-label={label}>
      <button
        type="button"
        aria-pressed={!archived}
        disabled={pending}
        onClick={() => onChange(false)}
      >
        {currentLabel}
      </button>
      <button
        type="button"
        aria-pressed={archived}
        disabled={pending}
        onClick={() => onChange(true)}
      >
        {archivedLabel}
      </button>
    </fieldset>
  );
}
