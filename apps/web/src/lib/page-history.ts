"use client";

import { type SetStateAction, useCallback, useEffect, useRef, useState } from "react";

type View = Record<string, string>;
const slot = "we2dayView";
const address = () => window.location.pathname + window.location.search;

/** Store navigation identifiers only; never pass records, form contents or credentials. */
export function usePageHistory<T extends View>(
  scope: string,
  initial: T,
  accept?: (value: T) => boolean,
) {
  const first = useRef(initial);
  const check = useRef(accept);
  check.current = accept;
  const [value, setValue] = useState(initial);
  const current = useRef(value);
  const path = useRef("");
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    path.current = window.location.pathname;
    const restore = () => {
      if (window.location.pathname !== path.current) return;
      const entry = window.history.state?.[slot];
      const candidate = entry?.value;
      const valid =
        entry?.scope === scope &&
        entry.url === address() &&
        candidate &&
        typeof candidate === "object" &&
        !Array.isArray(candidate) &&
        Object.keys(candidate).length === Object.keys(first.current).length &&
        Object.keys(first.current).every(
          (key) => typeof candidate[key] === "string" && candidate[key].length <= 100,
        ) &&
        (!check.current || check.current(candidate));
      current.current = valid ? candidate : first.current;
      setValue(current.current);
    };
    restore();
    window.addEventListener("popstate", restore);
    return () => {
      mounted.current = false;
      window.removeEventListener("popstate", restore);
    };
  }, [scope]);
  const write = useCallback(
    (next: SetStateAction<T>, replace: boolean, url?: URL) => {
      if (!mounted.current || window.location.pathname !== path.current) return;
      const resolved = typeof next === "function" ? next(current.current) : next;
      if (check.current && !check.current(resolved)) return;
      if (!url && JSON.stringify(resolved) === JSON.stringify(current.current)) return;
      // Let Next's native-history integration preserve its tree and update its URL context.
      const state = { ...window.history.state };
      delete state.__NA;
      delete state._N;
      const target = url ? url.pathname + url.search : address();
      state[slot] = {
        scope,
        url: target,
        value: resolved,
        parent: replace ? null : current.current,
      };
      window.history[replace ? "replaceState" : "pushState"](
        state,
        "",
        url || window.location.href,
      );
      current.current = resolved;
      setValue(resolved);
    },
    [scope],
  );
  const push = useCallback((next: SetStateAction<T>) => write(next, false), [write]);
  const replace = useCallback(
    (next: SetStateAction<T>, url?: URL) => write(next, true, url),
    [write],
  );
  const back = useCallback(
    (fallback: SetStateAction<T>) => {
      const entry = window.history.state?.[slot];
      if (entry?.scope === scope && entry.url === address() && entry.parent) window.history.back();
      else write(fallback, true);
    },
    [scope, write],
  );
  return [value, push, replace, back] as const;
}

const uuid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i;

/** Recover a selected record through the existing authenticated endpoint after traversal/reload. */
export function useItemHistory<T extends { id: string }>(
  scope: string,
  items: T[],
  endpoint: string,
  initialId = "",
  initialNewId = "",
) {
  const [view, push, replace, back] = usePageHistory(
    scope,
    { id: initialNewId || initialId, mode: initialNewId ? "new" : initialId ? "edit" : "" },
    (v) => (!v.id && !v.mode) || (uuid.test(v.id) && (v.mode === "new" || v.mode === "edit")),
  );
  const [recovered, setRecovered] = useState<T | null>(null);
  const [error, setError] = useState("");
  const saved =
    items.find((item) => item.id === view.id) || (recovered?.id === view.id ? recovered : null);
  useEffect(() => {
    if (view.mode !== "edit" || saved) return;
    const controller = new AbortController();
    fetch(`${endpoint}?id=${view.id}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw Error();
        const row = await response.json();
        if (!row || row.id !== view.id) throw Error();
        if (!controller.signal.aborted) {
          setRecovered(row);
          setError("");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError("항목을 불러오지 못했어요. 다시 선택해 주세요.");
          replace({ id: "", mode: "" });
        }
      });
    return () => controller.abort();
  }, [view.id, view.mode, saved, endpoint, replace]);
  const open = (id: string, create = false) => {
    setError("");
    push({ id, mode: create ? "new" : "edit" });
  };
  const select = (id: string) => {
    setError("");
    replace({ id, mode: "edit" });
  };
  const close = () => back({ id: "", mode: "" });
  const finish = () => replace({ id: "", mode: "" });
  return {
    id: view.mode === "new" || saved ? view.id : "",
    selected: saved,
    open,
    select,
    close,
    finish,
    error,
  };
}
