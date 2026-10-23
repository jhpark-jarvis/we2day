export type RouteMode = "car" | "public" | "walk" | "bicycle" | "navigation";
export type Destination = { lat: string; lng: string; mode: RouteMode };

// Public mobile-web contract: only the fixed origin identifies this app.
export function naverAppLinks(site: string, name: string, destination?: Destination) {
  let origin: string;
  try {
    const url = new URL(site);
    if (
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname !== "/" ||
      !(
        url.protocol === "https:" ||
        (url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname))
      )
    )
      return null;
    origin = `${url.origin}/`;
  } catch {
    return null;
  }
  const title = name.trim();
  if (
    !title ||
    title.length > 200 ||
    Array.from(title).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
  )
    return null;
  const params = new URLSearchParams({ appname: origin });
  let path = "search";
  if (destination) {
    if (
      !["car", "public", "walk", "bicycle", "navigation"].includes(destination.mode) ||
      !/^-?\d+(?:\.\d+)?$/.test(destination.lat) ||
      !/^-?\d+(?:\.\d+)?$/.test(destination.lng)
    )
      return null;
    const lat = Number(destination.lat),
      lng = Number(destination.lng);
    if (
      !Number.isFinite(lat) ||
      !Number.isFinite(lng) ||
      lat < 31.43 ||
      lat > 44.35 ||
      lng < 122.37 ||
      lng > 132
    )
      return null;
    params.set("dlat", String(lat));
    params.set("dlng", String(lng));
    params.set("dname", title);
    path = destination.mode === "navigation" ? "navigation" : `route/${destination.mode}`;
  } else {
    // A selected place is stored as "name (address)" for display, not as one search phrase.
    // Keep meaningful parentheses and directly entered addresses intact.
    const selected = /^(.*\S)\s+\(([^()]*)\)$/.exec(title);
    const address = selected?.[2] || "";
    const koreanAddress =
      /^(?:서울(?:특별시)?|부산(?:광역시)?|대구(?:광역시)?|인천(?:광역시)?|광주(?:광역시)?|대전(?:광역시)?|울산(?:광역시)?|세종(?:특별자치시)?|경기(?:도)?|강원(?:특별자치도|도)?|충청[남북]도|충[남북]|전라[남북]도|전북특별자치도|전[남북]|경상[남북]도|경[남북]|제주(?:특별자치도|도)?)\s+.+\d/;
    params.set("query", selected && koreanAddress.test(address) ? selected[1].trim() : title);
  }
  // Native URI decoders need percent-encoded spaces, not HTML form '+' encoding.
  const query = params.toString().replace(/\+/g, "%20");
  return {
    ios: `nmap://${path}?${query}`,
    android: `intent://${path}?${query}#Intent;scheme=nmap;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.nhn.android.nmap;end`,
  };
}

// User-pasted NAVER share links only; never fetch or expand them on the server.
export function naverShareLink(value: string) {
  return /^https:\/\/naver\.me\/[A-Za-z0-9_-]{1,80}$/.test(value) ? value : null;
}
