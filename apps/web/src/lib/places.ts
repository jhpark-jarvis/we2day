export type PlaceResult = {
  title: string;
  link: string;
  category: string;
  description: string;
  address: string;
  roadAddress: string;
};

export type PlaceResults = { items: PlaceResult[] };

export function safePlaceLink(value: string) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

// Decode text entities, never HTML. Unknown markup remains escaped React text.
export function placeText(value: string) {
  return value.replace(/&(?:amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-f]+);/gi, (entity) => {
    const named: Record<string, string> = {
      amp: "&",
      lt: "<",
      gt: ">",
      quot: '"',
      apos: "'",
      nbsp: "\u00a0",
    };
    const key = entity.slice(1, -1).toLowerCase();
    if (named[key]) return named[key];
    const code = key.startsWith("#x") ? Number.parseInt(key.slice(2), 16) : Number(key.slice(1));
    return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff)
      ? String.fromCodePoint(code)
      : entity;
  });
}
