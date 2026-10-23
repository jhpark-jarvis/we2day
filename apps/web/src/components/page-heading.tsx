"use client";

import { createContext, type ReactNode, useContext } from "react";
import { createPortal } from "react-dom";

// The shell reserves this space in the initial HTML; headings never add a body row.
export const PageHeadingTarget = createContext<HTMLElement | null | undefined>(undefined);

export function PageHeading({ children }: { children: ReactNode }) {
  const target = useContext(PageHeadingTarget);
  const heading = <div className="page-heading">{children}</div>;
  if (target === undefined) return heading;
  return target ? createPortal(heading, target) : null;
}
