import { PageHeading } from "@/components/page-heading";

export default function NotFound() {
  return (
    <section className="empty-state">
      <PageHeading>
        <h1>페이지를 찾지 못했어요</h1>
      </PageHeading>
      <p>주소를 확인해 주세요.</p>
    </section>
  );
}
