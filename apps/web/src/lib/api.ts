import "server-only";
import { createAuthClient } from "@/lib/auth/server";

const errors: Record<string, string> = {
  plan_draft_required: "확정한 적이 있는 플랜은 삭제할 수 없어요. 보관을 이용해 주세요.",
  ai_conversation_not_found: "대화 기록을 찾지 못했어요.",
  ai_not_configured: "AI 연결을 준비 중이에요. 서버 설정을 확인해 주세요.",
  ai_context_too_long: "대화가 길어요. 필요한 초안을 저장하고 새 대화를 시작해 주세요.",
  ai_daily_limit: "잠시 후 다시 전송해 주세요.",
  ai_rate_limited: "연속 요청을 잠시 쉬고 다시 전송해 주세요.",
  ai_provider_limited: "Cloudflare AI 사용 한도에 도달했어요. 나중에 다시 시도해 주세요.",
  ai_provider_busy: "지금 AI 요청이 몰리고 있어요. 잠시 후 다시 전송해 주세요.",
  ai_timeout: "답변 준비가 오래 걸려 중단했어요. 같은 요청으로 다시 시도해 주세요.",
  ai_request_in_progress: "같은 대화를 처리 중이에요. 잠시 후 다시 시도해 주세요.",
  ai_lease_expired: "요청 시간이 만료됐어요. 같은 요청으로 다시 시도해 주세요.",
  ai_request_cancelled: "대화 요청을 중단했어요.",
  ai_unavailable: "AI에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
  ai_invalid_response: "답변을 완성하지 못했어요. 요청을 짧게 나눠 다시 시도해 주세요.",
  agent_connection_limit: "사용 가능한 연결 키는 최대 5개예요. 기존 키를 폐기해 주세요.",
  invalid_agent_connection: "연결 이름을 1~60자로 입력해 주세요.",
  agent_connection_not_found: "연결 키를 찾지 못했어요. 목록을 새로고침해 주세요.",
  invalid_favorite_place: "별칭은 100자, 장소명·주소는 200자 이내로 입력해 주세요.",
  favorite_place_not_found: "이 공간의 장소를 찾지 못했어요. 목록을 새로고침해 주세요.",
  invalid_profile: "이름은 앞뒤 공백과 줄바꿈 없이 1~40자로 입력해 주세요.",
  invalid_push_subscription: "기기 알림 정보를 확인하지 못했어요. 다시 등록해 주세요.",
  push_device_limit: "등록 가능한 기기는 계정당 5개예요. 다른 기기의 알림을 꺼 주세요.",
  push_test_limited: "테스트 알림은 기기당 1분에 한 번 보낼 수 있어요.",
  push_registration_required: "기기 등록이 만료됐어요. 이 기기에서 알림을 다시 켜 주세요.",
  push_not_configured: "기기 알림을 준비 중이에요. 운영 주소와 서버 설정이 필요해요.",
  push_delivery_failed: "테스트 알림을 보내지 못했어요. 잠시 후 다시 시도해 주세요.",
  invalid_record_search: "기록 종류·최대 366일 범위·검색어 길이를 확인해 주세요.",
  invalid_visit_progress: "플랜 당일·지난 날짜의 활동과 방문 상태를 확인해 주세요.",
  publication_changed: "확정 내용이 바뀌었어요. 확정 플랜을 새로고침해 주세요.",
  invalid_photo_search: "검색할 날짜 순서·최대 366일 범위와 검색 조건을 확인해 주세요.",
  calendar_export_too_large: "선택한 기간에 일정이 너무 많아요. 더 짧은 기간으로 확인해 주세요.",
  "Database setup required":
    "새 기능의 데이터베이스 설정이 아직 적용되지 않았어요. 서버 설정을 확인해 주세요.",
  invalid_route: "두 장소의 이름과 좌표, 기록할 날짜를 확인해 주세요.",
  invalid_plan: "플랜의 날짜·활동·준비물과 내용의 길이를 확인해 주세요.",
  invalid_report: "회고 내용·방문 장소·지출과 내용의 길이를 확인해 주세요.",
  invalid_wish: "위시의 이름·종류와 메모의 길이를 확인해 주세요.",
  wish_not_found: "위시를 찾지 못했어요. 최신 목록을 불러와 주세요.",
  invalid_checklist: "목록 이름·항목·수량과 내용의 길이를 확인해 주세요.",
  checklist_not_found: "목록을 찾지 못했어요. 최신 목록을 불러와 주세요.",
  checklist_items_retained: "저장된 항목은 이름을 수정하거나 체크를 해제해 주세요.",
  invalid_goal: "목표 이름·희망 날짜·단계를 확인해 주세요.",
  goal_not_found: "목표를 찾지 못했어요. 최신 목표를 불러와 주세요.",
  goal_steps_retained: "저장된 단계는 이름을 수정하거나 체크를 해제해 주세요.",
  invalid_question: "질문 날짜와 문구(1~500자)를 확인해 주세요.",
  invalid_question_search: "검색할 날짜 순서·최대 366일 범위와 검색어 길이를 확인해 주세요.",
  question_not_found: "이 공간의 질문을 찾지 못했어요.",
  invalid_answer: "답변은 2000자까지예요. 공유하려면 건너뛰기를 해제하고 내용을 적어 주세요.",
  invalid_timezone: "지원하는 시간대를 직접 선택해 주세요.",
  invalid_roulette: "후보를 중복 없이 2~20개, 각각 100자까지 적어 주세요.",
  roulette_not_found: "이 공간의 룰렛을 찾지 못했어요.",
  roulette_archived: "보관한 룰렛은 복원 후 뽑을 수 있어요.",
  report_not_ready: "플랜을 확정하고 해당 날짜가 되면 회고를 작성할 수 있어요.",
  plan_not_found: "플랜을 찾지 못했어요. 최신 목록을 불러와 주세요.",
  plan_archived: "보관한 플랜이에요. 복원한 뒤 수정해 주세요.",
  already_connected: "이미 둘의 공간에 연결되어 있어요. 페이지를 새로고침해 주세요.",
  couple_required: "먼저 둘의 공간을 연결해 주세요.",
  couple_full: "이미 두 사람이 연결된 공간이에요.",
  invalid_invite: "초대 코드를 확인해 주세요. 만료되거나 이미 사용한 코드일 수 있어요.",
  version_conflict: "다른 곳에서 내용이 바뀌었어요. 최신 내용을 불러온 뒤 다시 수정해 주세요.",
  anniversary_not_found: "기념일을 찾지 못했어요. 최신 내용을 확인해 주세요.",
  relationship_exists: "우리의 시작이 이미 등록되어 있어요. 최신 기념일을 불러와 수정해 주세요.",
  invalid_anniversary: "기념일의 종류와 날짜를 확인해 주세요.",
  request_conflict: "이전 저장 요청과 내용이 달라요. 최신 일정을 확인해 주세요.",
  appointment_owner_required: "개인 일정은 작성자만 수정하거나 삭제할 수 있어요.",
  personal_appointment_required: "개인 일정만 삭제할 수 있어요.",
  appointment_not_found: "약속을 찾지 못했어요. 최신 일정을 확인해 주세요.",
  photo_not_found: "사진을 찾지 못했어요. 날짜의 사진 목록을 새로고침해 주세요.",
  invalid_photo:
    "사진 파일이나 사진 정보를 확인해 주세요. 1MB·1600px 이하의 JPEG·WebP 압축본을 선택해 주세요.",
  photo_upload_incomplete: "사진 저장이 아직 완료되지 않았어요. 같은 사진으로 다시 시도해 주세요.",
  invalid_meeting_day: "오늘 또는 지난 날짜를 선택하고 메모 길이를 확인해 주세요.",
  invalid_photo_metadata: "앨범 날짜와 500자 이내의 설명을 확인해 주세요.",
  invalid_photo_action: "사진과 요청 내용을 확인해 주세요.",
  photo_confirmation_required: "영구 삭제 확인 문구를 정확히 입력해 주세요.",
  photo_deleting: "영구 삭제를 진행 중인 사진이에요. 삭제 재시도로 마무리해 주세요.",
  photo_state_conflict: "사진 상태가 바뀌었어요. 목록을 새로고침해 주세요.",
  photo_retention_active: "휴지통에 보관한 지 30일이 지나야 영구 삭제할 수 있어요.",
  photo_delete_incomplete: "파일 삭제 결과를 확인하지 못했어요. 영구 삭제를 다시 시도해 주세요.",
  invalid_photo_export: "내보낼 사진은 중복 없이 1~20장 선택해 주세요.",
  invalid_place_search: "검색어를 1~100자로 입력해 주세요.",
  place_search_not_configured:
    "장소 검색이 아직 설정되지 않았어요. 직접 입력한 약속은 그대로 저장할 수 있어요.",
  place_search_limited: "장소 검색 이용 한도에 도달했어요. 잠시 후 다시 시도해 주세요.",
  place_search_unavailable:
    "장소 검색에 연결하지 못했어요. 검색어를 유지했으니 다시 시도해 주세요.",
};

