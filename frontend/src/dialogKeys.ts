import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * What the ui's Dialog does with the keyboard, for the platform's own windows (Modal and the
 * calendar's): focus moves to the first field below the title on open, Escape closes, Tab stays
 * inside, and focus goes back to what opened it on close.
 */
export function useDialogKeys(box: RefObject<HTMLElement | null>, onClose: () => void) {
  const latest = useRef(onClose);
  latest.current = onClose;
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = box.current;
    const inside = [...(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    if (!root?.contains(document.activeElement)) (inside.find((item) => !item.closest("header")) ?? inside[0])?.focus();
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
  }, [box]);
}
