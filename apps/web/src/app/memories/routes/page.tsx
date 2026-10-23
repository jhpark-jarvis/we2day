import { redirect } from "next/navigation";
export default function LegacyPage() {
  redirect("/memories/search?type=routes");
}
