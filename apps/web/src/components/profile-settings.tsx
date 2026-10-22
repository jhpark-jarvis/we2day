"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { saveDisplayName } from "@/app/actions/profile";
import type { Profile } from "@/lib/profiles";

export function ProfileSettings({
  initial,
  loadError,
}: {
  initial: Profile | null;
  loadError: string;
}) {
  const router = useRouter();
  const [profile, setProfile] = useState(initial);
  const [name, setName] = useState(initial?.display_name || "");
  const [error, setError] = useState(loadError);
  const [notice, setNotice] = useState("");
  const [pending, startTransition] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  return (
    <form
      className="username-login"
      aria-label="사용자 이름 설정"
      onSubmit={(event) => {
        event.preventDefault();
        if (pending || loadError) return;
        const signature = JSON.stringify([name.trim(), profile?.version || 0]);
        if (request.current?.signature !== signature)
          request.current = { signature, id: crypto.randomUUID() };
        const id = request.current.id;
        setNotice("");
        startTransition(async () => {
          try {
            const result = await saveDisplayName(name, profile?.version || 0, id);
            setError(result.error);
            if (result.data) {
              setProfile(result.data);
              setName(result.data.display_name);
              request.current = null;
              setNotice("이름을 저장했어요.");
              router.refresh();
            }
          } catch {
            setError("저장하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
          }
        });
      }}
    >
      <div>
        <label htmlFor="display-name">사용자 이름</label>
        <input
          id="display-name"
          name="display_name"
          autoComplete="nickname"
          required
          maxLength={40}
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={pending || !!loadError}
          aria-describedby="display-name-hint"
        />
        <p id="display-name-hint" className="muted">
          서비스에서 사용할 이름이에요. 연결된 상대방에게도 보여요. (1~40자)
        </p>
      </div>
      <button
        className="primary-button"
        type="submit"
        disabled={pending || !!loadError || !name.trim()}
      >
        {pending ? "저장 중…" : "이름 저장"}
      </button>
      {notice && <p role="status">{notice}</p>}
      {error && (
        <>
          <p className="error-message" role="alert">
            {error}
          </p>
          <button
            className="text-button"
            type="button"
            disabled={pending}
            onClick={() => router.refresh()}
          >
            최신 이름 불러오기
          </button>
        </>
      )}
    </form>
  );
}