export async function callApi<T>(path: string, init: RequestInit = {}) {
  const failure = (status: number, error: string) => ({
    data: null as T | null,
    status,
    error,
    serverTiming: "",
  });
  try {
    const client = await createAuthClient();
    if (!client) return failure(503, "지금은 공유 공간에 연결할 수 없어요.");
    // This supplies a token only. FastAPI verifies identity; SQL enforces membership.
    const { data, error } = await client.auth.getSession();
    if (error || !data.session) return failure(401, "로그인이 필요해요. 다시 로그인해 주세요.");
    const response = await fetch(
      `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}${path}`,
      {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...init.headers,
          Authorization: `Bearer ${data.session.access_token}`,
        },
        cache: "no-store",
        signal: requestSignal(
          init.signal,
          path === "/ai/planner"
            ? 100_000
            : path === "/photos" && init.method === "POST"
              ? 30_000
              : 8_000,
        ),
      },
    );
    const body = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      return failure(response.status, apiError(response.status, body?.detail));
    }
    return {
      data: body as T,
      status: response.status,
      error: "",
      serverTiming: response.headers.get("Server-Timing") || "",
    };
  } catch {
    return failure(503, "연결하지 못했어요. 잠시 후 다시 시도해 주세요.");
  }
}

function requestSignal(signal: AbortSignal | null | undefined, milliseconds: number) {
  const timeout = AbortSignal.timeout(milliseconds);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

export function timingHeaders(result: { serverTiming: string }): Record<string, string> {
  return result.serverTiming ? { "Server-Timing": result.serverTiming } : {};
}

export function apiError(status: number, detail?: string) {
  return (
    (detail && errors[detail]) ||
    (status === 401
      ? "로그인이 필요해요. 다시 로그인해 주세요."
      : status === 422
        ? "입력한 날짜·시간과 내용의 길이를 확인해 주세요."
        : "연결하지 못했어요. 잠시 후 다시 시도해 주세요.")
  );
}

export async function callBinaryApi(
  path: string,
  init: RequestInit = {},
  contentType = "image/webp",
) {
  try {
    const client = await createAuthClient();
    if (!client) return new Response(null, { status: 503 });
    const { data, error } = await client.auth.getSession();
    if (error || !data.session) return new Response(null, { status: 401 });
    const response = await fetch(
      `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}${path}`,
      {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          Authorization: `Bearer ${data.session.access_token}`,
        },
        cache: "no-store",
        signal: requestSignal(init.signal, path === "/photos/export" ? 60_000 : 20_000),
      },
    );
    if (!response.ok) return new Response(null, { status: response.status });
    return new Response(await response.arrayBuffer(), {
      headers: {
        "Content-Type": contentType,
        ...timingHeaders({ serverTiming: response.headers.get("Server-Timing") || "" }),
      },
    });
  } catch {
    return new Response(null, { status: 503 });
  }
}

export async function callImageApi(path: string) {
  return callBinaryApi(path);
}
