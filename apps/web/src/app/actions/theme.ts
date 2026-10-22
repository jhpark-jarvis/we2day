"use server";

import { cookies } from "next/headers";
import { isTheme, THEME_COOKIE, THEME_MAX_AGE, type Theme } from "@/lib/theme";

export async function saveTheme(theme: Theme): Promise<void> {
  if (!isTheme(theme)) throw new Error("Unsupported theme");
  const store = await cookies();
  store.set(THEME_COOKIE, theme, {
    path: "/",
    maxAge: THEME_MAX_AGE,
    sameSite: "lax",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
  });
}
