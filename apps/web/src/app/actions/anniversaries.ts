"use server";

import { revalidatePath } from "next/cache";
import type { Anniversary, AnniversaryState } from "@/lib/anniversaries";
import { callApi } from "@/lib/api";

export async function saveAnniversary(
  _previous: AnniversaryState,
  form: FormData,
): Promise<AnniversaryState> {
  const read = (key: string) => (typeof form.get(key) === "string" ? String(form.get(key)) : "");
  const id = read("id");
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if ((id && !uuid.test(id)) || (!id && !uuid.test(read("request_id"))))
    return { error: "저장할 기념일을 확인해 주세요." };
  const kind = read("kind");
  const body = {
    kind,
    title: read("title"),
    date: kind === "birthday" ? null : read("date"),
    month: kind === "birthday" ? Number(read("month")) : null,
    day: kind === "birthday" ? Number(read("day")) : null,
    annual: kind !== "custom" || read("annual") === "on",
    ...(id ? { expected_version: Number(read("version")) } : { request_id: read("request_id") }),
  };
  const result = await callApi<Anniversary>(id ? `/anniversaries/${id}` : "/anniversaries", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(body),
  });
  if (result.error)
    return {
      error: result.error.startsWith("다른 곳에서 약속")
        ? "다른 곳에서 기념일이 바뀌었어요. 최신 내용을 불러온 뒤 다시 수정해 주세요."
        : result.error,
      conflict: result.status === 409,
    };
  revalidatePath("/");
  revalidatePath("/anniversaries");
  return { error: "", anniversary: result.data || undefined };
}
