// Stable account namespace; these reserved-domain addresses never receive email.
export const USERNAME_DOMAIN = "login.we2day.invalid";
export const USERNAME_PATTERN = "[a-zA-Z][a-zA-Z0-9_]{2,31}";

export function normalizeUsername(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const username = value.trim().toLowerCase();
  return /^[a-z][a-z0-9_]{2,31}$/.test(username) ? username : null;
}

export function usernameAddress(username: string) {
  const normalized = normalizeUsername(username);
  if (!normalized) throw new Error("Invalid username");
  return `${normalized}@${USERNAME_DOMAIN}`;
}

export function usernameFromAddress(email?: string | null): string | null {
  if (!email?.endsWith(`@${USERNAME_DOMAIN}`)) return null;
  return normalizeUsername(email.slice(0, -USERNAME_DOMAIN.length - 1));
}
