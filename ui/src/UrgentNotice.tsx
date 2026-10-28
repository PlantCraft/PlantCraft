/**
 * A critical or high notification pops up in whatever app the person has open (owner,
 * 2026-10-26, docs/quick-access.md), with the buttons the app gave it: "Acknowledge" runs the
 * call in that app as the person, without opening Alarms. The inbox (`GET /api/v1/inbox`,
 * `urgent_notification`) names the newest unread one of the last hour; once closed, acted on or
 * opened, it does not pop up again in this tab.
 */
import { BellRing, X } from "lucide-react";
import { useState } from "react";
import { t } from "./i18n.js";

/** A notification's button: GET opens the page, POST runs the call in the app that sent it. */
export type NoticeAction = { label: string; href: string; method?: "GET" | "POST" };

/** `urgent_notification` of the inbox. */
export type UrgentNotice = {
  key: string;
  title: string;
  detail?: string;
  priority: string;
  priority_label?: string | null;
  from?: string;
  at?: string;
  href?: string | null;
  actions: NoticeAction[];
};

/**
 * Runs a notification's POST button: the app's own path, as the person (same server, the
 * session cookie). `ok` with the app's answer, or what the app said went wrong ("You cannot
 * acknowledge this alarm.").
 */
export async function runNoticeAction(href: string, fetcher: typeof fetch = fetch): Promise<{ ok: boolean; message: string }> {
  try {
    const response = await fetcher(href, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: "{}" });
    if (response.ok) return { ok: true, message: t("Done") };
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown } | null;
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch { /* not JSON */ }
    if (response.status === 401) return { ok: false, message: t("Sign in again to do this.") };
    if (response.status === 403) return { ok: false, message: detail || t("You cannot do this here.") };
    return { ok: false, message: detail || t("It did not work ({status}). Open it to try there.", { status: response.status }) };
  } catch {
    return { ok: false, message: t("The app did not answer. Try again in a moment.") };
  }
}

const SEEN_KEY = "pcs-urgent-seen";
const seen = new Set<string>(readSeen());

function readSeen(): string[] {
  try {
    const raw = typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(SEEN_KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(list) ? list.filter((item): item is string => typeof item === "string").slice(-50) : [];
  } catch {
    return [];
  }
}

/** This pop-up was closed, acted on or opened: not again in this tab. */
export function markUrgentSeen(key: string) {
  seen.add(key);
  try { sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-50))); } catch { /* private window */ }
}

/** Whether this notification should still pop up. */
export function urgentDue(notice: UrgentNotice | null | undefined): notice is UrgentNotice {
  return Boolean(notice && notice.key && !seen.has(notice.key));
}

/** The pop-up: priority and title, the app's buttons, Open (the Notifications panel) and close. */
export function UrgentToast({ notice, onOpen, onChanged }: { notice: UrgentNotice; onOpen: () => void; onChanged: () => void }) {
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [, setGone] = useState(0);
  const close = () => { markUrgentSeen(notice.key); setGone((value) => value + 1); };
  const run = async (action: NoticeAction) => {
    setBusy(action.label);
    const answer = await runNoticeAction(action.href);
    setBusy("");
    setResult(answer);
    if (answer.ok) {
      onChanged();
      window.setTimeout(close, 1500);
    }
  };
  if (seen.has(notice.key)) return null;
  return (
    <div className={`pcs-toast pcs-urgent pcs-urgent-${notice.priority}`} role="alert">
      <BellRing size={17} aria-hidden="true" />
      <div className="pcs-urgent-main">
        <strong>{notice.priority_label ? `${notice.priority_label} · ` : ""}{notice.title}</strong>
        {notice.from && <small>{notice.from}</small>}
        {result && <small className={result.ok ? "pcs-urgent-ok" : "pcs-urgent-error"}>{result.message}</small>}
        <div className="pcs-urgent-buttons">
          {!result?.ok && notice.actions.map((action) => action.method === "POST"
            ? <button key={action.label} type="button" className="pcs-urgent-button pcs-urgent-primary" disabled={Boolean(busy)} onClick={() => void run(action)}>{busy === action.label ? t("Working…") : action.label}</button>
            : <a key={action.label} className="pcs-urgent-button" href={action.href} onClick={close}>{action.label}</a>)}
          <button type="button" className="pcs-urgent-button" onClick={() => { close(); onOpen(); }}>{t("Open")}</button>
        </div>
      </div>
      <button type="button" className="pcs-urgent-close" onClick={close} aria-label={t("Close")}><X size={15} /></button>
    </div>
  );
}
