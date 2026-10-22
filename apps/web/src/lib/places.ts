// Search terms are passed only through a user-clicked NAVER Maps link.
export const PLACE_QUERY_MAX_LENGTH = 200;
export function normalizePlaceQuery(value: string) {
  const query = value.trim();
  return query.length > 0 &&
    query.length <= PLACE_QUERY_MAX_LENGTH &&
    !Array.from(query).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
    ? query
    : "";
}
