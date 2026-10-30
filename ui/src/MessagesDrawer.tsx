/**
 * Messages and Notifications over any app: two of the sidebar's quick buttons
 * open PlantCraft's Messages in a panel from the left, over the page, without leaving the app;
 * closing it returns to the same screen. Messages opens the chats, Notifications the notifications
 * (round 8: one button each, each with its own count). The panel shows PlantCraft's own page
 * (`/messages?embed=1`, `/messages/notifications?embed=1`, same server, the session cookie), so
 * there is one Messages in the suite and the panel is it. The page tells the panel when something
 * was read (`postMessage`, `MESSAGES_CHANGED`) so the counts follow, and opens anything outside
 * Messages in the whole window.
 *
 * One panel at a time (SidePanel.tsx): opening Messages closes the assistant and the queues.
 */
import { Bell, MessagesSquare } from "lucide-react";
import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { isFramed, toFrame } from "./frame.js";
import { t } from "./i18n.js";
import { claimPanel, registerPanel, SidePanel, usePresence } from "./SidePanel.js";

/** What the embedded Messages page posts to the window around it when the unread counts change. */
export const MESSAGES_CHANGED = "processcraft:messages-changed";

let open: string | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };

/** What the Notifications panel opens: Messages' notifications section. */
export const NOTIFICATIONS = "notifications";

/** Open the Messages panel, at a conversation (`"12"`), at its start (`""`) or at the
 * notifications (`NOTIFICATIONS`). */
export function openMessages(conversation = "") {
  // An app inside the platform's frame: the frame draws Messages.
  if (isFramed()) { toFrame({ type: "pc-frame:messages", conversation }); return; }
  claimPanel("messages"); open = conversation; emit();
}
/** Open the Notifications panel. */
export function openNotifications() { openMessages(NOTIFICATIONS); }
export function closeMessages() { if (open === null) return; open = null; emit(); }
registerPanel("messages", closeMessages, () => open !== null);
export function useOpenMessages(): string | null { return useSyncExternalStore(subscribe, () => open, () => null); }

/** The embedded page's address: PlantCraft's Messages with `embed=1`. */
export function embeddedMessagesUrl(messagesHref: string, conversation: string): string {
  const base = conversation ? `${messagesHref.replace(/\/$/, "")}/${encodeURIComponent(conversation)}` : messagesHref;
  return `${base}${base.includes("?") ? "&" : "?"}embed=1`;
}

/** Whether a page runs inside the Messages panel (PlantCraft reads it once at start). */
export function isEmbedded(search = typeof window === "undefined" ? "" : window.location.search): boolean {
  return new URLSearchParams(search).get("embed") === "1";
}

/** From the embedded page: tell the panel's window that the unread counts changed. */
export function announceMessagesChanged() {
  if (typeof window === "undefined" || window.parent === window) return;
  window.parent.postMessage({ type: MESSAGES_CHANGED }, "*");
}

/** The panel, drawn by `SuiteShell`. `onChanged` runs when the page read something, and on close. */
export function MessagesHost({ messagesHref, onChanged }: { messagesHref: string; onChanged: () => void }) {
  const opened = useOpenMessages();
  const { value: conversation, leaving } = usePresence(opened);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  useEffect(() => {
    if (opened === null) return;
    const heard = (event: MessageEvent) => {
      if (event.data && typeof event.data === "object" && (event.data as { type?: unknown }).type === MESSAGES_CHANGED) changed.current();
    };
    window.addEventListener("message", heard);
    return () => {
      window.removeEventListener("message", heard);
      changed.current();
    };
  }, [opened]);
  const close = useCallback(() => closeMessages(), []);
  if (conversation === null) return null;
  const notices = conversation === NOTIFICATIONS;
  const full = conversation ? `${messagesHref.replace(/\/$/, "")}/${encodeURIComponent(conversation)}` : messagesHref;
  const label = notices ? t("Notifications") : t("Messages");
  return <SidePanel label={label} icon={notices ? <Bell size={18} aria-hidden="true" /> : <MessagesSquare size={18} aria-hidden="true" />} fullHref={full} size="wide" leaving={leaving} className="pc-messages-drawer" onClose={close}>
    <iframe className="pc-messages-frame" src={embeddedMessagesUrl(messagesHref, conversation)} title={label} />
  </SidePanel>;
}
