"use server";

import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";

export type PhotoActionState = { error: string; changed?: string };

export async function changePhoto(
  _previous: PhotoActionState,
  form: FormData,
): Promise<PhotoActionState> {
  const read = (name: string) => String(form.get(name) || "");
  const id = read("id"),
    requestId = read("request_id"),
    action = read("action");
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuid.test(id) || !uuid.test(requestId) || !["trash", "restore", "purge"].includes(action))
    return { error: "변경할 사진을 확인해 주세요." };
  const confirmation = read("confirmation");
  if (action === "purge" && confirmation !== "영구 삭제")
    return { error: "확인란에 ‘영구 삭제’를 정확히 입력해 주세요." };
  const result = await callApi(`/photos/${id}/${action}`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: Number(read("version")),
      request_id: requestId,
      confirmation,
    }),
  });
  if (result.error)
    return {
      error: result.error.replace(
        "다른 곳에서 약속이 바뀌었어요. 최신 일정을 불러온 뒤 다시 수정해 주세요.",
        "사진 상태가 바뀌었어요. 목록을 새로고침해 주세요.",
      ),
    };
  revalidatePath("/memories");
  return {
    error: "",
    changed:
      action === "trash"
        ? "사진을 휴지통으로 옮겼어요."
        : action === "restore"
          ? "사진을 원래 날짜의 앨범으로 복구했어요."
          : "사진 파일과 기록을 영구 삭제했어요.",
  };
}
