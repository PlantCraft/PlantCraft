/** Messages' Notifications: what came to the person besides conversations, read
 * like an email inbox beside the chats. Apps' notifications (one thread per app and key: an alarm
 * fired, reminded, cleared), changes others made to the person's actions and alarms on what they
 * follow. Opening one marks it seen; one button turns it back to not seen and again; the check marks it
 * done (here, in the quick-access panel, and on the page it opens), out of the list until
 * something new happens to it; the star keeps it among the person's favorites. */
import { AlertTriangle, ArrowLeft, ArchiveRestore, BellRing, Check, CheckCheck, CheckCircle2, ClipboardCheck, ExternalLink, Info, PlayCircle, Siren, Star } from "lucide-react";
import { runNoticeAction } from "@plantcraft/ui";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { errorText, fullWhen, Go, ReadToggle, RefChip, shortWhen, StarButton } from "./collab";
import { collabApi, type Notice, type NoticeCategory, type NoticeFeed } from "./collabApi";
import { t } from "./i18n";
import { followNotice } from "./NoticeFollowUp";

export const NOTICE_POLL = 20_000;

export type NoticeFilter = "all" | "unread" | "starred" | "alarm" | "action" | "run" | "archived";

const CATEGORY_ICON: Record<NoticeCategory, ReactNode> = {
  alarm: <Siren aria-hidden="true" />,
  action: <ClipboardCheck aria-hidden="true" />,
  run: <PlayCircle aria-hidden="true" />,
  info: <Info aria-hidden="true" />,
};

/** Which entries a filter and a search keep; done ones only under "Done"; favorites, done or not, under "Favorites". */
export function filterNotices(items: Notice[], filter: NoticeFilter, query: string): Notice[] {
  const needle = query.trim().toLowerCase();
  return items.filter((item) => {
    if (filter === "starred") { if (!item.starred) return false; }
    else if (filter === "archived" ? item.state !== "archived" : item.state === "archived") return false;
    if (filter === "unread" && item.state !== "unread") return false;
    if ((filter === "alarm" || filter === "action" || filter === "run") && item.category !== filter) return false;
    return !needle || `${item.title} ${item.detail} ${item.from}`.toLowerCase().includes(needle);
  });
}

/** The feed, read now and every 20 s while the page is visible; `mark` changes it at once. */
export function useNotices(onChange: () => void) {
  const [feed, setFeed] = useState<NoticeFeed | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setFeed(await collabApi.notifications()); setError(""); } catch (err) { setError(errorText(err)); }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, NOTICE_POLL);
    return () => window.clearInterval(timer);
  }, [load]);
  const mark = useCallback(async (keys: string[], state: "read" | "archived" | null) => {
    if (!keys.length) return;
    const next = state === "archived" ? "archived" : state === "read" ? "read" : "unread";
    setFeed((current) => current && { ...current, items: current.items.map((item) => (keys.includes(item.key) ? { ...item, state: next } : item)) });
    try { await collabApi.markNotifications(keys, state); onChange(); } catch (err) { setError(errorText(err)); }
    void load();
  }, [load, onChange]);
  const star = useCallback(async (key: string, on: boolean) => {
    setFeed((current) => current && { ...current, items: current.items.map((item) => (item.key === key ? { ...item, starred: on } : item)) });
    try { await collabApi.mark(key, "star", on); } catch (err) { setError(errorText(err)); }
    void load();
  }, [load]);
  return { feed, error, mark, star, reload: load };
}

const FILTERS: Array<{ id: NoticeFilter; label: string }> = [
  { id: "all", label: t("All") },
  { id: "unread", label: t("Unread") },
  { id: "starred", label: t("Favorites") },
  { id: "alarm", label: t("Alarms") },
  { id: "action", label: t("Actions") },
  { id: "run", label: t("Runs") },
  { id: "archived", label: t("Done") },
];

export function NoticeList({ feed, error, query, selected, onSelect, onMarkAll, onMark, onStar }: { feed: NoticeFeed | null; error: string; query: string; selected: string | null; onSelect: (item: Notice) => void; onMarkAll: () => void; onMark: (item: Notice, state: "read" | "archived" | null) => void; onStar: (item: Notice) => void }) {
  const [filter, setFilter] = useState<NoticeFilter>("all");
  const shown = useMemo(() => filterNotices(feed?.items ?? [], filter, query), [feed, filter, query]);
  const unread = feed?.counts.unread ?? 0;
  return <>
    <div className="nt-filters" role="toolbar" aria-label={t("Show")}>
      {FILTERS.map((item) => <button key={item.id} type="button" className={`nt-chip${filter === item.id ? " on" : ""}`} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>{item.label}</button>)}
      {unread > 0 && <button type="button" className="nt-markall" onClick={onMarkAll} title={t("Mark all as read")}><CheckCheck size={14} />{t("Mark all as read")}</button>}
    </div>
    {error && <div className="form-error msg-error"><AlertTriangle size={15} /> {error}</div>}
    <ul className="msg-conversations nt-list">
      {feed === null && !error && <li className="msg-list-empty">{t("Loading…")}</li>}
      {shown.map((item) => <li key={item.key} className="nt-row">
        <button type="button" className={`nt-item nt-${item.category} nt-priority-${item.priority}${item.state === "unread" ? " unread" : ""}${selected === item.key ? " active" : ""}`} onClick={() => onSelect(item)}>
          <span className="nt-icon">{CATEGORY_ICON[item.category]}</span>
          <span className="msg-item-main">
            <span className="msg-item-top"><strong>{item.title}</strong>{item.starred && <Star className="nt-starred" aria-label={t("Favorite")} />}<time dateTime={item.at} title={fullWhen(item.at)}>{shortWhen(item.at)}</time></span>
            <span className="msg-item-bottom"><small>{item.from}{item.detail ? ` · ${item.detail.replace(/\s+/g, " ").slice(0, 110)}` : ""}</small>{item.history.length > 1 && <b className="nt-count" aria-label={t("{count} updates", { count: item.history.length })}>{item.history.length}</b>}</span>
          </span>
        </button>
        <NoticeTools item={item} onMark={(state) => onMark(item, state)} onStar={() => onStar(item)} className="nt-row-tools" />
      </li>)}
      {feed !== null && !shown.length && <li className="msg-list-empty">{query ? t("Nothing found.") : filter === "archived" ? t("Nothing marked done.") : filter === "starred" ? t("No favorites yet. The star keeps a notification here.") : t("No notifications. Alarms, runs and changes to your actions arrive here.")}</li>}
    </ul>
  </>;
}

