import { CalendarExport } from "@/components/calendar-export";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { seoulToday } from "@/lib/calendar";
export default function CalendarExportPage() {
  return (
    <section className="plan-editor">
      <Link className="text-button" href="/">
        ← 일정으로
      </Link>
      <PageHeading>
        <div>
          <p className="eyebrow">TAKE OUR PLANS WITH YOU</p>
          <h1>캘린더 파일 내보내기</h1>
          <p className="muted">선택한 달의 약속과 기념일을 파일로 받아요.</p>
        </div>
      </PageHeading>
      <CalendarExport month={seoulToday().slice(0, 7)} />
      <details className="compact-help">
        <summary>캘린더에서 파일 열기</summary>
        <p className="settings-hint">
          가져오기를 지원하는 캘린더에서 .ics 파일을 열어 사용해요. 휴대폰·캘린더 앱에 따라 가져오기
          방법이 달라요.
        </p>
      </details>
      <p className="settings-hint">
        내보낸 파일에는 선택한 일정의 이름·장소가 포함돼요. 이후 WE2DAY의 수정·공유 변경은 파일에
        자동 반영되지 않아요. 자동 동기화와 알림 발송은 포함하지 않아요.
      </p>
    </section>
  );
}
