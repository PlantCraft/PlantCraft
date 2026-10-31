/**
 * A short message in a corner of the page that goes away on its own: what went wrong after a
 * click (a run that would not cancel), or that something worked. It replaces `window.alert`,
 * which blocks the page and looks like the browser's, not the suite's. Any app calls
 * `showToast(text, { tone })`; the stack is created on first use under `document.body`, read by
 * screen readers (`role="status"`, errors `role="alert"`), and each toast closes with its button,
 * Escape, or after `ms` (6 s; errors 10 s). Styles: `.pc-toasts`, `.pc-toast` in base.css.
 */

export type ToastTone = "info" | "ok" | "error";
export type ToastOptions = { tone?: ToastTone; ms?: number };

import { t } from "./i18n.js";

const STACK_ID = "pc-toasts";
const MAX_SHOWN = 4;

function stack(doc: Document): HTMLElement {
  let found = doc.getElementById(STACK_ID);
  if (!found) {
    found = doc.createElement("div");
    found.id = STACK_ID;
    found.className = "pc-toasts";
    doc.body.appendChild(found);
  }
  return found;
}

/** Shows ``text``; returns a function that closes it now. */
export function showToast(text: string, options: ToastOptions = {}, doc: Document = document): () => void {
  const tone = options.tone ?? "info";
  const ms = options.ms ?? (tone === "error" ? 10_000 : 6_000);
  const host = stack(doc);
  while (host.children.length >= MAX_SHOWN) host.firstElementChild?.remove();
  const item = doc.createElement("div");
  item.className = `pc-toast pc-toast-${tone}`;
  item.setAttribute("role", tone === "error" ? "alert" : "status");
  const body = doc.createElement("span");
  body.className = "pc-toast-text";
  body.textContent = text;
  const close = doc.createElement("button");
  close.type = "button";
  close.className = "pc-toast-close";
  close.setAttribute("aria-label", t("Close"));
  close.textContent = "×";
  item.append(body, close);
  host.appendChild(item);
  let timer: ReturnType<typeof setTimeout> | null = null;
  const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") dismiss(); };
  function dismiss() {
    if (timer) clearTimeout(timer);
    timer = null;
    doc.removeEventListener("keydown", onKey);
    item.remove();
  }
  close.addEventListener("click", dismiss);
  doc.addEventListener("keydown", onKey);
  if (ms > 0) timer = setTimeout(dismiss, ms);
  return dismiss;
}
