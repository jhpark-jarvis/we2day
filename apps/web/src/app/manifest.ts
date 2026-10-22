import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "WE2DAY",
    short_name: "WE2DAY",
    description: "함께할 약속과 함께한 날을 담는 둘의 일정 공간.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#fcf9f4",
    theme_color: "#fcf9f4",
    lang: "ko",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/pwa-icon/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/pwa-icon/512", sizes: "512x512", type: "image/png", purpose: "any" },
    ],
  };
}
