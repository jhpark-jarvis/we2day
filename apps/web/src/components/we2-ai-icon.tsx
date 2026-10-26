import Image from "next/image";

export function We2AiIcon({ size = 24 }: { size?: number }) {
  return (
    <span className="we2-ai-icon" style={{ width: size, height: size }} aria-hidden="true">
      <Image src="/brand/we2-ai-v1.png" width={1402} height={1122} alt="" unoptimized />
    </span>
  );
}
