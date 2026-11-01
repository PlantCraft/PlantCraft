/** A public demo's visit (docs/public-demo.md): "Enter the demo" and its line on the sign-in page,
 * then the visit's signs of life, the note before an unused visit closes, and its end. */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Clock3, LoaderCircle, LogOut, MessageCircle } from "lucide-react";
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
export function DemoEntry({ ended, minutes, contactUrl, updating, onEntered }: { ended: boolean; minutes: number; contactUrl?: string; updating?: boolean; onEntered: (username: string) => void }) {
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
    {ended && contactUrl && <a className="demo-ended-contact" href={contactUrl} target="_blank" rel="noopener">{t("Questions about your plant? Talk to us")} <ArrowRight size={14} aria-hidden="true" /></a>}
    <span>{t("A live demo of PlantCraft on a simulated refinery. Look around and try the editors for up to {minutes} minutes: nothing you change is saved. As a public demo, some parts are locked for security.", { minutes })}</span>
    {updating ? <div className="demo-line" role="status">
      <LoaderCircle className="spin" size={16} />
      <span>{t("The demo is being updated with a new version. It will be back in a few minutes: nothing is broken.")}</span>
    </div> : waiting ? <div className="demo-line" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={16} />
      <span>{t("Every place is taken. You are number {position} in line: {wait}. Keep this page open.", { position: waiting.position, wait: waitText(waiting.wait_seconds) })}</span>
    </div>
      : <button type="button" className="button button-primary button-wide" disabled={busy} onClick={() => void ask()}>{busy ? <LoaderCircle className="spin" size={18} /> : <>{ended ? t("Enter the demo again") : t("Enter the demo")} <ArrowRight size={18} /></>}</button>}
    {error && <span className="demo-error">{error}</span>}
  </div>;
}

/** The visit's clock, always on screen: a visit lasts its minutes (30) from the moment it starts,
 * and ends sooner when the visitor leaves it unused for its idle minutes (5); the last of those
 * asks "Still there?". Either way what the visitor did is not kept. Says it is alive every 30 s
 * (with whether the visitor used the page), which also renews the apps' token. */
export const WARN_SECONDS = 2 * 60;
/** The last stretch of an unused visit that asks whether the visitor is still there. */
export const IDLE_WARN_SECONDS = 60;

export function DemoVisitBar({ visit, updatingUrl, onEnded, onLeave }: { visit: DemoVisitInfo; updatingUrl?: string; onEnded: () => void; onLeave: () => void }) {
  const updateAt = useRef(visit.update_seconds == null ? null : Date.now() + visit.update_seconds * 1000);
  const [update, setUpdate] = useState<number | null>(visit.update_seconds ?? null);
  // The update is here: wait for it on the site's page (it opens the demo again once it is back),
  // else on the sign-in page, which says the demo is being updated.
  const updating = useCallback(() => {
    if (updatingUrl) window.location.assign(updatingUrl);
    else onEnded();
  }, [updatingUrl, onEnded]);
  const clockEnds = useRef(Date.now() + visit.clock_seconds * 1000);
  const ends = useRef(Date.now() + visit.seconds_left * 1000);
  const [clock, setClock] = useState(visit.clock_seconds);
  const [left, setLeft] = useState(visit.seconds_left);
  const used = useRef(true);
  // The pages the visitor had in front since the last sign of life (the demo's stats: which pages
  // people open; no clicks, nothing typed).
  const pages = useRef(new Set<string>());
  const beat = useCallback((active: boolean, seen: string[] = []) => demoApi.heartbeat(active, seen.slice(0, 20)).then((answer) => {
    clockEnds.current = Date.now() + answer.clock_seconds * 1000;
    ends.current = Date.now() + answer.seconds_left * 1000;
    updateAt.current = answer.update_seconds == null ? null : Date.now() + answer.update_seconds * 1000;
    setUpdate(answer.update_seconds ?? null);
    setClock(answer.clock_seconds);
    setLeft(answer.seconds_left);
    return suiteApi.renewToken();
  }).catch(() => {
    // The visit ended while an update was announced (or the server is already down for it).
    if (updateAt.current !== null && updateAt.current - Date.now() < 15_000) updating();
  }), [updating]);
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
      setClock(Math.round((clockEnds.current - Date.now()) / 1000));
      setLeft(seconds);
      const toUpdate = updateAt.current === null ? null : Math.round((updateAt.current - Date.now()) / 1000);
      setUpdate(toUpdate);
      if (toUpdate !== null && toUpdate <= 0) updating();
      else if (seconds <= 0) onEnded();
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
  }, [onEnded, beat, updating]);
  // Unused: the visit ends before its clock does, and the last minute asks.
  const idle = left < clock - 1 && left <= IDLE_WARN_SECONDS;
  const late = idle || clock <= WARN_SECONDS;
  return <>{update !== null && <div className="demo-update-banner" role="alert">
    <LoaderCircle size={15} aria-hidden="true" />
    <span>{t("The demo will be updated to a new version in {time}. Your visit ends then and your changes are discarded; it will be back in a few minutes.", { time: clockText(Math.max(update, 0)) })}</span>
  </div>}
  <div className={`demo-visit-bar${late ? " demo-visit-late" : ""}`} role={late ? "alert" : "status"}>
    <Clock3 size={14} aria-hidden="true" />
    <span className="demo-visit-clock" title={t("Each demo visit lasts {minutes} minutes and ends after {idle} minutes without use. Nothing you change is kept, and some parts are locked for security.", { minutes: visit.minutes, idle: visit.idle_minutes })}>{clockText(idle ? left : clock)}</span>
    <span className="demo-visit-note">{idle
      ? t("Still there? Without use, this visit ends and its changes are discarded.")
      : clock <= WARN_SECONDS ? t("Your visit is ending; its changes are discarded.") : t("left in your demo visit")}</span>
    {idle && <button type="button" className="demo-visit-leave" onClick={() => { used.current = false; void beat(true); }}>{t("Keep exploring")}</button>}
    <button type="button" className="demo-visit-leave" onClick={onLeave}><LogOut size={13} aria-hidden="true" />{t("Leave")}</button>
  </div></>;
}

/** The visit's way to the team: a small button at the bottom right on every page, the apps
 * included, that opens the site's contact form in a new tab (``PLANTCRAFT_PUBLIC_DEMO_CONTACT_URL``;
 * none without it). Most visitors come from a post and leave without a word: this is the word. */
export function DemoContact({ url }: { url: string }) {
  return <a className="demo-contact" href={url} target="_blank" rel="noopener" title={t("Questions, a pilot on your plant, a call: the team answers")}>
    <MessageCircle size={15} aria-hidden="true" />{t("Talk to us")}
  </a>;
}
