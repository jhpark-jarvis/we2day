export const THEME_COOKIE = "we2day-theme";
export const THEME_MAX_AGE = 60 * 60 * 24 * 365;
export type Theme = "warm" | "white";

export function isTheme(value: unknown): value is Theme {
  return value === "warm" || value === "white";
}

export function resolveTheme(value: unknown): Theme {
  return isTheme(value) ? value : "warm";
}
