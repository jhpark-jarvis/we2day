"use client";
import { useEffect, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";

type InstallPrompt = Event & { prompt: () => Promise<{ outcome: "accepted" | "dismissed" }> };
export function PwaSettings() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(false);
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let mounted = true;
    const standalone = window.matchMedia("(display-mode: standalone)");
    const check = () =>
      setInstalled(
        standalone.matches || !!(navigator as Navigator & { standalone?: boolean }).standalone,
      );
    const install = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPrompt);
    };
    const done = () => {
      setInstalled(true);
      setPrompt(null);
    };
    check();
    standalone.addEventListener("change", check);
    window.addEventListener("beforeinstallprompt", install);
    window.addEventListener("appinstalled", done);
    if ("serviceWorker" in navigator)
      navigator.serviceWorker
        .getRegistration("/")
        .then((registration) => {
          if (mounted && registration?.waiting) setWaiting(registration.waiting);
        })
        .catch(() => {});
    return () => {
      mounted = false;
      standalone.removeEventListener("change", check);
      window.removeEventListener("beforeinstallprompt", install);
      window.removeEventListener("appinstalled", done);
    };
  }, []);
  async function install() {
    if (!prompt) return;
    setPending(true);
    try {
      const choice = await prompt.prompt();
      setNotice(
        choice.outcome === "accepted"
          ? "브라우저에서 설치를 진행해요."
          : "설치를 취소했어요. 브라우저 메뉴에서도 설치할 수 있어요.",
      );
    } catch {
      setNotice("브라우저 메뉴에서 설치를 시도해 주세요.");
    } finally {
      setPrompt(null);
      setPending(false);
    }
  }
  async function checkUpdate() {
    if (!window.isSecureContext || !("serviceWorker" in navigator)) {
      setNotice("이 브라우저에서는 설치 준비를 사용할 수 없어요. HTTPS 주소에서 다시 열어 주세요.");
      return;
    }
    if (process.env.NODE_ENV !== "production") {
      setNotice("개발 모드에서는 설치 준비를 하지 않아요. production 실행에서 확인할 수 있어요.");
      return;
    }
    setPending(true);
    try {
      const registration = await navigator.serviceWorker.register("/sw.js", {
        scope: "/",
        updateViaCache: "none",
      });
      await registration.update();
      if (registration.installing)
        await new Promise<void>((resolve) => {
          const worker = registration.installing;
          if (!worker) return resolve();
          if (worker.state === "installed" || worker.state === "redundant") return resolve();
          const timeout = setTimeout(resolve, 8000);
          worker.addEventListener("statechange", () => {
            if (worker.state === "installed" || worker.state === "redundant") {
              clearTimeout(timeout);
              resolve();
            }
          });
        });
      setWaiting(registration.waiting);
      setNotice(
        registration.waiting
          ? "새 버전이 준비됐어요. 작성 중인 내용을 저장한 뒤 적용해 주세요."
          : installed
            ? "최신 버전을 사용 중이에요."
            : "앱 준비를 확인했어요. 이미 홈 화면에 추가했다면 WE2DAY 아이콘으로 열어 주세요.",
      );
    } catch {
      setNotice("설치 준비를 확인하지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요.");
    } finally {
      setPending(false);
    }
  }
  function update() {
    if (!waiting) return;
    navigator.serviceWorker.addEventListener("controllerchange", () => window.location.reload(), {
      once: true,
    });
    waiting.postMessage({ type: "WE2DAY_APPLY_UPDATE" });
  }
  return (
    <section className="settings-section account-settings">
      <LoadingRegion busy={pending} label="앱 준비를 확인하는 중">
        <h2>홈 화면에 설치</h2>
        <p className="muted pwa-install-state">
          {installed
            ? "홈 화면 앱으로 사용 중이에요."
            : "휴대폰의 홈 화면에서 WE2DAY를 바로 열어보세요."}
        </p>
        {!installed && (
          <details className="compact-help">
            <summary>설치 방법</summary>{" "}
            <p className="settings-hint">
              iPhone·iPad: Safari의 공유 메뉴 → 홈 화면에 추가
              <br />
              Android·Chrome: 브라우저 메뉴 → 앱 설치 또는 홈 화면에 추가
            </p>
          </details>
        )}
        {prompt && !installed && (
          <button type="button" className="primary-button" disabled={pending} onClick={install}>
            WE2DAY 설치
          </button>
        )}
        <button type="button" className="text-button" disabled={pending} onClick={checkUpdate}>
          업데이트 확인
        </button>
        <p className="settings-hint">
          새 버전이 준비되면 적용할 수 있어요. 작성 중인 내용은 먼저 저장해 주세요.
        </p>
        {waiting && (
          <button type="button" className="primary-button" disabled={pending} onClick={update}>
            업데이트 적용 후 새로고침
          </button>
        )}
        {notice && (
          <p role="status" className="settings-hint">
            {notice}
          </p>
        )}
        <details className="compact-help">
          <summary>오프라인 이용 안내</summary>{" "}
          <p className="settings-hint">
            연결이 끊기면 연결 안내 화면을 표시해요. 일정·사진·회고의 오프라인 열람과 편집은 아직
            지원하지 않아요.
          </p>
        </details>
      </LoadingRegion>
    </section>
  );
}
