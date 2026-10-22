"use server";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { PhotoSearchPage, PhotoSearchQuery } from "@/lib/photo-search";

export async function searchPhotos(input: PhotoSearchQuery, offset = 0) {
  if (
    !input ||
    !isSupportedDate(input.start_date) ||
    !isSupportedDate(input.end_date) ||
    typeof input.query !== "string" ||
    input.query.length > 100 ||
    !["caption", "filename", "device"].includes(input.field) ||
    !["all", "mine", "partner"].includes(input.uploader) ||
    !Number.isInteger(offset) ||
    offset < 0 ||
    offset > 100000
  )
    return { data: null, status: 422, error: "검색할 날짜와 조건을 확인해 주세요." };
  return callApi<PhotoSearchPage>("/photos/reference-search", {
    method: "POST",
    body: JSON.stringify({ ...input, offset }),
  });
}
