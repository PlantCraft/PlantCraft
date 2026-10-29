/** Tabs under a page heading for pages that belong together (Assets | Asset types). On a narrow
 * screen they scroll sideways: the edge with more tabs past it fades, and the active tab is
 * scrolled into view. */
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

export type PageTab = { to: string; label: string; active: boolean };

/** Which edges of a scrolling row have more past them ("left", "right", both or none). */
export function moreSides(scrollLeft: number, clientWidth: number, scrollWidth: number): { left: boolean; right: boolean } {
  return { left: scrollLeft > 2, right: scrollLeft + clientWidth < scrollWidth - 2 };
}

export function PageTabs({ tabs, href, navigate, label }: { tabs: PageTab[]; href: (to: string) => string; navigate: (to: string) => void; label: string }) {
  const row = useRef<HTMLElement>(null);
  const [more, setMore] = useState({ left: false, right: false });
  const measure = useCallback(() => {
    const el = row.current;
    if (!el) return;
    const next = moreSides(el.scrollLeft, el.clientWidth, el.scrollWidth);
    setMore((current) => (current.left === next.left && current.right === next.right ? current : next));
  }, []);
  const active = tabs.find((tab) => tab.active)?.to;
  useEffect(() => {
    const el = row.current;
    if (!el) return;
    const on = el.querySelector<HTMLElement>(".pcs-active");
    if (on && el.scrollWidth > el.clientWidth) el.scrollLeft = Math.max(0, on.offsetLeft - (el.clientWidth - on.offsetWidth) / 2);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(el);
    return () => observer?.disconnect();
  }, [active, tabs.length, measure]);
  function follow(event: MouseEvent<HTMLAnchorElement>, to: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  }
  const fade = `${more.left ? " pcs-tabs-more-left" : ""}${more.right ? " pcs-tabs-more-right" : ""}`;
  return (
    <nav ref={row} className={`pcs-tabs${fade}`} aria-label={label} onScroll={measure}>
      {tabs.map((tab) => (
        <a key={tab.to} href={href(tab.to)} onClick={(event) => follow(event, tab.to)} className={tab.active ? "pcs-active" : ""} aria-current={tab.active ? "page" : undefined}>{tab.label}</a>
      ))}
    </nav>
  );
}
