import type { VisitChange, VisitProgress } from "@/lib/visits";

async function request<T>(url: string, init: RequestInit = {}) {
  const response = await fetch(url, {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(15_000),
  });
  const value = await response.json();
  return response.ok
    ? { data: value as T, error: "" }
    : {
        data: null,
        error: typeof value.error === "string" ? value.error : "방문 진행에 연결하지 못했어요.",
      };
}

export function readVisits(id: string, offset = 0) {
  return request<VisitProgress[]>(`/api/visits?id=${encodeURIComponent(id)}&offset=${offset}`);
}

export function changeVisit(id: string, input: VisitChange) {
  return request<VisitProgress>(`/api/visits?id=${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}
