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
  } else params.set("query", title);
  return {
    ios: `nmap://${path}?${params}`,
    android: `intent://${path}?${params}#Intent;scheme=nmap;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.nhn.android.nmap;end`,
  };
}
