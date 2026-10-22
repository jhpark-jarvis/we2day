"use client";
import { useCallback, useEffect, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";

type Configuration = {
  configured: boolean;
  public_key: string | null;
  automatic_available?: boolean;
};
async function device(action: string, subscription?: PushSubscription) {
  const json = subscription?.toJSON();
  const response = await fetch("/api/push/device", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      endpoint: subscription?.endpoint ?? "",
      ...(action === "register" ? { p256dh: json?.keys?.p256dh, auth: json?.keys?.auth } : {}),
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(20_000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "기기 알림에 연결하지 못했어요.");
  return result as { enabled?: boolean; accepted?: boolean; automatic_enabled?: boolean };
}
function publicKey(value: string) {
  const data = atob(
    value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4),
  );
  return Uint8Array.from(data, (c) => c.charCodeAt(0));
}
export function PushSettings() {
  const [config, setConfig] = useState<Configuration | null>(null);
  const [supported, setSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [automatic, setAutomatic] = useState(false);
  const [hasSubscription, setHasSubscription] = useState(false);
  const [pending, setPending] = useState(true);
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => {
    setPending(true);
    try {
      const ios =
        /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
      const installed =
        window.matchMedia("(display-mode: standalone)").matches ||
        !!(navigator as Navigator & { standalone?: boolean }).standalone;
      const capable =
        (!ios || installed) &&
        window.isSecureContext &&
        "serviceWorker" in navigator &&
        "PushManager" in window &&
        "Notification" in window;
      setSupported(capable);
      const response = await fetch("/api/push/config", {
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "알림 설정을 확인하지 못했어요.");
      setConfig(result);
      if (capable) {
        const registration = await navigator.serviceWorker.getRegistration("/");
        const sub = await registration?.pushManager.getSubscription();
        setHasSubscription(!!sub);
        const status = sub && result.configured ? await device("status", sub) : null;
        setEnabled(status?.enabled === true);
        setAutomatic(status?.automatic_enabled === true);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "알림 상태를 확인하지 못했어요.");
    } finally {
      setPending(false);
    }
  }, []);
  // Loading never requests notification permission or creates a subscription.
  useEffect(() => {
    void refresh();
  }, [refresh]);
  async function enable() {
    if (!config?.public_key || !supported) return;
    setPending(true);
    setNotice("");
    let created: PushSubscription | null = null;
    try {
      // Keep the permission request in the direct click handler for iOS.
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setNotice("알림을 허용하지 않았어요. 기기 설정에서 권한을 바꾼 뒤 다시 켤 수 있어요.");
        return;
      }
      await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
      const registration = await Promise.race([
        navigator.serviceWorker.ready,
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error("앱 준비가 지연돼요. 설치 준비 후 다시 시도해 주세요.")),
            10_000,
          ),
        ),
      ]);
      let existing = await registration.pushManager.getSubscription();
      const expectedKey = publicKey(config.public_key);
      const previousKey = existing?.options?.applicationServerKey;
      if (
        existing &&
        previousKey &&
        (previousKey.byteLength !== expectedKey.byteLength ||
          new Uint8Array(previousKey).some((byte, index) => byte !== expectedKey[index]))
      ) {
        await device("remove", existing);
        if (!(await existing.unsubscribe()))
          throw new Error("이전 기기 등록을 해지하지 못했어요. 알림 끄기 후 다시 시도해 주세요.");
        existing = null;
        setHasSubscription(false);
        setEnabled(false);
        setAutomatic(false);
      }
      const sub =
        existing ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: expectedKey,
        }));
      if (!existing) created = sub;
      setHasSubscription(true);
      await device("register", sub);
      created = null;
      setEnabled(true);
      setAutomatic((await device("status", sub)).automatic_enabled === true);
      setNotice("이 기기를 등록했어요. 테스트 알림을 눌러 실제 도착을 확인해 주세요.");
    } catch (error) {
      if (created && (await created.unsubscribe().catch(() => false))) setHasSubscription(false);
      setNotice(error instanceof Error ? error.message : "기기를 등록하지 못했어요.");
    } finally {
      setPending(false);
    }
  }
  async function act(action: "test" | "remove" | "automatic_on" | "automatic_off") {
    setPending(true);
    setNotice("");
    try {
      const registration = await navigator.serviceWorker.getRegistration("/");
      const sub = await registration?.pushManager.getSubscription();
      if (!sub) {
        setEnabled(false);
        setAutomatic(false);
        setHasSubscription(false);
        setNotice("이 기기의 알림을 다시 켜 주세요.");
        return;
      }
      const result = await device(action, sub);
      if (action === "remove") {
        setEnabled(false);
        setAutomatic(false);
        const removed = await sub.unsubscribe();
        setHasSubscription(!removed);
        setNotice(
          removed
            ? "이 기기의 알림을 껐어요."
            : "서버 알림은 껐어요. 브라우저 구독 해지는 다시 확인해 주세요.",
        );
      } else if (action === "automatic_on" || action === "automatic_off") {
        setAutomatic(result.automatic_enabled === true);
        setNotice(
          action === "automatic_on"
            ? "자동 기념일 알림을 켰어요. 켠 이후의 예약 시점부터 받아요."
            : "자동 기념일 알림을 껐어요. 수동 테스트는 계속 사용할 수 있어요.",
        );
      } else {
        setNotice(
          "Push 서비스가 요청을 수락했어요. 이 기기에 실제 알림이 도착했는지 확인해 주세요.",
        );
      }
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "요청을 마치지 못했어요. 다시 시도해 주세요.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="settings-section account-settings" aria-label="이 기기의 알림">
      <h2>이 기기의 알림</h2>
      <p className="muted">
        내가 직접 켠 기기에만 알림을 보내요. 이름·일정 내용은 잠금화면에 표시하지 않아요.
      </p>
      <p className="settings-hint">
        iPhone: HTTPS 주소를 Safari에서 열고 홈 화면에 추가한 뒤, 홈 화면 앱에서 켜 주세요.
      </p>
      <LoadingRegion busy={pending} label="기기 알림 상태를 확인하는 중">
        <p className="settings-hint push-capability-note">
          {config === null
            ? "\u00a0"
            : !supported
              ? "이 화면에서는 기기 알림을 사용할 수 없어요. HTTPS·홈 화면 앱·브라우저 지원을 확인해 주세요."
              : !config.configured
                ? "서버 알림 설정을 준비 중이에요. 아직 기기 권한을 요청하지 않아요."
                : enabled
                  ? "이 기기에 등록된 알림이 있어요."
                  : "이 기기에는 알림이 꺼져 있어요."}
        </p>
        <div className="calendar-toolbar">
          <button
            type="button"
            className="primary-button"
            disabled={pending || !supported || !config?.configured}
            onClick={enable}
          >
            {enabled ? "기기 등록 갱신" : "이 기기에서 알림 켜기"}
          </button>
          <button
            type="button"
            className="text-button"
            disabled={pending || !supported || !enabled}
            onClick={() => act("test")}
          >
            테스트 알림 보내기
          </button>
        </div>
        <div className="account-settings">
          <h3>기념일 알림</h3>
          <p className="settings-hint">
            한국 시간 오전 9시, 기념일 7일 전·1일 전·당일에 받아요. 이 기기에서 별도로 켠 경우에만
            자동으로 보내요.
          </p>
          <button
            type="button"
            className="text-button notification-switch"
            role="switch"
            aria-checked={automatic}
            aria-label="자동 기념일 알림"
            disabled={pending || !supported || !enabled || !config?.automatic_available}
            onClick={() => act(automatic ? "automatic_off" : "automatic_on")}
          >
            <span>자동 기념일 알림</span>
            <span className="notification-switch-track" aria-hidden="true" />
            <span>{automatic ? "켜짐" : "꺼짐"}</span>
          </button>
          <p className="settings-hint">
            지난 예약은 몰아서 보내지 않아요. 발송은 오전 10시까지 시도하며, 기기와 통신 상태에 따라
            도착이 늦거나 전달되지 않을 수 있어요.
          </p>
        </div>
        <div className="calendar-toolbar">
          <button
            type="button"
            className="text-button"
            disabled={pending || !supported || !hasSubscription}
            onClick={() => act("remove")}
          >
            이 기기 알림 끄기
          </button>
          <button type="button" className="text-button" disabled={pending} onClick={refresh}>
            알림 상태 다시 확인
          </button>
        </div>
      </LoadingRegion>
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
      <p className="settings-hint">
        등록은 30일간 유효해요. 로그아웃하면 이 계정의 모든 기기 알림이 해지되어 다시 켜야 해요.
        테스트는 1분에 한 번 보낼 수 있어요.
      </p>
    </section>
  );
}