/** A notification's own buttons, in its row and on top of it: seen or not, favorite, done (or back from done). */
export function NoticeTools({ item, onMark, onStar, className }: { item: Notice; onMark: (state: "read" | "archived" | null) => void; onStar: () => void; className: string }) {
  const done = item.state === "archived";
  return <span className={className}>
    {!done && <ReadToggle seen unread={item.state === "unread"} onToggle={() => onMark(item.state === "unread" ? "read" : null)} />}
    <StarButton starred={Boolean(item.starred)} onToggle={onStar} />
    {done
      ? <button type="button" className="co-icon" onClick={(event) => { event.stopPropagation(); onMark("read"); }} title={t("Back to the notifications")} aria-label={t("Back to the notifications")}><ArchiveRestore /></button>:
      <button type="button" className="co-icon nt-done" onClick={(event) => { event.stopPropagation(); onMark("archived"); }} title={t("Mark as done")} aria-label={t("Mark as done")}><Check /></button>}
  </span>;
}

/** One entry, read like an email: what, from whom, its buttons and what happened before. */
export function NoticePane({ item, onBack, onMark, onStar, onActed }: { item: Notice; onBack: () => void; onMark: (state: "read" | "archived" | null) => void; onStar: () => void; onActed?: () => void }) {
  // A button that runs a call in the app that sent it ("Acknowledge"), as this person.
  const [running, setRunning] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null);
  const run = async (href: string, label: string) => {
    setRunning(label);
    setOutcome(null);
    const answer = await runNoticeAction(href);
    setRunning(null);
    setOutcome(answer);
    if (answer.ok) onActed?.();
  };
  return <section className="msg-chat nt-pane" aria-label={item.title}>
    <header className="msg-chat-head nt-head">
      <button type="button" className="co-icon msg-back" onClick={onBack} aria-label={t("Back")}><ArrowLeft /></button>
      <span className={`nt-icon nt-${item.category} nt-priority-${item.priority}`}>{CATEGORY_ICON[item.category]}</span>
      <div className="nt-head-text"><h2>{item.title}</h2><small>{item.from} · <time dateTime={item.at} title={fullWhen(item.at)}>{shortWhen(item.at)}</time>{item.priority_label ? ` · ${item.priority_label}` : ""}</small></div>
      <NoticeTools item={item} onMark={onMark} onStar={onStar} className="nt-tools" />
    </header>
    <div className="msg-scroll nt-body">
      {item.detail && <p className="nt-text">{item.detail}</p>}
      {item.resolved && <p className="nt-resolved"><CheckCircle2 size={15} aria-hidden="true" />{item.resolved.note || t("Resolved")}<time dateTime={item.resolved.at} title={fullWhen(item.resolved.at)}>{shortWhen(item.resolved.at)}</time></p>}
      {(item.href || item.actions.length > 0) && <div className="nt-buttons">
        {item.actions.map((action) => action.method === "POST"
          ? <button key={action.href + action.label} type="button" className="button button-secondary" disabled={running !== null} onClick={() => void run(action.href, action.label)}>{running === action.label ? t("Working…") : action.label}</button>:
          <Go key={action.href + action.label} to={action.href} className="button button-secondary">{action.label}</Go>)}
        {item.href && <Go to={item.href} className="button button-primary" onClickCapture={() => followNotice(item)}><ExternalLink size={15} />{t("Open")}</Go>}
      </div>}
      {outcome && <p className={outcome.ok ? "nt-outcome" : "form-error"} role="status">{outcome.message}</p>}
      {item.refs.length > 0 && <div className="co-about">{item.refs.map((ref) => <RefChip key={ref.ref} item={ref} label={`${ref.kind_label}: ${ref.title || ref.id}`} />)}</div>}
      {item.history.length > 1 && <>
        <h3 className="nt-history-title">{t("What happened")}</h3>
        <ol className="nt-history">{item.history.map((step, index) => <li key={`${step.at}-${index}`}>
          <BellRing size={13} aria-hidden="true" /><span><b>{step.title}</b>{step.text && <small>{step.text}</small>}</span><time dateTime={step.at} title={fullWhen(step.at)}>{shortWhen(step.at)}</time>
        </li>)}</ol>
      </>}
    </div>
  </section>;
}
