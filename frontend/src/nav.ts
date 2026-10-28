import { isEmbedded } from "@plantcraft/ui";

/** Inside the Messages panel of another screen (`?embed=1`, MessagesDrawer.tsx): only Messages is drawn
 * here; anything else opens in the whole window. */
export const EMBEDDED = isEmbedded();

export function isMessagesPath(to: string): boolean {
  return /^\/messages(\/|\?|#|$)/.test(to);
}

/** Leave the panel: open ``to`` in the window around it. */
export function openOutside(to: string) {
  (window.top ?? window).location.assign(to);
}

/** Client-side navigation: push the URL and let the shell re-render the route. */
export function navigate(to: string) {
  if (EMBEDDED && !isMessagesPath(to)) { openOutside(to); return; }
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  if (!to.includes("#")) window.scrollTo(0, 0);
}
