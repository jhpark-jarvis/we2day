"use server";

import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { MeetingDay, MeetingSaveState } from "@/lib/meetings";

export async function saveMeeting(
  _previous: MeetingSaveState,
  form: FormData,
): Promise<MeetingSaveState> {
  const date = String(form.get("date") || "");
  const requestId = String(form.get("request_id") || "");
  if (
    !isSupportedDate(date) ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId)
  )
    return { error: "저장할 날짜를 확인해 주세요." };
  const result = await callApi<MeetingDay>(`/meetings/${date}`, {
    method: "POST",
    body: JSON.stringify({
      met: form.get("met") === "on",
      note: String(form.get("note") || ""),
      expected_version: Number(form.get("version")),
      request_id: requestId,
    }),
  });
  if (result.error)
    return {
      error:
        result.status === 409
          ? "다른 곳에서 만남 기록이 바뀌었어요. 최신 기록을 불러온 뒤 다시 수정해 주세요."
          : result.error,
      conflict: result.status === 409,
    };
  revalidatePath("/");
  return { error: "", meeting: result.data || undefined };
}
