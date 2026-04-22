"use client";

import { useCallback, useEffect, useState } from "react";

type State =
  | "loading"
  | "unsupported" // no ServiceWorker/PushManager or not served over HTTPS
  | "needs-standalone" // PWA isn't installed to home screen (iOS requirement)
  | "off" // permission pending, not subscribed
  | "on" // subscribed
  | "denied" // user said no; can't re-prompt on iOS
  | "error";

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(display-mode: standalone)").matches) return true;
  // iOS legacy flag still set in some versions.
  return (
    (window.navigator as Navigator & { standalone?: boolean }).standalone ===
    true
  );
}

function urlBase64ToUint8Array(b64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (b64.length % 4)) % 4);
  const base = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function PushToggle() {
  const [state, setState] = useState<State>("loading");

  const refresh = useCallback(async () => {
    try {
      if (
        typeof navigator === "undefined" ||
        !("serviceWorker" in navigator) ||
        !("PushManager" in window)
      ) {
        setState("unsupported");
        return;
      }
      if (!isStandalone()) {
        setState("needs-standalone");
        return;
      }
      if (Notification.permission === "denied") {
        setState("denied");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      setState(sub ? "on" : "off");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    // One-shot async probe of SW + permission + subscription state on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  async function enable() {
    try {
      if (Notification.permission !== "granted") {
        const p = await Notification.requestPermission();
        if (p !== "granted") {
          setState(p === "denied" ? "denied" : "off");
          return;
        }
      }
      const keyRes = await fetch("/api/push/vapid-key");
      const { key } = (await keyRes.json()) as { key: string };
      if (!key) {
        setState("error");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      const r = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!r.ok) throw new Error(`subscribe failed: ${r.status}`);
      setState("on");
    } catch {
      setState("error");
    }
  }

  async function disable() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await fetch("/api/push/subscribe", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      }
      setState("off");
    } catch {
      setState("error");
    }
  }

  // Hide when there's nothing actionable or the app isn't yet installed.
  if (state === "loading" || state === "unsupported" || state === "needs-standalone") {
    return null;
  }

  const label =
    state === "on"
      ? "🔔 on"
      : state === "denied"
        ? "🔕 blocked"
        : state === "error"
          ? "push: err"
          : "🔔 enable";

  return (
    <button
      type="button"
      data-testid="push-toggle"
      data-state={state}
      onClick={state === "on" ? disable : state === "off" ? enable : undefined}
      disabled={state === "denied" || state === "error"}
      className="text-xs px-2 py-1 rounded-full bg-neutral-800 text-neutral-300 disabled:opacity-60"
    >
      {label}
    </button>
  );
}
