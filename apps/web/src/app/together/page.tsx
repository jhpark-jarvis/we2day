import { ChevronRight, Dices, ListChecks, MessagesSquare, Target } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "함께" };

const features = [
  { href: "/checklists", label: "목록", description: "준비물과 함께 챙길 일", icon: ListChecks },
  { href: "/goals", label: "목표", description: "같이 이루고 싶은 일", icon: Target },
  { href: "/questions", label: "질문", description: "서로의 생각과 일상", icon: MessagesSquare },
  { href: "/roulette", label: "룰렛", description: "고민되는 선택을 가볍게", icon: Dices },
];

export default function TogetherPage() {
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">LITTLE THINGS, TOGETHER</p>
          <h1>함께</h1>
          <p className="muted">같이 챙길 일과 나누고 싶은 이야기.</p>
        </div>
      </header>
      <nav className="together-grid" aria-label="공동 활동">
        {features.map(({ href, label, description, icon: Icon }) => (
          <Link className="together-card" href={href} key={href} aria-label={label}>
            <Icon size={22} aria-hidden="true" />
            <strong>{label}</strong>
            <span>{description}</span>
            <ChevronRight className="card-chevron" size={18} aria-hidden="true" />
          </Link>
        ))}
      </nav>
    </>
  );
}
