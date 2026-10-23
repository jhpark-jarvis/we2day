export const THEME_COOKIE = "we2day-theme";
export const THEME_MAX_AGE = 60 * 60 * 24 * 365;
export const themes = [
  { value: "warm", name: "웜 클린", description: "차분한 크림과 따뜻한 테라코타", character: null },
  { value: "white", name: "화이트", description: "밝은 화이트와 간결한 여백", character: null },
  {
    value: "pongni",
    name: "퐁니 라벤더",
    description: "포근한 라벤더와 부드러운 회보라",
    character: "/themes/pongni.png",
  },
  {
    value: "dumung",
    name: "두뭉 크림",
    description: "따뜻한 크림과 은은한 밀크티",
    character: "/themes/dumung.png",
  },
  {
    value: "sopoo",
    name: "소푸 버터",
    description: "산뜻한 버터 옐로와 노란 꽃",
    character: "/themes/sopoo.png",
  },
  {
    value: "kuku",
    name: "쿠쿠 코코아",
    description: "차분한 코코아와 부드러운 베이지",
    character: "/themes/kuku.png",
  },
] as const;
export type Theme = (typeof themes)[number]["value"];

export function isTheme(value: unknown): value is Theme {
  return themes.some((theme) => theme.value === value);
}

export function resolveTheme(value: unknown): Theme {
  return isTheme(value) ? value : "warm";
}
