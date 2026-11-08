import { redirect } from "next/navigation";
import { isSupportedDate } from "@/lib/calendar";
export default async function LegacyPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  redirect(`/today${typeof date === "string" && isSupportedDate(date) ? `?date=${date}` : ""}`);
}
