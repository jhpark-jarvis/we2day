"use client";

import { ArrowLeft, Plus, RefreshCw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type ButtonHTMLAttributes,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
} from "react";
import { createPortal } from "react-dom";
import Link from "@/components/progress-link";

export function TogetherBack({
  href = "/together",
  label = "함께로 돌아가기",
}: {
  href?: string;
  label?: string;
}) {
  return (
    <Link href={href} className="icon-button together-back" aria-label={label} title={label}>
      <ArrowLeft size={20} aria-hidden="true" />
    </Link>
  );
}

/** Shared presentation only: callers retain their existing save/permission contracts. */
export function TogetherSheet({
  open,
  title,
  busy = false,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  busy?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const [portal, setPortal] = useState<HTMLElement | null>(null);
  const heading = useId();
  function dismiss() {
    if (!busy && !dialog.current?.querySelector('form[aria-busy="true"]')) onClose();
  }
  useEffect(() => {
    setPortal(document.body);
  }, []);
  useEffect(() => {
    if (!portal || !dialog.current) return;
    const node = dialog.current;
    if (open && !node.open) {
      trigger.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      node.showModal();
    } else if (!open && node.open) {
      node.close();
      trigger.current?.focus();
    }
    return () => {
      if (node.open) node.close();
    };
  }, [open, portal]);
  if (!portal) return null;
  return createPortal(
    <dialog
      ref={dialog}
      className="together-sheet"
      aria-labelledby={heading}
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onPointerDown={(event) => {
        if (busy || event.target !== event.currentTarget) return;
        const r = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < r.left ||
          event.clientX > r.right ||
          event.clientY < r.top ||
          event.clientY > r.bottom
        )
          dismiss();
      }}
    >
      <header className="together-sheet-heading">
        <h2 id={heading}>{title}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label={`${title} 닫기`}
          title="닫기"
          disabled={busy}
          onClick={dismiss}
        >
          <X size={21} aria-hidden="true" />
        </button>
      </header>
      <div className="together-sheet-body">{children}</div>
    </dialog>,
    portal,
  );
}

export function TogetherCreate({
  title,
  label = title,
  children,
}: {
  title: string;
  label?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="icon-button together-add"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        <Plus size={20} aria-hidden="true" />
      </button>
      <TogetherSheet open={open} title={title} onClose={() => setOpen(false)}>
        {children}
      </TogetherSheet>
    </>
  );
}

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
