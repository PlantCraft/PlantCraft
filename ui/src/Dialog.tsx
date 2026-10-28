/**
 * The suite's dialogs (scale review A1): one Dialog every app opens its windows in, and
 * confirmAction() in place of the browser's window.confirm, so asking before a delete looks and
 * reads the same in every app, follows the theme and works inside the platform's frame. The
 * styles are in base.css ("Forms and dialogs").
 */
import { X } from "lucide-react";
import { createElement, useEffect, useId, useRef, type FormEvent, type ReactNode, type RefObject } from "react";
import { createRoot } from "react-dom/client";
import { t } from "./i18n.js";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type DialogProps = {
  title: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  /** The buttons at the bottom right: Cancel, then the main action. */
  footer?: ReactNode;
  /** About 1100 px instead of 760 px: a table or an editor. */
  wide?: boolean;
  /** "alertdialog" for a question the person must answer (confirmAction). */
  role?: "dialog" | "alertdialog";
  /** The control to focus when the dialog opens; else its first field or button. */
  initialFocus?: string;
  /** Make the dialog a form: Enter in a field and a submit button in `footer` call this. */
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
};

/**
 * A window over the page: Escape, the × and a click on the dimmed page (until a field is changed)
 * close it; focus moves into it on open, Tab stays inside it, and focus goes back to what opened
 * it when it closes.
 */
export function Dialog({ title, onClose, children, footer, wide, role = "dialog", initialFocus, onSubmit }: DialogProps) {
  const box = useRef<HTMLElement>(null);
  const titleId = useId();
  const edited = useRef(false);
  const latest = useRef(onClose);
  latest.current = onClose;
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = box.current;
    // The first field or button below the title, so the × is not where typing starts.
    const inside = [...(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const first = (initialFocus && root?.querySelector<HTMLElement>(initialFocus))
      || inside.find((item) => !item.closest("header")) || inside[0];
    first?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); latest.current(); return; }
      if (event.key !== "Tab" || !root) return;
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((item) => !item.closest("[hidden]"));
      if (!items.length) return;
      const [head, tail] = [items[0], items[items.length - 1]];
      if (event.shiftKey && document.activeElement === head) { event.preventDefault(); tail.focus(); }
      else if (!event.shiftKey && document.activeElement === tail) { event.preventDefault(); head.focus(); }
    };
    root?.addEventListener("keydown", key);
    return () => {
      root?.removeEventListener("keydown", key);
      if (opener?.isConnected) opener.focus();
    };
  }, [initialFocus]);
  const parts = <>
    <header>
      <h2 id={titleId}>{title}</h2>
      <button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")} title={t("Close")}><X size={18} /></button>
    </header>
    {children}
    {footer && <footer>{footer}</footer>}
  </>;
  // Once a field is typed in, a stray click on the dimmed page no longer throws the work away
  // (Escape, the × and Cancel still close).
  const shared = { className: `dialog${wide ? " dialog-wide" : ""}`, role, "aria-modal": true, "aria-labelledby": titleId, onInput: () => { edited.current = true; } };
  return (
    <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !edited.current) onClose(); }}>
      {onSubmit
        ? <form ref={box as RefObject<HTMLFormElement>} {...shared} onSubmit={(event) => { event.preventDefault(); onSubmit(event); }}>{parts}</form>
        : <div ref={box as RefObject<HTMLDivElement>} {...shared}>{parts}</div>}
    </div>
  );
}

export type ConfirmOptions = {
  /** The dialog's title; "Are you sure?" when left out. */
  title?: string;
  /** The words of the button that goes ahead ("Delete", "Revoke"); "OK" when left out. */
  confirm?: string;
  /** The words of the button that stays; "Cancel" when left out. */
  cancel?: string;
  /** Draw the button that goes ahead as a danger (deleting, revoking). */
  danger?: boolean;
};

/** The question confirmAction() draws. Exported for its tests and for a page that wants it inline. */
export function ConfirmDialog({ message, options, answer }: { message: string; options: ConfirmOptions; answer: (yes: boolean) => void }) {
  return (
    <Dialog
      role="alertdialog"
      title={options.title ?? t("Are you sure?")}
      onClose={() => answer(false)}
      initialFocus=".pc-confirm-yes"
      footer={<>
        <button type="button" className="button button-secondary" onClick={() => answer(false)}>{options.cancel ?? t("Cancel")}</button>
        <button type="button" className={`button ${options.danger ? "button-danger" : "button-primary"} pc-confirm-yes`} onClick={() => answer(true)}>{options.confirm ?? t("OK")}</button>
      </>}
    >
      {message.split(/\n{2,}/).map((part, index) => <p key={index} className="pc-confirm-text">{part}</p>)}
    </Dialog>
  );
}

/**
 * Ask the person before an action, in the suite's dialog: resolves true when they go ahead, false
 * when they cancel, press Escape or click outside. `await confirmAction(...)` takes the place of
 * `window.confirm(...)`; a blank line in `message` starts a new paragraph.
 */
export function confirmAction(message: string, options: ConfirmOptions = {}): Promise<boolean> {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    host.className = "pc-confirm-host";
    document.body.append(host);
    const root = createRoot(host);
    let done = false;
    const answer = (yes: boolean) => {
      if (done) return;
      done = true;
      resolve(yes);
      // Unmounted after the click that answered has finished, never inside React's own handler.
      queueMicrotask(() => { root.unmount(); host.remove(); });
    };
    root.render(createElement(ConfirmDialog, { message, options, answer }));
  });
}
