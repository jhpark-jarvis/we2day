export default function Loading() {
  return (
    <section className="page-loading" aria-busy="true" aria-label="페이지 로딩">
      <p role="status">화면을 불러오고 있어요.</p>
      <div className="loading-heading" aria-hidden="true" />
      <div className="loading-line" aria-hidden="true" />
      <div className="loading-panel" aria-hidden="true" />
    </section>
  );
}
