export type PlanningBrief = {
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  region: string;
  transport: "" | "자동차" | "대중교통" | "도보";
  activities: string[];
  recommend: boolean;
  budget: number | null;
  requirements: string;
};

export type IntakeContext = {
  date?: string | null;
  region?: string;
  transport?: string;
  activities?: string[];
  budget?: number | null;
  requirements?: string;
  search_scope?: Record<string, unknown>;
  control?: { last_action?: { operation: string } | null; outcome?: string };
  dialogue?: { cleared_date?: boolean; pending?: { resume: string } | null };
  activity_edit?: unknown;
  pending_fields?: unknown;
  intake?: { data: PlanningBrief; pending?: string | null } | null;
};

export function emptyBrief(): PlanningBrief {
  return {
    date: null,
    start_time: null,
    end_time: null,
    region: "",
    transport: "",
    activities: [],
    recommend: false,
    budget: null,
    requirements: "",
  };
}

export function briefError(brief: PlanningBrief, step = 3, selectedPlaces = 0): string {
  const clock = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
  if (brief.date) {
    const parsed = new Date(`${brief.date}T00:00:00Z`);
    if (
      !/^(?:20\d{2}|2100)-\d{2}-\d{2}$/.test(brief.date) ||
      !Number.isFinite(parsed.getTime()) ||
      parsed.toISOString().slice(0, 10) !== brief.date
    )
      return "날짜를 확인해 주세요.";
  }
  if ([brief.start_time, brief.end_time].some((t) => t !== null && !clock.test(t)))
    return "시간을 확인해 주세요.";
  if (brief.start_time && brief.end_time && brief.end_time <= brief.start_time)
    return "종료 시간은 시작 시간보다 늦어야 해요.";
  if (step === 0) return "";
  if ((!brief.region.trim() && !selectedPlaces) || brief.region.length > 100)
    return "지역을 입력하거나 저장한 장소를 선택해 주세요.";
  if (!["", "자동차", "대중교통", "도보"].includes(brief.transport))
    return "이동수단을 확인해 주세요.";
  if (step === 1) return "";
  if (Boolean(brief.activities.length) === brief.recommend)
    return "활동을 선택하거나 추천을 선택해 주세요.";
  if (
    brief.activities.length > 8 ||
    brief.activities.some((a) => !a.trim() || a.length > 60) ||
    new Set(brief.activities.map((a) => a.trim())).size !== brief.activities.length
  )
    return "활동은 중복 없이 8개까지 선택할 수 있어요.";
  if (
    brief.budget !== null &&
    (!Number.isSafeInteger(brief.budget) || brief.budget < 0 || brief.budget > 1_000_000_000)
  )
    return "예산은 0원부터 10억 원 사이의 정수로 입력해 주세요.";
  if (brief.requirements.length > 300) return "추가 조건은 300자까지 입력해 주세요.";
  return "";
}

export function briefMessage(brief: PlanningBrief): string {
  const opening = brief.date
    ? "입력한 조건으로 코스를 만들어줘."
    : "입력한 조건으로 장소 후보만 찾아줘. 날짜는 미정이야.";
  const amount =
    brief.budget === null
      ? "미정"
      : `${String(brief.budget).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}원`;
  return [
    opening,
    `날짜: ${brief.date || "미정"}`,
    `시간대: ${brief.start_time || "미정"} ~ ${brief.end_time || "미정"}`,
    `지역: ${brief.region || "직접 선택한 저장 장소"}`,
    `이동수단: ${brief.transport || "미정"}`,
    `활동: ${brief.activities.length ? brief.activities.join(" → ") : "자유롭게 추천"}`,
    `예산: ${amount}`,
    `추가 조건: ${brief.requirements || "없음"}`,
  ].join("\n");
}

export function currentBrief(context: IntakeContext): PlanningBrief {
  return {
    ...emptyBrief(),
    ...context.intake?.data,
    date: context.date ?? null,
    region: context.region || "",
    budget: context.budget ?? null,
    transport: (["자동차", "대중교통", "도보"].includes(context.transport || "")
      ? context.transport
      : "") as PlanningBrief["transport"],
    activities: context.activities || [],
    recommend: !context.activities?.length,
    requirements: context.requirements || "",
  };
}
