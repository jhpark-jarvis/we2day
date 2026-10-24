import { redirect } from "next/navigation";
import { isSupportedDate } from "@/lib/calendar";
export default async function LegacyPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  redirect(`/memories/search?type=routes${date && isSupportedDate(date) ? `&date=${date}` : ""}`);
}
