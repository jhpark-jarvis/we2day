"use client";

import { Check } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import { saveTheme } from "@/app/actions/theme";
import { LoadingRegion } from "@/components/loading-region";
import type { Theme } from "@/lib/theme";

export function ThemePicker({ initialTheme }: { initialTheme: Theme }) {
  const [selected, setSelected] = useState(initialTheme);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState("");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", selected);
  }, [selected]);

  function choose(theme: Theme) {
    if (pending || theme === selected) return;
    const previous = selected;
    setSelected(theme);
    setError("");
    startTransition(async () => {
      try {
        await saveTheme(theme);
      } catch {
        setSelected(previous);
        setError("테마를 저장하지 못했어요. 다시 선택해 주세요.");
      }
    });
  }

  return (
    <div>
      <LoadingRegion busy={pending} label="테마를 저장하는 중">
        <fieldset className="theme-options" aria-label="화면 테마">
          {(
            [
              { value: "warm", name: "웜 클린", description: "차분한 크림과 따뜻한 테라코타" },
              { value: "white", name: "화이트", description: "밝은 화이트와 간결한 여백" },
            ] as const
          ).map((option) => (
            <button
              className="theme-option"
              type="button"
              key={option.value}
              aria-pressed={selected === option.value}
              disabled={pending}
              onClick={() => choose(option.value)}
            >
              <span className={`theme-swatch swatch-${option.value}`} aria-hidden="true">
                <span>WE2DAY</span>
                <i />
                <i />
                <i />
              </span>
              <span className="theme-option-copy">
                <strong>
                  <span>{option.name}</span>
                  {selected === option.value && (
                    <Check className="theme-check" size={18} aria-hidden="true" />
                  )}
                </strong>
                <small>{option.description}</small>
              </span>
            </button>
          ))}
        </fieldset>
      </LoadingRegion>
      <p className="settings-hint" role="status">
        선택한 테마는 이 브라우저에 1년 동안 저장돼요.
      </p>
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
