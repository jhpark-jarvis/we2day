"use server";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { QuestionSearchPage, QuestionSearchQuery } from "@/lib/question-search";

export async function searchQuestions(input: QuestionSearchQuery, offset = 0) {
  if (
    !input ||
    !isSupportedDate(input.start_date) ||
    !isSupportedDate(input.end_date) ||
    typeof input.query !== "string" ||
    input.query.length > 100 ||
    !Number.isInteger(offset) ||
    offset < 0 ||
    offset > 100000
  )
    return { data: null, status: 422, error: "검색할 날짜와 질문 문구를 확인해 주세요." };
  return callApi<QuestionSearchPage>("/questions/search", {
    method: "POST",
    body: JSON.stringify({ ...input, offset }),
  });
}
