/** Pieces shared by Messages, Actions and Specialists: avatars, reference chips, dates, the reference picker. */
import { Bot, Hash, LoaderCircle, Mail, MailOpen, Search, Star, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useState, type AnchorHTMLAttributes, type MouseEvent, type ReactNode } from "react";
import { collabApi, type RefOption, type ResolvedRef } from "./collabApi";
import { locale, t } from "./i18n";
import { navigate } from "./nav";
import "./collab.css";
import { displayTimeZone, wallClock } from "@plantcraft/ui";

/** PlantCraft's own pages open inside the app; anything else (another app's page) loads in full. */
const LOCAL_PAGE = /^\/(assets|asset-types|actions|messages|users|people|data|calendar|todo|team|admin|attention)(\/|\?|#|$)/;

export function isLocalHref(href: string): boolean {
  return LOCAL_PAGE.test(href);
}

export function Go({ to, className, title, children, ...rest }: { to: string; className?: string; title?: string; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick">) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (!isLocalHref(to) || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  }
  return <a {...rest} href={to} className={className} title={title} onClick={follow}>{children}</a>;
}

/** A favorite's star (owner, 2026-10-28): notifications, conversations and assistant chats. */
export function StarButton({ starred, onToggle, className = "" }: { starred: boolean; onToggle: () => void; className?: string }) {
  const label = starred ? t("Remove from favorites") : t("Add to favorites");
  return <button type="button" className={`co-icon co-star${starred ? " on" : ""}${className ? ` ${className}` : ""}`} onClick={(event) => { event.preventDefault(); event.stopPropagation(); onToggle(); }} title={label} aria-label={label} aria-pressed={starred}><Star /></button>;
}

/** One button that turns read into unread and back (notifications say "seen"). */
export function ReadToggle({ unread, onToggle, seen = false, className = "" }: { unread: boolean; onToggle: () => void; seen?: boolean; className?: string }) {
  const label = unread ? (seen ? t("Mark as seen") : t("Mark as read")) : (seen ? t("Mark as not seen") : t("Mark as unread"));
  return <button type="button" className={`co-icon co-read${className ? ` ${className}` : ""}`} onClick={(event) => { event.preventDefault(); event.stopPropagation(); onToggle(); }} title={label} aria-label={label}>{unread ? <MailOpen /> : <Mail />}</button>;
}

export function initials(value: string) {
  const words = value.trim().split(/[\s.]+/).filter(Boolean);
  return `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? words[0]?.[1] ?? ""}`.toUpperCase() || "?";
}

export function Avatar({ name, bot, size = "md" }: { name: string; bot?: boolean; size?: "sm" | "md" | "lg" }) {
  return <span className={`co-avatar co-avatar-${size}${bot ? " co-avatar-bot" : ""}`} aria-hidden="true">{bot ? <Bot /> : initials(name)}</span>;
}

/** A reference as a chip: a link to its page, or marked when the object no longer exists. */
export function RefChip({ item, label }: { item: ResolvedRef; label?: string }) {
  const text = label ?? item.title ?? item.id;
  const title = item.exists ? `${item.kind_label}: ${item.title}` : t("{kind}: not found", { kind: item.kind_label });
  if (!item.href || !item.exists) return <span className="co-ref co-ref-missing" title={title}><Hash />{text}</span>;
  return <Go to={item.href} className="co-ref" title={title}><Hash />{text}</Go>;
}

/** Whether two times fall on the same day where times are shown (the plant, or this device). */
export function sameDay(a: Date, b: Date) { return wallClock(a.getTime()).slice(0, 10) === wallClock(b.getTime()).slice(0, 10); }

/** "14:05" today, "yesterday", the weekday this week, else the date. */
export function shortWhen(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (sameDay(date, now)) return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone() });
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (sameDay(date, yesterday)) return t("yesterday");
  if (now.getTime() - date.getTime() < 6 * 86400000) return date.toLocaleDateString(locale, { weekday: "short", timeZone: displayTimeZone() });
  return date.toLocaleDateString(locale, { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: displayTimeZone() });
}

export function fullWhen(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short", timeZone: displayTimeZone() });
}

/** A due date (YYYY-MM-DD) in the person's format. */
export function dayText(value?: string | null) {
  if (!value) return "";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(locale, { day: "2-digit", month: "short", year: "numeric" });
}

