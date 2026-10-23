import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";

export default function NotFound() {
  return (
    <section className="empty-state">
      <PageHeading>
        <h1>페이지를 찾지 못했어요</h1>
      </PageHeading>
      <p>다시 우리의 일정으로 돌아갈까요?</p>
      <Link className="text-button" href="/">
        일정으로
      </Link>
    </section>
  );
}
