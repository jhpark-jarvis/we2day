import type { ReactNode } from "react";

/** Keep content mounted and measurable while a request is in flight. */
export function LoadingRegion({
  busy,
  label = "불러오는 중",
  children,
  disabled = false,
  className = "",
}: {
  busy: boolean;
  disabled?: boolean;
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`loading-region ${className}`} data-loading={busy}>
      <div aria-busy={busy} inert={busy || disabled}>
        {children}
      </div>
      {busy && (
        <div className="loading-veil" role="status">
          <span className="loading-spinner" aria-hidden="true" />
          <span className="sr-only">{label}</span>
        </div>
      )}
    </div>
  );
}
