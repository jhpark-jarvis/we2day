export const AI_STAGES = {
  accepted: "요청을 받았어요.",
  context: "이전 대화와 조건을 확인하고 있어요.",
  model: "조건에 맞춰 답변을 구성하고 있어요.",
  search: "네이버에서 장소 후보를 검색하고 있어요.",
  tools: "필요한 정보를 확인하고 있어요.",
  validate: "장소 근거와 코스 조건을 검사하고 있어요.",
  persist: "대화 결과를 저장하고 있어요.",
} as const;

export type AiStage = keyof typeof AI_STAGES;

class AiResponseError extends Error {}

const streamErrors: Record<string, string> = {
  ai_timeout: "답변 준비가 오래 걸려 중단했어요. 같은 요청으로 다시 시도해 주세요.",
  ai_request_in_progress: "같은 요청이 아직 처리 중이에요. 잠시 후 다시 시도해 주세요.",
  ai_lease_expired: "요청 시간이 만료됐어요. 같은 요청으로 다시 시도해 주세요.",
  ai_request_cancelled: "요청을 중단했어요. 같은 요청으로 다시 시도할 수 있어요.",
  ai_provider_limited: "AI 사용 한도에 도달했어요. 나중에 다시 시도해 주세요.",
  ai_provider_busy: "AI 요청이 몰리고 있어요. 잠시 후 다시 시도해 주세요.",
  ai_daily_limit: "잠시 후 다시 전송해 주세요.",
  ai_rate_limited: "연속 요청을 잠시 쉬고 다시 전송해 주세요.",
  version_conflict: "다른 곳에서 대화가 바뀌었어요. 대화 내역을 다시 열어 주세요.",
  ai_context_too_long: "대화가 길어요. 필요한 초안을 저장하고 새 대화를 시작해 주세요.",
  ai_invalid_response: "답변을 확인하지 못했어요. 같은 요청으로 다시 시도해 주세요.",
};

export async function readAiResponse<T>(
  response: Response,
  progress: (stage: AiStage) => void,
): Promise<T> {
  if (!response.ok) {
    const value = await response.json().catch(() => null);
    throw new AiResponseError(value?.error || "답변을 받지 못했어요.");
  }
  // Older server versions and deterministic UI fixtures retain the JSON contract.
  if (!response.headers.get("content-type")?.startsWith("text/event-stream"))
    return response.json().catch(() => {
      throw new AiResponseError("연결이 끊겼어요. 같은 요청으로 다시 시도해 주세요.");
    });
  const reader = response.body?.getReader();
  if (!reader) throw new AiResponseError("처리 상태를 받지 못했어요.");
  const decoder = new TextDecoder();
  let buffer = "",
    bytes = 0,
    terminal: T | undefined;
  function consume(frame: string) {
    const lines = frame.split(/\r?\n/);
    const event = lines
      .find((line) => line.startsWith("event:"))
      ?.slice(6)
      .trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data || !["progress", "result", "error"].includes(event || "")) return;
    if (terminal !== undefined) throw new AiResponseError("답변을 확인하지 못했어요.");
    let value: ReturnType<typeof JSON.parse>;
    try {
      value = JSON.parse(data);
      if (!value || typeof value !== "object") throw new AiResponseError();
    } catch {
      throw new AiResponseError("답변을 확인하지 못했어요. 같은 요청으로 다시 시도해 주세요.");
    }
    if (event === "progress") {
      if (typeof value.stage === "string" && Object.hasOwn(AI_STAGES, value.stage))
        progress(value.stage);
    } else if (event === "error") {
      throw new AiResponseError(
        streamErrors[value.code] || "처리를 완료하지 못했어요. 같은 요청으로 다시 시도해 주세요.",
      );
    } else {
      if (
        typeof value.reply !== "string" ||
        !value.reply ||
        !Number.isInteger(value.version) ||
        value.version < 0
      )
        throw new AiResponseError("답변을 확인하지 못했어요.");
      terminal = value as T;
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 524288)
        throw new AiResponseError("답변이 너무 길어요. 같은 요청으로 다시 시도해 주세요.");
      buffer += decoder.decode(value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        consume(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
      if (buffer.length > 196608) throw new AiResponseError("답변을 확인하지 못했어요.");
    }
    if (terminal === undefined)
      throw new AiResponseError("연결이 끊겼어요. 같은 요청으로 다시 시도해 주세요.");
    return terminal;
  } catch (error) {
    if (error instanceof AiResponseError) throw error;
    throw new AiResponseError("연결이 끊겼어요. 같은 요청으로 다시 시도해 주세요.");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
