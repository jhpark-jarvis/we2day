import { approveAgentOAuth } from "@/app/actions/agent-oauth";
import { PageHeading } from "@/components/page-heading";
import { callApi } from "@/lib/api";
export const metadata = { title: "ChatGPT 연결 확인", robots: { index: false, follow: false } };
export default async function Authorize({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const pairs = Object.entries(params);
  const valid = pairs.every(([, value]) => typeof value === "string");
  const values = Object.fromEntries(pairs) as Record<string, string>;
  const result =
    valid && !params.error
      ? await callApi<Record<string, string>>(`/agent/oauth/review?${new URLSearchParams(values)}`)
      : null;
  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">CHATGPT CONNECTION</p>
          <h1>ChatGPT 연결</h1>
        </div>
      </PageHeading>
      <section className="plan-review">
        {!result?.data || result.error ? (
          <p role="alert">
            연결 요청을 확인하지 못했어요. WE2DAY에 로그인한 뒤 ChatGPT에서 연결을 다시 시작해
            주세요.
          </p>
        ) : (
          <>
            <h2>공동 일정·코스 관리</h2>
            <p>
              ChatGPT가 공동 일정과 코스를 조회하고, 요청한 초안·수정·확정·보관·복원과 독립 공동
              약속 삭제를 처리할 수 있어요.
            </p>
            <p>
              조회한 제목·날짜·시간·장소·메모는 ChatGPT(OpenAI)에 전달될 수 있어요. 개인
              일정·사진·계정·설정은 제외돼요.
            </p>
            <p>
              연결은 발급일부터 1년간 유효해요. 설정의 에이전트 연결에서 언제든 폐기할 수 있어요.
            </p>
            <form action={approveAgentOAuth.bind(null, result.data)}>
              <label className="checkbox-label">
                <input type="checkbox" name="consent" required />이 권한으로 내 ChatGPT에 연결
              </label>
              <div className="calendar-toolbar">
                <button type="submit" className="primary-button">
                  연결 허용
                </button>
                <a className="text-button" href="/settings/agents">
                  취소
                </a>
              </div>
            </form>
          </>
        )}
      </section>
    </>
  );
}
