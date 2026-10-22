import { ArrowUpRight } from "lucide-react";
import Image from "next/image";

export function PhotoStory({ onOpen }: { onOpen: () => void }) {
  return (
    <button className="photo-story" onClick={onOpen} type="button">
      <Image
        src="/demo/autumn.jpg"
        alt="가을 강변 산책길을 표현한 생성 예시 사진"
        width={960}
        height={640}
        sizes="(max-width: 640px) 100vw, 360px"
      />
      <span className="photo-story-caption">
        <span>
          <small>10월 10일 · 지난 기록</small>
          <strong>함께 걸었던 가을 오후</strong>
        </span>
        <ArrowUpRight size={18} aria-hidden="true" />
      </span>
    </button>
  );
}
