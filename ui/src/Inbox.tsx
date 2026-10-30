/**
 * The Messages and Notifications buttons every app shows in its sidebar (docs/collaboration.md):
 * they read the person's inbox from PlantCraft's API v1 (`GET /api/v1/inbox`, same host, the token
 * cookie), each with its own unread count, and open PlantCraft's Messages in a panel.
 */
import { Bell, MessagesSquare } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { t } from "./i18n.js";
import type { SuiteApp } from "./SuiteShell.js";
import type { NoticeAction, UrgentNotice } from "./UrgentNotice.js";

/** GET /api/v1/inbox. `urgent_notification` (PlantCraft with SDK 0.53.0): the newest unread
 * critical or high notification of the last hour, which pops up in every app. */
export type InboxCounts = { unread_messages: number; open_actions: number; messages_url: string; actions_url: string; unread_notifications?: number; urgent_notification?: UrgentNotice | null };

/** What the messages button counts: unread chat messages and unread notifications (PlantCraft 0.3
 * counts them apart since ui 0.34.0; older platforms send only ``unread_messages``). */
export function unreadCount(counts: InboxCounts | null | undefined): number {
  if (!counts) return 0;
  return counts.unread_messages + (counts.unread_notifications ?? 0);
}

/** Every 15 s while the page is visible (an alarm must reach people at once). */
export const INBOX_POLL_MS = 15_000;

/** What the sidebar knows: the counts (null: no badge) and whether the person may not use Messages. */
export type InboxState = { counts: InboxCounts | null; forbidden: boolean };

/**
 * The inbox; "forbidden" on a 403 (dashboards-only accounts and service tokens cannot use
 * Messages); null when PlantCraft has none (404, an older version), on 401 or when anything fails.
 */
export async function fetchInbox(): Promise<InboxCounts | "forbidden" | null> {
  try {
    const response = await fetch("/api/v1/inbox", { credentials: "same-origin" });
    if (response.status === 403) return "forbidden";
    if (!response.ok) return null;
    const data = (await response.json()) as Partial<InboxCounts> | null;
    if (!data || typeof data !== "object") return null;
    return {
      unread_messages: Math.max(0, Number(data.unread_messages) || 0),
      open_actions: Math.max(0, Number(data.open_actions) || 0),
      ...(data.unread_notifications !== undefined ? { unread_notifications: Math.max(0, Number(data.unread_notifications) || 0) } : {}),
      ...(data.urgent_notification !== undefined ? { urgent_notification: urgentFrom(data.urgent_notification) } : {}),
      messages_url: typeof data.messages_url === "string" ? data.messages_url : "/messages",
      actions_url: typeof data.actions_url === "string" ? data.actions_url : "/actions",
    };
  } catch {
    return null;
  }
}

/** The inbox's urgent notification, checked; null for anything else. */
export function urgentFrom(raw: unknown): UrgentNotice | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.key !== "string" || typeof item.title !== "string") return null;
  const actions: NoticeAction[] = Array.isArray(item.actions)
    ? item.actions.flatMap((entry) => {
        const action = entry as Record<string, unknown> | null;
        if (!action || typeof action.label !== "string" || typeof action.href !== "string" || !action.href.startsWith("/") || action.href.startsWith("//")) return [];
        return [{ label: action.label, href: action.href, method: action.method === "POST" ? "POST" as const : "GET" as const }];
      }).slice(0, 3):
    [];
  const text = (value: unknown) => (typeof value === "string" ? value : undefined);
  const href = text(item.href);
  return { key: item.key, title: item.title, detail: text(item.detail), priority: text(item.priority) ?? "high", priority_label: text(item.priority_label) ?? null, from: text(item.from), at: text(item.at), href: href && href.startsWith("/") && !href.startsWith("//") ? href : null, actions };
}

/**
 * The person's inbox: read at once, every INBOX_POLL_MS while the page is visible, when the window gets the focus again and
 * whenever `refresh` changes (PlantCraft bumps it after a conversation was read).
 */
export function useInbox(options: { enabled?: boolean; refresh?: number } = {}): InboxState {
  const { enabled = true, refresh = 0 } = options;
  const [inbox, setInbox] = useState<InboxState>({ counts: null, forbidden: false });
  useEffect(() => {
    if (!enabled) {
      setInbox({ counts: null, forbidden: false });
      return;
    }
    let live = true;
    const read = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void fetchInbox().then((value) => {
        if (live) setInbox(value === "forbidden" ? { counts: null, forbidden: true } : { counts: value, forbidden: false });
      });
    };
    read();
    const timer = window.setInterval(read, INBOX_POLL_MS);
    window.addEventListener("focus", read);
    return () => {
      live = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", read);
    };
  }, [enabled, refresh]);
  return inbox;
}

/** The badge text: nothing at 0, "99+" above 99. */
export function inboxBadge(count: number | null | undefined): string {
  if (!count || count <= 0) return "";
  return count > 99 ? "99+" : String(Math.floor(count));
}

/** PlantCraft's Messages page: its entry of the suite's apps joined with "messages". */
export function messagesUrl(apps: SuiteApp[]): string {
  return platformUrl(apps, "messages");
}

/** A page of PlantCraft from any app: "people/me" is the person's own profile. */
export function platformUrl(apps: SuiteApp[], page: string): string {
  const base = apps.find((entry) => entry.id === "processcraft")?.url;
  if (!base) return `/${page}`;
  return `${base.endsWith("/") ? base : `${base}/`}${page}`;
}

/** The messages button beside the person's name: an icon with the unread count on it (owner,
 * 2026-10-23: new messages must be seen at a glance), opening the inbox. */
export function InboxButton({ href, unread, collapsed, active, onOpen, kind = "messages" }: { href: string; unread: number; collapsed: boolean; active?: boolean; onOpen?: () => void; kind?: "messages" | "notifications" }) {
  const badge = inboxBadge(unread);
  const notices = kind === "notifications";
  const label = notices ? t("Notifications") : t("Messages");
  const hint = badge ? (notices ? t("Notifications, {count} unread", { count: badge }) : t("Messages, {count} unread", { count: badge })) : label;
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (!onOpen || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onOpen();
  }
  return (
    <a href={href} onClick={follow} className={`pcs-quick-button pcs-inbox ${notices ? "pcs-notifications" : "pcs-messages"}${active ? " pcs-active" : ""}${collapsed ? " pcs-inbox-folded" : ""}`} aria-label={hint} aria-current={active ? "page" : undefined} title={hint}>
      {notices ? <Bell size={18} aria-hidden="true" /> : <MessagesSquare size={18} aria-hidden="true" />}
      {badge && <b className="pcs-badge" aria-hidden="true">{badge}</b>}
    </a>
  );
}
