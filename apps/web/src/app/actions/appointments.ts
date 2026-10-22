"use server";

import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Appointment, SaveState } from "@/lib/shared-calendar";

export async function saveAppointment(_previous: SaveState, form: FormData): Promise<SaveState> {
  const read = (key: string) => {
    const value = form.get(key);
    return typeof value === "string" ? value : "";
  };
  const id = read("id");
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if ((id && !uuid.test(id)) || (!id && !uuid.test(read("request_id")))) {
    return { error: "저장할 약속을 확인해 주세요." };
  }
  const body = {
    title: read("title"),
    date: read("date"),
    time: read("time") || null,
    place: read("place"),
    note: read("note"),
    ...(id ? { expected_version: Number(read("version")) } : { request_id: read("request_id") }),
  };
  const result = await callApi<Appointment>(id ? `/appointments/${id}` : "/appointments", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(body),
  });
  if (result.error) return { error: result.error, conflict: result.status === 409 };
  revalidatePath("/");
  return { error: "", appointment: result.data || undefined };
}
