/** The notification a person opened, on the page it opened ("dar o check na
 * notificação dentro da action"): a small bar says where they came from and marks it done there,
 * without going back to Notifications. It lives in this tab (sessionStorage), so it also follows a
 * notification opened from the quick-access panel of any app; it goes when the person moves on. */
import { useEffect, useState } from "react";
import { Bell, Check, X } from "lucide-react";
import { collabApi, type Notice } from "./collabApi";
import { t } from "./i18n";
import { EMBEDDED } from "./nav";
import "./collab.css";

const KEY = "processcraft:notice-follow-up";
const CHANGED = "processcraft:notice-follow-up-changed";

/** `shown`: its page was reached once (leaving that page ends it). */
export type FollowUp = { key: string; title: string; path: string; shown?: boolean; done?: boolean };

function read(): FollowUp | null {
  try { return JSON.parse(window.sessionStorage.getItem(KEY) ?? "null") as FollowUp | null; } catch { return null; }
}

function write(value: FollowUp | null) {
  try { if (value) window.sessionStorage.setItem(KEY, JSON.stringify(value)); else window.sessionStorage.removeItem(KEY); } catch { /* private mode: no bar */ }
  window.dispatchEvent(new Event(CHANGED));
}

/** The page part of a notification's link ("/actions/12?x=1" is "/actions/12"). */
export function hrefPath(href: string): string {
  return href.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
}

/** Whether `path` is the notification's page (or a page inside it). */
export function onNoticePage(path: string, follow: Pick<FollowUp, "path">): boolean {
  const page = hrefPath(path);
  return page === follow.path || page.startsWith(`${follow.path}/`);
}

/** Called as the person opens a notification's page. */
export function followNotice(item: Pick<Notice, "key" | "title" | "href" | "state">) {
  if (!item.href || item.state === "archived") return;
  write({ key: item.key, title: item.title, path: hrefPath(item.href) });
}

export function NoticeFollowUp({ path }: { path: string }) {
  const [follow, setFollow] = useState<FollowUp | null>(() => (EMBEDDED ? null : read()));
  const [error, setError] = useState("");
  useEffect(() => {
    if (EMBEDDED) return;
    const changed = () => setFollow(read());
    window.addEventListener(CHANGED, changed);
    return () => window.removeEventListener(CHANGED, changed);
  }, []);
  const here = follow ? onNoticePage(path, follow) : false;
  useEffect(() => {
    if (!follow) return;
    if (here && !follow.shown) write({ ...follow, shown: true });
    else if (!here && follow.shown) write(null);
  }, [follow, here]);
  useEffect(() => {
    if (!follow?.done) return;
    const timer = window.setTimeout(() => write(null), 2500);
    return () => window.clearTimeout(timer);
  }, [follow]);
  if (!follow || !here) return null;
  async function done() {
    if (!follow) return;
    try { await collabApi.markNotifications([follow.key], "archived"); setError(""); write({ ...follow, done: true }); } catch { setError(t("Could not mark it done. Try again.")); }
  }
  return <div className="nt-follow" role="status">
    <Bell size={15} aria-hidden="true" />
    <span className="nt-follow-text">{follow.done ? t("Notification marked done") : <>{t("From a notification:")} <strong>{follow.title}</strong></>}</span>
    {error && <span className="form-error">{error}</span>}
    {!follow.done && <button type="button" className="button button-primary button-small" onClick={() => void done()}><Check size={15} />{t("Mark as done")}</button>}
    <button type="button" className="co-icon" onClick={() => write(null)} title={t("Close")} aria-label={t("Close")}><X /></button>
  </div>;
}
