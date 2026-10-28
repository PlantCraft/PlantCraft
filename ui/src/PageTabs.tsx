/** Tabs under a page heading for pages that belong together (Assets | Asset types). */
import type { MouseEvent } from "react";

export type PageTab = { to: string; label: string; active: boolean };

export function PageTabs({ tabs, href, navigate, label }: { tabs: PageTab[]; href: (to: string) => string; navigate: (to: string) => void; label: string }) {
  function follow(event: MouseEvent<HTMLAnchorElement>, to: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  }
  return (
    <nav className="pcs-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <a key={tab.to} href={href(tab.to)} onClick={(event) => follow(event, tab.to)} className={tab.active ? "pcs-active" : ""} aria-current={tab.active ? "page" : undefined}>{tab.label}</a>
      ))}
    </nav>
  );
}
