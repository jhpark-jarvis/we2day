"use client";

import { useFormStatus } from "react-dom";

export function AuthSubmit({ children }: { children: React.ReactNode }) {
  const { pending } = useFormStatus();
  return (
    <button className="auth-button" type="submit" disabled={pending} aria-busy={pending}>
      {children}
    </button>
  );
}
