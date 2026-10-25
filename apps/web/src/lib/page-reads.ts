import { apiError } from "@/lib/api";
import type { ProfileView } from "@/lib/profiles";
import type { Appointment, Couple } from "@/lib/shared-calendar";
import type { TimezoneView } from "@/lib/timezones";
import type { NextAppointment } from "@/lib/upcoming";

export type ReadSection<T> = { data: T | null; status: number; detail: string };
export type AccountRead = { user_id: string; profiles: ReadSection<ProfileView> };
export type ContextRead = AccountRead & { couple: ReadSection<Couple> };
export type HomeRead = {
  couple: ReadSection<Couple>;
  appointments: ReadSection<Appointment[]>;
  zones: ReadSection<TimezoneView>;
  profiles: ReadSection<ProfileView>;
  next: ReadSection<NextAppointment>;
};
export function section<T>(value: ReadSection<T> | undefined, fallbackStatus = 503) {
  const status = value?.status || fallbackStatus;
  return {
    data: value?.data || null,
    status,
    error: status === 200 ? "" : apiError(status, value?.detail),
  };
}
