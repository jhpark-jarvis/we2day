"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Answer, CoupleQuestion } from "@/lib/questions";
import type { RouletteDraw, RouletteWheel } from "@/lib/roulette";
import type { TimezonePreference } from "@/lib/timezones";

const uuid = (id: string) => /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id);
const invalid = () => ({ data: null, status: 422, error: "항목을 확인해 주세요." });
export async function createQuestion(id: string, date: string, prompt: string, requestId: string) {
  if (!uuid(id)) return invalid();
  const result = await callApi<CoupleQuestion>(`/questions/${id}`, {
    method: "POST",
    body: JSON.stringify({ date, prompt, request_id: requestId }),
  });
  if (result.data) revalidatePath("/questions");
  return result;
}
export async function saveAnswer(
  id: string,
  content: string,
  shared: boolean,
  skipped: boolean,
  version: number,
  requestId: string,
) {
  if (!uuid(id)) return invalid();
  const result = await callApi<Answer>(`/questions/${id}/answer`, {
    method: "POST",
    body: JSON.stringify({
      content,
      shared,
      skipped,
      expected_version: version,
      request_id: requestId,
    }),
  });
  if (result.data) revalidatePath(`/questions/${id}`);
  return result;
}
export async function saveTimezone(timezone: string | null, version: number, requestId: string) {
  const result = await callApi<TimezonePreference>("/timezones", {
    method: "POST",
    body: JSON.stringify({ timezone, expected_version: version, request_id: requestId }),
  });
  if (result.data) {
    revalidatePath("/timezones");
    revalidatePath("/");
    revalidatePath("/today");
  }
  return result;
}
export async function saveRoulette(
  id: string,
  title: string,
  candidates: string[],
  archived: boolean,
  version: number,
  requestId: string,
) {
  if (!uuid(id)) return invalid();
  const result = await callApi<RouletteWheel>(`/roulette/${id}`, {
    method: "POST",
    body: JSON.stringify({
      title,
      candidates,
      archived,
      expected_version: version,
      request_id: requestId,
    }),
  });
  if (result.data) {
    revalidatePath("/roulette");
    revalidatePath(`/roulette/${id}`);
  }
  return result;
}
export async function drawRoulette(id: string, version: number, requestId: string) {
  if (!uuid(id)) return invalid();
  const result = await callApi<RouletteDraw>(`/roulette/${id}/draws`, {
    method: "POST",
    body: JSON.stringify({ expected_version: version, request_id: requestId }),
  });
  if (result.data) revalidatePath(`/roulette/${id}`);
  return result;
}

export async function readRouletteDraws(id: string) {
  if (!uuid(id)) return { data: null, status: 422, error: "룰렛을 확인해 주세요." };
  return callApi<RouletteDraw[]>(`/roulette/${id}/draws?offset=0`);
}
