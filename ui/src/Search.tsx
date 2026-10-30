/**
 * The suite's search: Ctrl+K (Cmd+K on a Mac), or the search entry at the
 * top of the sidebar, opens one box that finds a point, an asset, a dashboard, a block or a
 * person from any screen of any app. The shell asks every app the person may open, in
 * parallel, and lists the answers by app; an app that does not search (404, an older version,
 * an error) adds nothing, so the box never depends on a given app.
 *
 * An app searches with one read-only endpoint under its prefix (docs/en/search.md):
 *   GET <app>/api/search?q=<text>&limit=<n>
 *   {"format": "plantcraft-search/1", "items": [{"title", "detail", "type", "href"}]}
 * `href` is a path inside the app ("/points/FIC-101.PV"), joined to the app's address here.
 */
import { CornerDownLeft, LoaderCircle, Search as SearchIcon, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { AppMark } from "./Brand.js";
import { appIdFor, appLabel } from "./appMarks.js";
import { t } from "./i18n.js";
import type { SuiteApp } from "./SuiteShell.js";

export const SEARCH_FORMAT = "plantcraft-search/1";
/** Answers per app. */
export const SEARCH_LIMIT = 6;
/** Wait after the last key before asking. */
export const SEARCH_DEBOUNCE_MS = 180;
/** An app that takes longer adds nothing to this search. */
export const SEARCH_TIMEOUT_MS = 4000;

/** One answer as an app gives it. */
export type SearchItem = { title: string; detail?: string | null; type?: string | null; href: string };

/** One answer as the box lists it: with the app it came from and its full address. */
export type SearchHit = SearchItem & { app: string; appName: string; url: string };

export type SearchGroup = { app: string; appName: string; items: SearchHit[] };

function base(app: SuiteApp): string {
  return app.url.endsWith("/") ? app.url : `${app.url}/`;
}

/** The address of an app's answer: its path joined to the app's address (absolute http(s) links are refused). */
export function searchHref(app: SuiteApp, href: string): string | null {
  if (typeof href !== "string" || !href || /[\s\\]/.test(href) || href.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(href)) return null;
  const path = href.startsWith("/") ? href.slice(1) : href;
  if (path.split("/").includes("..")) return null;
  return `${base(app)}${path}`;
}

/** The answers of one app's body, checked: the format, at most `limit` items, text cut to size. */
export function searchItems(app: SuiteApp, body: unknown, limit = SEARCH_LIMIT): SearchHit[] {
  const answer = body as { format?: unknown; items?: unknown } | null;
  if (!answer || answer.format !== SEARCH_FORMAT || !Array.isArray(answer.items)) return [];
  const appName = appLabel(app.id, app.name);
  return answer.items.flatMap((raw): SearchHit[] => {
    const item = raw as Record<string, unknown>;
    const title = typeof item?.title === "string" ? item.title.trim().slice(0, 120) : "";
    const url = typeof item?.href === "string" ? searchHref(app, item.href) : null;
    if (!title || !url) return [];
    const detail = typeof item.detail === "string" ? item.detail.slice(0, 160) : null;
    const type = typeof item.type === "string" ? item.type.slice(0, 40) : null;
    return [{ title, detail, type, href: item.href as string, app: app.id, appName, url }];
  }).slice(0, limit);
}

/** One app's answers to `q`; nothing when it does not search or does not answer in time. */
export async function fetchAppSearch(app: SuiteApp, q: string, options: { fetcher?: typeof fetch; signal?: AbortSignal; limit?: number } = {}): Promise<SearchHit[]> {
  const { fetcher = fetch, signal, limit = SEARCH_LIMIT } = options;
  try {
    const response = await fetcher(`${base(app)}api/search?q=${encodeURIComponent(q)}&limit=${limit}`, { credentials: "same-origin", headers: { Accept: "application/json" }, signal });
    if (!response.ok) return [];
    return searchItems(app, await response.json(), limit);
  } catch {
    return [];
  }
}

/** The answers by app, in the apps' order, apps without answers left out. */
export function groupHits(apps: SuiteApp[], hits: Record<string, SearchHit[]>): SearchGroup[] {
  return apps.flatMap((app) => {
    const items = hits[app.id] ?? [];
    return items.length ? [{ app: app.id, appName: appLabel(app.id, app.name), items }] : [];
  });
}

/** True for Ctrl+K, and Cmd+K on a Mac. */
export function isSearchKey(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">): boolean {
  return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k";
}

/** "Ctrl K", or "⌘ K" on a Mac. */
export function searchShortcut(platform: string = typeof navigator === "undefined" ? "" : navigator.platform): string {
  return /mac|iphone|ipad/i.test(platform) ? "⌘ K" : "Ctrl K";
}

/** Every app's answers to `q`, read as they come; empty `q` asks nobody. */
export function useSuiteSearch(apps: SuiteApp[], q: string, fetcher: typeof fetch = fetch): { groups: SearchGroup[]; busy: boolean } {
  const [hits, setHits] = useState<Record<string, SearchHit[]>>({});
  const [pending, setPending] = useState(0);
  const text = q.trim();
  useEffect(() => {
    setHits({});
    if (text.length < 2 || !apps.length) {
      setPending(0);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    let stop = 0;
    const timer = window.setTimeout(() => {
      let left = apps.length;
      setPending(left);
      stop = window.setTimeout(() => controller.abort(), SEARCH_TIMEOUT_MS);
      for (const app of apps) {
        void fetchAppSearch(app, text, { fetcher, signal: controller.signal }).then((items) => {
          if (cancelled) return;
          left -= 1;
          setHits((current) => ({ ...current, [app.id]: items }));
          setPending(left);
          if (left <= 0) window.clearTimeout(stop);
        });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(stop);
      controller.abort();
    };
  }, [apps, text, fetcher]);
  return { groups: groupHits(apps, hits), busy: pending > 0 };
}

export type SuiteSearchProps = {
  /** The apps to ask (the shell's Apps list). */
  apps: SuiteApp[];
  /** The app drawing the shell: its own answers open inside it. */
  current: string;
  /** Client navigation inside the current app. */
  navigate: (to: string) => void;
  onClose: () => void;
  fetcher?: typeof fetch;
  /** Opens a hit of another app in place (the platform's frame); without it the page is loaded. */
  openUrl?: (url: string) => void;
};

/** The search box: type, move with the arrows, open with Enter, close with Esc. */
export function SuiteSearch({ apps, current, navigate, openUrl, onClose, fetcher }: SuiteSearchProps) {
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const { groups, busy } = useSuiteSearch(apps, q, fetcher);
  const flat = useMemo(() => groups.flatMap((group) => group.items), [groups]);
  useEffect(() => input.current?.focus(), []);
  useEffect(() => setAt(0), [q]);
  const open = useCallback((hit: SearchHit, newTab = false) => {
    onClose();
    if (newTab) {
      window.open(hit.url, "_blank", "noopener");
    } else if (appIdFor(hit.app) === appIdFor(current)) {
      navigate(hit.href.startsWith("/") ? hit.href : `/${hit.href}`);
    } else if (openUrl) {
      openUrl(hit.url);
    } else {
      window.location.assign(hit.url);
    }
  }, [current, navigate, openUrl, onClose]);
  function keys(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (flat.length) setAt((value) => (value + (event.key === "ArrowDown" ? 1 : flat.length - 1)) % flat.length);
    } else if (event.key === "Enter" && flat[at]) {
      event.preventDefault();
      open(flat[at], event.ctrlKey || event.metaKey);
    }
  }
  const text = q.trim();
  let index = -1;
  return (
    <div className="pcs-search-backdrop" onMouseDown={onClose}>
      <div className="pcs-search" role="dialog" aria-modal="true" aria-label={t("Search the suite")} onMouseDown={(event) => event.stopPropagation()} onKeyDown={keys}>
        <label className="pcs-search-field">
          <SearchIcon size={18} aria-hidden="true" />
          <input ref={input} value={q} onChange={(event) => setQ(event.target.value)} placeholder={t("Search signals, assets, dashboards, blocks, people…")} aria-label={t("Search the suite")} role="combobox" aria-expanded={flat.length > 0} aria-controls="pcs-search-list" aria-activedescendant={flat[at] ? `pcs-hit-${at}` : undefined} autoComplete="off" spellCheck={false} />
          {busy && <LoaderCircle size={16} className="pcs-spin" aria-label={t("Searching")} />}
          <button type="button" className="pcs-search-close" onClick={onClose} aria-label={t("Close")}><X size={16} /></button>
        </label>
        <div className="pcs-search-list" id="pcs-search-list" role="listbox" aria-label={t("Results")}>
          {groups.map((group) => (
            <section key={group.app} className="pcs-search-group" aria-label={group.appName}>
              <h3>{appIdFor(group.app) && <AppMark app={appIdFor(group.app) ?? "processcraft"} size={16} />}{group.appName}</h3>
              {group.items.map((hit) => {
                index += 1;
                const mine = index;
                return (
                  <a key={`${hit.app}:${hit.url}`} id={`pcs-hit-${mine}`} href={hit.url} role="option" aria-selected={mine === at} className={`pcs-hit${mine === at ? " pcs-hit-on" : ""}`}
                    onMouseEnter={() => setAt(mine)}
                    onClick={(event) => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); open(hit); }}>
                    <span className="pcs-hit-text"><strong>{hit.title}</strong>{hit.detail && <small>{hit.detail}</small>}</span>
                    {hit.type && <span className="pcs-hit-type">{hit.type}</span>}
                    {mine === at && <CornerDownLeft size={14} className="pcs-hit-enter" aria-hidden="true" />}
                  </a>
                );
              })}
            </section>
          ))}
          {text.length < 2 && <p className="pcs-search-hint">{t("Type at least two letters. Every app of the suite is searched.")}</p>}
          {text.length >= 2 && !busy && !flat.length && <p className="pcs-search-hint">{t("Nothing found for “{text}”.", { text })}</p>}
        </div>
        <footer className="pcs-search-keys"><span><kbd>↑</kbd><kbd>↓</kbd> {t("move")}</span><span><kbd>Enter</kbd> {t("open")}</span><span><kbd>Esc</kbd> {t("close")}</span></footer>
      </div>
    </div>
  );
}

/** Ctrl+K (Cmd+K) anywhere opens the search; the same keys close it. */
export function useSearchKey(setOpen: (update: (open: boolean) => boolean) => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const press = (event: KeyboardEvent) => {
      if (!isSearchKey(event)) return;
      event.preventDefault();
      setOpen((open) => !open);
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [setOpen, enabled]);
}

/** The search entry at the top of the sidebar. */
export function SearchButton({ onOpen, collapsed }: { onOpen: () => void; collapsed: boolean }) {
  const keys = searchShortcut();
  const label = t("Search");
  return (
    <button type="button" className="pcs-search-button" onClick={onOpen} aria-label={t("Search the suite ({keys})", { keys })} title={collapsed ? t("Search the suite ({keys})", { keys }) : undefined} aria-keyshortcuts="Control+K Meta+K">
      <SearchIcon size={16} aria-hidden="true" />
      <span>{label}</span>
      <kbd>{keys}</kbd>
    </button>
  );
}
