import type { Metadata } from "next";
import { PageHeading } from "@/components/page-heading";
import { PhotoWorkspace } from "@/components/photo-workspace";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import { type ProfileView, profileNames } from "@/lib/profiles";
import type { Couple } from "@/lib/shared-calendar";
export const metadata: Metadata = { title: "사진 휴지통" };
export default async function PhotoTrashPage() {
  const [couple, user, profiles] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<{ id: string }>("/auth/me"),
    callApi<ProfileView>("/profiles"),
  ]);
  return (
    <>
      <PageHeading>
        <h1>사진 휴지통</h1>
      </PageHeading>
      <PhotoWorkspace
        today={seoulToday()}
        userId={user.data?.id || null}
        canSave={!!couple.data && !!user.data}
        names={profileNames(profiles.data)}
        trash
      />
    </>
  );
}