/** Search the assets and actions a message or an action can point at (GET /api/messages/references). */
export function ReferencePicker({ onPick, onClose, className = "" }: { onPick: (option: RefOption) => void; onClose: () => void; className?: string }) {
  const [q, setQ] = useState("");
  const [options, setOptions] = useState<RefOption[] | null>(null);
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => { collabApi.references(q).then((rows) => { if (live) setOptions(rows); }).catch(() => { if (live) setOptions([]); }); }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [q]);
  return <div className={`co-picker ${className}`} role="dialog" aria-label={t("Choose a reference")}>
    <header><Search /><input autoFocus value={q} placeholder={t("Asset or action…")} aria-label={t("Search references")} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") onClose(); }} /><button type="button" className="co-icon" onClick={onClose} aria-label={t("Close")}><X /></button></header>
    <div className="co-picker-list">{options === null ? <div className="co-picker-empty"><LoaderCircle className="spin" /></div> : options.length ? options.map((option) => <button type="button" key={option.ref} onClick={() => onPick(option)}><span className="co-kind">{option.kind_label}</span><strong>{option.title}</strong><small>{option.detail || option.ref}</small></button>) : <div className="co-picker-empty">{t("Nothing found.")}</div>}</div>
  </div>;
}

/** A reference picked in a form, before the server resolves it. */
export function optionFromRef(ref: string): RefOption {
  const at = ref.indexOf(":");
  const kind = at > 0 ? ref.slice(0, at) : ref;
  return { ref, kind, kind_label: kind, title: at > 0 ? ref.slice(at + 1) : ref, detail: "" };
}

/** The picker's answer for one reference, or the reference as it is. */
export async function resolveOption(ref: string): Promise<RefOption> {
  const fallback = optionFromRef(ref);
  try {
    const rows = await collabApi.references(fallback.title);
    return rows.find((row) => row.ref === ref) ?? fallback;
  } catch {
    return fallback;
  }
}

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function escapeRegex(value: string) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

const LABELLED = /#\[([^\]\n]{1,120})\]\(([a-z][a-z_]{1,31}:[^)\s]+)\)/;

/** Splits a message's text into plain text, **bold** and its references (`#[label](kind:id)`, `#asset:FIC-101` or a plain id). */
export function messageParts(text: string, refs: ResolvedRef[]): Array<{ kind: "text" | "bold"; text: string } | { kind: "ref"; ref: ResolvedRef; text: string }> {
  const tokens: Array<{ needle: string; ref: ResolvedRef }> = [];
  for (const ref of refs) {
    tokens.push({ needle: `#${ref.ref}`, ref });
    // A bare id is a reference only when it reads like one: never a number such as an action's "1".
    if (ref.exists && ref.id && ref.kind !== "user" && !/^\d+$/.test(ref.id)) tokens.push({ needle: ref.id, ref });
  }
  tokens.sort((a, b) => b.needle.length - a.needle.length);
  const alternatives = tokens.map((token) => (token.needle.startsWith("#") ? escapeRegex(token.needle) : `(?<![\\w#:.-])${escapeRegex(token.needle)}(?![\\w-]|\\.\\w)`));
  // A labelled mention, #[label](kind:id) (what the seed and the assistant write), first.
  const pattern = new RegExp([LABELLED.source, `\\*\\*([^*\\n]+)\\*\\*`, ...alternatives.map((item) => `(${item})`)].join("|"), "g");
  const out: ReturnType<typeof messageParts> = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) out.push({ kind: "text", text: text.slice(last, index) });
    if (match[1] !== undefined) {
      const ref = refs.find((item) => item.ref === match[2]);
      out.push(ref ? { kind: "ref", ref, text: match[1] } : { kind: "text", text: match[1] });
    } else if (match[3] !== undefined) out.push({ kind: "bold", text: match[3] });
    else {
      const token = tokens.find((item) => item.needle === match[0]);
      if (token) out.push({ kind: "ref", ref: token.ref, text: token.needle.startsWith("#") ? (token.ref.exists && token.ref.kind !== "action" && token.ref.kind !== "user" ? token.ref.id : token.ref.title || token.ref.id) : token.needle });
      else out.push({ kind: "text", text: match[0] });
    }
    last = index + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** A text with its #references as chips (a message, an action's description or comment). */
export function MentionText({ text, refs, className }: { text: string; refs: ResolvedRef[]; className?: string }) {
  const parts = useMemo(() => messageParts(text, refs), [text, refs]);
  return <p className={className}>{parts.map((part, index) => part.kind === "ref" ? <RefChip key={index} item={part.ref} label={part.text} /> : part.kind === "bold" ? <strong key={index}>{part.text}</strong> : <Fragment key={index}>{part.text}</Fragment>)}</p>;
}

/** The text with its references read as plain words (#asset:FIC-101 -> FIC-101), for previews. */
export function plainMentions(text: string): string {
  return text.replace(/#\[([^\]\n]{1,120})\]\([a-z][a-z_]{1,31}:[^)\s]+\)/g, "$1").replace(/#[a-z][a-z_]{1,31}:([A-Za-z0-9][A-Za-z0-9_.:/-]*[A-Za-z0-9])/g, "$1");
}

/** A person's name, linking to their profile page. */
export function PersonLink({ username, name, className }: { username: string | null | undefined; name?: string | null; className?: string }) {
  if (!username) return <span className="muted">{t("Nobody")}</span>;
  return <Go to={`/people/${encodeURIComponent(username)}`} className={`co-person ${className ?? ""}`.trim()}>{name || username}</Go>;
}
