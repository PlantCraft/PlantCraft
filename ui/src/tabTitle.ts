/**
 * The browser tab: one title format and one icon for every app of the suite, set by the shell.
 *
 * The title reads page first, then app, then the brand: "FIC-1003 · Link · PlantCraft". A tab
 * cuts the end of a long title, so what tells two tabs apart (the page) goes first and the brand,
 * the same on every tab, goes last; the platform's home is just "PlantCraft". The page is the
 * first `<h1>` of the page (what the person reads as its title), or the active sidebar entry while
 * the page has none. A page can name its tab itself with `data-tab-title` on that `<h1>`.
 *
 * The icon is always the platform's mark, whatever app the tab shows.
 */
import { useEffect } from "react";
import { BRAND_NAME, appDisplayName, markSvg, type AnyAppId } from "./appMarks.js";

export const TAB_SEPARATOR = " · ";
/** Longest page part of a tab title; the rest is cut with an ellipsis. */
export const TAB_PAGE_MAX = 60;

/** "Page · App · PlantCraft"; the app or the page drops out when it says nothing new. Unread
 * messages lead it as "(3) ", so a person working in another tab sees them arrive. */
export function tabTitle(app: AnyAppId, page?: string | null, unread = 0, name?: string | null): string {
  const appName = app === "processcraft" ? null : appDisplayName(app, name);
  let pagePart = (page ?? "").replace(/\s+/g, " ").trim();
  if (pagePart === appName || pagePart === BRAND_NAME) pagePart = "";
  if (pagePart.length > TAB_PAGE_MAX) pagePart = `${pagePart.slice(0, TAB_PAGE_MAX - 1).trimEnd()}…`;
  const count = unread > 0 ? `(${unread > 99 ? "99+" : Math.floor(unread)}) ` : "";
  return count + [pagePart, appName, BRAND_NAME].filter(Boolean).join(TAB_SEPARATOR);
}

/** The words of a heading as a person reads them: its text pieces with a space between parts,
 * leaving out what is hidden from readers (icons) and status pills. */
export function headingText(heading: Element): string {
  const explicit = heading.getAttribute("data-tab-title");
  if (explicit !== null) return explicit;
  const parts: string[] = [];
  const walk = (node: Node) => {
    if (node.nodeType === 3) { parts.push(node.textContent ?? ""); return; }
    if (node.nodeType !== 1) return;
    const element = node as Element;
    if (element.getAttribute("aria-hidden") === "true" || element.classList.contains("pill") || element.tagName.toLowerCase() === "svg") return;
    element.childNodes.forEach(walk);
    parts.push(" ");
  };
  heading.childNodes.forEach(walk);
  return parts.join("").replace(/\s+/g, " ").trim();
}

/** The favicon of every tab: the platform's mark. */
export const BRAND_FAVICON = `data:image/svg+xml,${encodeURIComponent(markSvg("processcraft"))}`;

function setFavicon() {
  const links = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]'));
  if (links.length === 0) {
    const link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
    links.push(link);
  }
  for (const link of links) {
    if (link.href === BRAND_FAVICON) continue;
    link.type = "image/svg+xml";
    link.href = BRAND_FAVICON;
  }
}

/**
 * Keeps the tab's title and icon in step with the page: on every route change and whenever the
 * page's heading appears or changes (a detail page fills its title after it loads).
 * `content` is the element the pages render into; `fallback` the active sidebar entry's label.
 */
export function useTabTitle(app: AnyAppId, path: string, fallback: string | null, content: () => Element | null, unread = 0, name?: string) {
  useEffect(() => {
    setFavicon();
    const root = content();
    const home = path === "/" || path === "";
    const update = () => {
      const heading = root?.querySelector("h1");
      const page = home ? null : (heading ? headingText(heading) : "") || fallback;
      const title = tabTitle(app, page, unread, name);
      if (document.title !== title) document.title = title;
    };
    update();
    if (!root || typeof MutationObserver === "undefined") return;
    let pending = 0;
    const observer = new MutationObserver(() => {
      if (pending) return;
      pending = window.setTimeout(() => { pending = 0; update(); }, 50);
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    return () => { observer.disconnect(); if (pending) window.clearTimeout(pending); };
  }, [app, path, fallback, content, unread, name]);
}
