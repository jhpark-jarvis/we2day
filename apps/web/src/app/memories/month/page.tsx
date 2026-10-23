import { redirect } from "next/navigation";
import { seoulToday } from "@/lib/calendar";
export default async function LegacyMonth({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const { month: value } = await searchParams;
  const month =
    typeof value === "string" && /^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(value)
      ? value
      : seoulToday().slice(0, 7);
  redirect(`/memories/search?type=monthly&month=${month}`);
}
