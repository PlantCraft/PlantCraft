/**
 * The panels the sidebar's quick buttons open (round 8): Messages,
 * Notifications, the Assistant and the work queues all open the same panel. It slides out from
 * under the sidebar's edge over the page and folds back the same way; its width and header are
 * the same everywhere (the title, "Full page", close).
 *
 * One panel at a time for the whole page: opening one closes the others (`claimPanel`). Going from
 * one panel straight to another only swaps what is inside (round 8): the panel
 * that closes goes at once and the one that opens does not slide in, so the frame seems to stay.
 */
import { Maximize2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useDismiss } from "./dismiss.js";
import { t } from "./i18n.js";

export type PanelKind = "messages" | "assistant" | "queues";

type Registered = { close: () => void; isOpen: () => boolean };
const panels = new Map<PanelKind, Registered>();
/** Panels open in another document of the page (the app's assistant inside the frame's iframe). */
const outside = new Set<PanelKind>();

/** How long after a swap the closing panel skips its fold-back and the new one its slide-in. */
export const PANEL_SWAP_MS = 300;
let swapUntil = 0;

/** A panel's store says how it closes and whether it is open, so that another panel opening can close it. */
export function registerPanel(kind: PanelKind, close: () => void, isOpen: () => boolean = () => false) {
  panels.set(kind, { close, isOpen });
}

/** A panel of this kind is open, or closed, in another document (the frame learns it from the app). */
export function setOutsidePanel(kind: PanelKind, open: boolean) {
  if (open) outside.add(kind);
  else outside.delete(kind);
}

/** Whether a panel other than `kind` is open now. */
export function otherPanelOpen(kind: PanelKind): boolean {
  for (const [other, panel] of panels) if (other !== kind && panel.isOpen()) return true;
  for (const other of outside) if (other !== kind) return true;
  return false;
}

/** The next panel to close or open swaps in place (no fold-back, no slide-in). */
export function markPanelSwap(now = Date.now()) { swapUntil = now + PANEL_SWAP_MS; }

/** Whether a swap is under way. */
export function panelSwapping(now = Date.now()): boolean { return now < swapUntil; }

/** Every panel of this document closes (going to another page). */
export function closeAllPanels() { panels.forEach((panel) => panel.close()); }

/**
 * Going to another page or app closes the quick panel that was open, as the
 * list of apps and the person's menu already close. `where` names the page; the first one closes
 * nothing.
 */
export function useClosePanelsOnMove(where: string) {
  const last = useRef(where);
  useEffect(() => {
    if (last.current === where) return;
    last.current = where;
    closeAllPanels();
  }, [where]);
}

/** Called by a panel as it opens: every other panel closes; when one was open, in place. */
export function claimPanel(kind: PanelKind) {
  if (otherPanelOpen(kind)) markPanelSwap();
  panels.forEach((panel, other) => { if (other !== kind) panel.close(); });
}

/** How long the panel takes to fold back (shell.css, `pc-panel-out`). */
export const PANEL_OUT_MS = 160;

/**
 * The last open value, kept for the fold-back animation after it closed: `leaving` is true for
 * those last moments. With reduced motion (or no animation at all) the panel goes at once.
 */
export function usePresence<T>(value: T | null, ms = PANEL_OUT_MS): { value: T | null; leaving: boolean } {
  const [kept, setKept] = useState<T | null>(value);
  const [leaving, setLeaving] = useState(false);
  const last = useRef<T | null>(value);
  useEffect(() => {
    if (value !== null) {
      last.current = value;
      setKept(value);
      setLeaving(false);
      return;
    }
    if (last.current === null) return;
    // A swap to another panel, or reduced motion: gone at once.
    const still = panelSwapping() || (typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    if (still || ms <= 0) { last.current = null; setKept(null); setLeaving(false); return; }
    setLeaving(true);
    const timer = window.setTimeout(() => { last.current = null; setKept(null); setLeaving(false); }, ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return value !== null ? { value, leaving: false } : { value: kept, leaving: leaving && kept !== null };
}

export type SidePanelProps = {
  /** The dialog's name for screen readers and tests ("Messages"). */
  label: string;
  /** The heading; `label` when left out. */
  title?: ReactNode;
  /** A short line under the heading (where the assistant is). */
  subtitle?: string;
  /** Drawn before the heading. */
  icon?: ReactNode;
  /** The panel's own page: "Full page" opens it in the whole window. */
  fullHref?: string | null;
  /** Instead of following `fullHref` (an app that serves the page itself). */
  onFull?: () => void;
  /** Buttons of the panel's own, before "Full page". */
  actions?: ReactNode;
  /** No longer used: every panel has the same width. */
  size?: "narrow" | "wide";
  /** Folding back: drawn, but no longer a dialog anyone can use. */
  leaving?: boolean;
  className?: string;
  onClose: () => void;
  children: ReactNode;
};

/** The panel's frame. Escape, or a click outside it, closes it. */
export function SidePanel({ label, title, subtitle, icon, fullHref, onFull, actions, leaving = false, className, onClose, children }: SidePanelProps) {
  // Opened in place of another panel: no slide-in.
  const [still] = useState(() => panelSwapping());
  const root = useRef<HTMLElement | null>(null);
  // Like the person's menu and the list of apps: Escape or a click outside closes it. The quick
  // buttons open and close panels themselves, and a picker the panel opened keeps it open.
  useDismiss(!leaving, onClose, root, { ignore: ".pcs-quick", keepFloating: true });
  const classes = ["pc-drawer", "pc-side-panel", still ? "pc-side-panel-still" : "", leaving ? "pc-side-panel-leaving" : "", className ?? ""].filter(Boolean).join(" ");
  return <aside ref={root} className={classes} role={leaving ? undefined : "dialog"} aria-label={leaving ? undefined : label} aria-hidden={leaving || undefined} inert={leaving || undefined}>
    <header className="pc-drawer-head">
      {icon}
      <div><strong>{title ?? label}</strong>{subtitle && <small title={subtitle}>{subtitle}</small>}</div>
      {actions}
      {(fullHref || onFull) && <a className="pc-drawer-keep" href={fullHref ?? "#"} title={t("Open on its own page")} onClick={(event) => {
        if (!onFull || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        onFull();
      }}><Maximize2 size={14} aria-hidden="true" />{t("Full page")}</a>}
      <button type="button" className="pc-drawer-close" onClick={onClose} aria-label={t("Close")}><X size={17} /></button>
    </header>
    {children}
  </aside>;
}
