/**
 * Everything that floats over the page closes the same way: the person's menu,
 * the list of apps and the quick panels close on Escape and on a click anywhere outside them,
 * including a click on an app's page inside the frame's iframe (the click lands in another
 * document, so this window only sees its focus leave for that iframe).
 */
import { useEffect, useRef } from "react";

/** Floating parts a click may land on without closing what is open (dialogs and lists opened from it). */
const KEEP_OPEN = '[role="dialog"], [role="alertdialog"], [role="listbox"], [role="tooltip"]';

export type DismissOptions = {
  /** Clicks inside these (a selector) leave it open: the buttons that toggle it themselves. */
  ignore?: string;
  /** Leave dialogs and lists that float over the page alone (a panel's own pickers). */
  keepFloating?: boolean;
};

/** Whether a click on `target` is outside `root` and outside what `options` keeps. */
export function clickedOutside(root: Element | null, target: EventTarget | null, options: DismissOptions = {}): boolean {
  if (!root || !(target instanceof Node)) return false;
  if (root.contains(target)) return false;
  const element = target instanceof Element ? target : target.parentElement;
  if (options.ignore && element?.closest(options.ignore)) return false;
  if (options.keepFloating && element?.closest(KEEP_OPEN)) return false;
  return true;
}

/** While `open`, Escape or a click outside `root` (or into an iframe outside it) calls `close`. */
export function useDismiss(open: boolean, close: () => void, root: { current: Element | null }, options: DismissOptions = {}) {
  const latest = useRef(close);
  latest.current = close;
  const { ignore, keepFloating } = options;
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") latest.current(); };
    const down = (event: globalThis.MouseEvent) => {
      if (clickedOutside(root.current, event.target, { ignore, keepFloating })) latest.current();
    };
    // A click into an iframe (the app beside the sidebar, the Messages panel) only blurs this
    // window; the iframe is the focused element right after.
    let timer = 0;
    const blur = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const focused = document.activeElement;
        if (focused instanceof HTMLIFrameElement && root.current && !root.current.contains(focused)) latest.current();
      }, 0);
    };
    window.addEventListener("keydown", key);
    document.addEventListener("mousedown", down);
    window.addEventListener("blur", blur);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", key);
      document.removeEventListener("mousedown", down);
      window.removeEventListener("blur", blur);
    };
  }, [open, root, ignore, keepFloating]);
}
