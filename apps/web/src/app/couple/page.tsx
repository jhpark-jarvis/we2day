import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { CoupleSpace } from "@/components/couple-space";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import type { Couple } from "@/lib/shared-calendar";

export const metadata: Metadata = { title: "둘의 공간" };

export default async function CouplePage() {
  const result = await callApi<Couple | null>("/couple");
  if (result.status === 401) redirect("/login");
  return (
    <section className="auth-panel">
      {result.error ? (
        <>
          <h1>공간에 연결하지 못했어요</h1>
          <p role="alert" className="error-message">
            {result.error}
          </p>
          <Link href="/couple" className="text-button">
            다시 확인하기
          </Link>
        </>
      ) : (
        <CoupleSpace couple={result.data} />
      )}
      <Link href="/account" className="text-button">
        내 계정으로
      </Link>
    </section>
  );
}
