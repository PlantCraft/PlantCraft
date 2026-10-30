/**
 * An app's Overview: the first page of every app of the suite, built the same way as
 * PlantCraft's (docs/widgets.md). The heading (the app's name above "Overview", one line on
 * what the app does, its main actions), the app's notices, then a board of widgets each person
 * arranges, saved per person and per app in PlantCraft (`/api/home/layout?page=<app>`).
 *
 * The catalog is the widgets the app publishes (`<app>/api/widgets`, the same ones PlantCraft's
 * Overview offers, so a widget is written once) plus the page's own, drawn by the app (`render`).
 * Without PlantCraft (an app's own tests) the layout is not kept and the default is drawn.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { t } from "./i18n.js";
import type { SuiteApp } from "./SuiteShell.js";
import { fetchAppWidgets, WidgetBoard, type BoardItem, type WidgetDef } from "./Widgets.js";

const PAGE = /^[a-z0-9][a-z0-9-]{0,40}$/;

function layoutUrl(page?: string): string {
  return page ? `/api/home/layout?page=${encodeURIComponent(page)}` : "/api/home/layout";
}

/** A saved board: placements on the grid, or (saved before the grid) widget ids in order. */
export type SavedLayout = Array<BoardItem | string>;

/**
 * A person's board for one Overview: `undefined` while it is read, `null` until they arrange
 * their own. `page` is the app's id (PlantCraft's own Overview passes none; Desk's is "desk").
 */
export function useOverviewLayout(page?: string, fetcher: typeof fetch = fetch): [SavedLayout | null | undefined, (layout: BoardItem[] | null) => void] {
  const [layout, setLayout] = useState<SavedLayout | null | undefined>(undefined);
  useEffect(() => {
    if (page !== undefined && !PAGE.test(page)) { setLayout(null); return; }
    let live = true;
    fetcher(layoutUrl(page), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { widgets?: unknown } | null) => {
        if (!live) return;
        const widgets = body?.widgets;
        setLayout(Array.isArray(widgets) ? widgets.filter((item): item is BoardItem | string => typeof item === "string" || (typeof item === "object" && item !== null)) : null);
      })
      .catch(() => { if (live) setLayout(null); });
    return () => { live = false; };
  }, [page, fetcher]);
  const save = useCallback((next: BoardItem[] | null) => {
    setLayout(next);
    const init: RequestInit = next === null
      ? { method: "DELETE", credentials: "same-origin" }
      : { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ widgets: next }) };
    fetcher(layoutUrl(page), init).catch(() => undefined);
  }, [page, fetcher]);
  return [layout, save];
}

export type AppOverviewProps = {
  /** The app's id in the suite (`linkcraft`): its layout's key and its widgets' prefix. */
  app: string;
  /** The app's name (`Link`), for its widgets. */
  name: string;
  /** Where the app is served (`/link/`): its published widgets are read from `<url>api/widgets`. */
  url: string;
  /** No longer drawn: the page's top is its title and buttons only. */
  intro?: string;
  /** The app's main actions, at the right of the heading. */
  actions?: ReactNode;
  /** Notices between the heading and the widgets (a stopped collector, a message after an action). */
  children?: ReactNode;
  /** The page's own widgets, drawn by the app; `id` without the app's prefix. */
  widgets?: Array<Omit<WidgetDef, "app">>;
  /** A new person's board: placements (`BoardItem`, to set each card's place and size) or ids in
   * order (placed at their sizes). Default: every widget, the page's own first. */
  defaultLayout?: SavedLayout;
};

/** The page's own widgets first, then the published ones, each id once. On the app's own page a
 * published title loses the "<name>: " it carries on PlantCraft's Overview. */
export function overviewCatalog(app: string, own: Array<Omit<WidgetDef, "app">>, published: WidgetDef[], name = ""): WidgetDef[] {
  const mine = own.map((item) => ({ ...item, app, id: item.id.includes(":") ? item.id : `${app}:${item.id}` }));
  const ids = new Set(mine.map((item) => item.id));
  const prefix = name ? `${name}: ` : "";
  const plain = (title: string) => {
    if (!prefix || !title.startsWith(prefix)) return title;
    const rest = title.slice(prefix.length);
    return rest.charAt(0).toUpperCase() + rest.slice(1);
  };
  return [...mine, ...published.filter((item) => !ids.has(item.id)).map((item) => ({ ...item, title: plain(item.title) }))];
}

export function AppOverview({ app, name, url, actions, children, widgets = [], defaultLayout }: AppOverviewProps) {
  const [published, setPublished] = useState<WidgetDef[] | null>(null);
  const [layout, saveLayout] = useOverviewLayout(app);
  useEffect(() => {
    let live = true;
    fetchAppWidgets({ id: app, name, url }).then((items) => { if (live) setPublished(items); });
    return () => { live = false; };
  }, [app, name, url]);
  const catalog = overviewCatalog(app, widgets, published ?? [], name);
  const shown = layout ?? defaultLayout ?? catalog.map((item) => item.id);
  return <>
    <div className="page-heading pc-overview-heading">
      <div><h1>{t("Overview")}</h1></div>
      {actions && <div className="heading-actions">{actions}</div>}
    </div>
    {children}
    <WidgetBoard catalog={catalog} layout={shown} onLayout={saveLayout} onReset={layout ? () => saveLayout(null) : undefined}
      loading={published === null || layout === undefined} apps={[{ id: app, name, url }]} marks={false} />
  </>;
}

export type { SuiteApp };
