/** A public demo's visit (docs/public-demo.md): "Enter the demo" and its line on the sign-in page,
 * then the visit's signs of life, the note before an unused visit closes, and its end. */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Clock3, LoaderCircle, LogOut } from "lucide-react";
import { clockText, demoApi, waitText, type DemoVisitInfo, type Waiting } from "./demoApi";
import { startGuide } from "./DemoGuide";
import { t } from "./i18n";
import { suiteApi } from "./suiteApi";

/** How often a waiting browser asks again (the server forgets a ticket after 30 s of silence). */
const LINE_MS = 5_000;
/** How often the visit's frame says it is alive and renews the apps' token (it lives 2 minutes). */
const HEARTBEAT_MS = 30_000;

/** The public demo's way in, its only one (one short line and one button, nothing
 * that scares a first visitor): enter, or wait in line until a place frees. The platform's tour
 * opens inside; the guides by role are in the menu under the visitor's name. */
export function DemoEntry({ ended, onEntered }: { ended: boolean; onEntered: (username: string) => void }) {
  const [waiting, setWaiting] = useState<Waiting | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ticket = useRef<string | null>(null);
  async function ask() {
    setBusy(true);
    setError("");
    try {
      const answer = await demoApi.enter(ticket.current);
      if (answer.entered) { setWaiting(null); startGuide(null); onEntered(answer.username ?? ""); return; }
      ticket.current = answer.ticket;
      setWaiting(answer);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't enter the demo."));
      setWaiting(null);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setTimeout(() => void ask(), LINE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting]);
  return <div className="login-demo" role="note">
    {ended && <span className="demo-ended">{t("Your demo visit ended. Thank you for trying PlantCraft!")}</span>}
    <span>{t("A live demo of PlantCraft on a simulated refinery. Look around and try anything: nothing you change is saved.")}</span>
    {waiting ? <div className="demo-line" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={16} />
      <span>{t("Every place is taken. You are number {position} in line: {wait}. Keep this page open.", { position: waiting.position, wait: waitText(waiting.wait_seconds) })}</span>
    </div>:
      <button type="button" className="button button-primary button-wide" disabled={busy} onClick={() => void ask()}>{busy ? <LoaderCircle className="spin" size={18} /> : <>{ended ? t("Enter the demo again") : t("Enter the demo")} <ArrowRight size={18} /></>}</button>}
    {error && <span className="demo-error">{error}</span>}
  </div>;
}

/** When the visit's place is given back unless the visitor comes back: nothing shows while they use
 * the demo (no clock); a visit left unused for its minutes (30) ends, so a tab
 * forgotten for days does not hold a place, and the last 5 of them say so. Says it is alive every
 * 30 s (with whether the visitor used the page), which also renews the apps' token. */
export const WARN_SECONDS = 5 * 60;

export function DemoVisitBar({ visit, onEnded, onLeave }: { visit: DemoVisitInfo; onEnded: () => void; onLeave: () => void }) {
  const ends = useRef(Date.now() + visit.seconds_left * 1000);
  const [left, setLeft] = useState(visit.seconds_left);
  const used = useRef(true);
  // The pages the visitor had in front since the last sign of life (the demo's stats: which pages
  // people open; no clicks, nothing typed).
  const pages = useRef(new Set<string>());
  const beat = useCallback((active: boolean, seen: string[] = []) => demoApi.heartbeat(active, seen.slice(0, 20)).then((answer) => {
    ends.current = Date.now() + answer.seconds_left * 1000;
    setLeft(answer.seconds_left);
    return suiteApi.renewToken();
  }).catch(() => undefined), []);
  useEffect(() => {
    // Any use of the page, the apps' frames included (same origin: listened to as they appear).
    const mark = () => { used.current = true; };
    const events = ["pointerdown", "keydown", "wheel", "touchstart"] as const;
    const listened = new WeakSet<EventTarget>();
    const listen = (target: EventTarget | null) => {
      if (!target || listened.has(target)) return;
      try {
        events.forEach((name) => target.addEventListener(name, mark, { passive: true }));
        listened.add(target);
      } catch { /* another origin */ }
    };
    listen(window);
    const tick = window.setInterval(() => {
      if (document.visibilityState === "visible") pages.current.add(window.location.pathname);
      document.querySelectorAll("iframe").forEach((frame) => {
        try { listen(frame.contentDocument); } catch { /* another origin */ }
        try {
          if (frame.offsetParent !== null && document.visibilityState === "visible" && frame.contentWindow) pages.current.add(frame.contentWindow.location.pathname);
        } catch { /* another origin */ }
      });
      const seconds = Math.round((ends.current - Date.now()) / 1000);
      setLeft(seconds);
      if (seconds <= 0) onEnded();
    }, 1000);
    const timer = window.setInterval(() => {
      const active = used.current;
      used.current = false;
      const seen = [...pages.current];
      pages.current.clear();
      void beat(active, seen);
    }, HEARTBEAT_MS);
    return () => {
      events.forEach((name) => window.removeEventListener(name, mark));
      window.clearInterval(tick);
      window.clearInterval(timer);
    };
  }, [onEnded, beat]);
  if (left > WARN_SECONDS) return null;
  return <div className="demo-visit-bar demo-visit-late" role="alert">
    <Clock3 size={14} aria-hidden="true" />
    <span className="demo-visit-note">{t("Still there? This demo visit closes in {time} without use.", { time: clockText(left) })}</span>
    <button type="button" className="demo-visit-leave" onClick={() => { used.current = false; void beat(true); }}>{t("Keep exploring")}</button>
    <button type="button" className="demo-visit-leave" onClick={onLeave}><LogOut size={13} aria-hidden="true" />{t("Leave")}</button>
  </div>;
}
