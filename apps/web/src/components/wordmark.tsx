"use client";
import Image from "next/image";
import Link from "@/components/progress-link";
import { themes } from "@/lib/theme";

export function Wordmark() {
  return (
    <Link
      className="wordmark"
      href="/"
      aria-label="WE2DAY 홈"
      onClick={() => window.dispatchEvent(new Event("we2day:calendar-home"))}
    >
      <span>
        WE<span className="wordmark-accent">2</span>DAY
      </span>
      {themes.map(
        (option) =>
          option.character && (
            <Image
              key={option.value}
              src={option.character}
              alt=""
              aria-hidden="true"
              width={40}
              height={40}
              sizes="40px"
              className={`wordmark-character character-${option.value}`}
            />
          ),
      )}
    </Link>
  );
}
