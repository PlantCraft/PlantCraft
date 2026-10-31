/**
 * Overview widgets. A page of widgets the person arranges on the suite's grid (Grid.tsx, the one
 * View's dashboards use): add one from the catalog (a window with the apps at the left and their
 * widgets, previewed, at the right), drag it by its title to move it, pick one of its sizes in its
 * settings, remove it; the page saves the board (PlantCraft keeps it per person). The catalog has the
 * page's own widgets (drawn by the page) and the widgets each installed app publishes, so the
 * Overview never depends on a given app: an app that is not installed adds nothing.
 *
 * Sizes are fixed: each widget declares one to three sizes on the 12-column
 * grid, 1 to 3 rows high (a count fits 3 x 1, a list needs two rows), and draws what fits each one.
 * The widget gallery (`WidgetGallery`, Desk's /widgets) draws every widget at every size; its
 * browser test fails when one spills out of its card.
 *
 * An app publishes widgets with two read-only endpoints under its prefix (docs/widgets.md):
 *   GET <app>/api/widgets        {"version": 1, "widgets": [{"id", "title", "description", "size", "sizes", "default"}]}
 *   GET <app>/api/widgets/<id>   {"kind": "number", "value", "unit", "label", "state", "href"}
 *                                {"kind": "list", "items": [{"label", "detail", "value", "state", "href"}], "href", "empty"}
 */
import { Check, ChevronDown, GripVertical, LoaderCircle, Plus, RotateCcw, Settings2, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { AppMark } from "./Brand.js";
import { appIdFor, appLabel } from "./appMarks.js";
import { bottom, CardGrid, fitCell, freePlace, GRID_COLUMNS, GRID_GAP, GRID_ROW, packCells, readingOrder, type GridCell } from "./Grid.js";
import { t } from "./i18n.js";
import type { SuiteApp } from "./SuiteShell.js";
import { WidgetBody, type WidgetData } from "./WidgetKinds.js";
import { tipProps } from "./WidgetTip.js";

export type { WidgetData, WidgetFact, WidgetItem, WidgetPart } from "./WidgetKinds.js";

export const WIDGETS_VERSION = 1;
export const WIDGET_POLL_MS = 60_000;

export type WidgetSize = "s" | "m" | "l";

/** A widget's own settings, kept with its place on the board (a calendar's range, a list's filter). */
export type WidgetConfig = Record<string, unknown>;

/** What a widget draws with: its settings, its size on the grid (columns, rows), how many list
 * rows fit in it, and (on a board) a way to keep new settings (a quick note's text). */
export type WidgetContext = { config: WidgetConfig; w: number; h: number; rows: number; editing: boolean; setConfig?: (config: WidgetConfig) => void };

/** One size a widget may take: columns of 12 and rows (1 to 3). */
export type WidgetSizeChoice = { w: number; h: number };

/** One widget placed on a board: `i` is the placement (a widget may be placed more than once
 * when it is `multiple`), `widget` the catalog id; x, y, w, h in grid units (Grid.tsx). */
export type BoardItem = GridCell & { widget: string; title?: string; config?: WidgetConfig };

export type WidgetDef = {
  /** Unique in the catalog: "<app>:<widget>" for an app's, a plain id for the page's own. */
  id: string;
  app: string;
  title: string;
  description?: string;
  size: WidgetSize;
  /** The page's own widget draws itself, with its settings and size. */
  render?: (context: WidgetContext) => ReactNode;
  /** Its fields in the widget's settings (below the title and size); without it only those two. */
  settings?: (props: { config: WidgetConfig; onChange: (config: WidgetConfig) => void }) => ReactNode;
  /** A new placement's settings. */
  defaultConfig?: WidgetConfig;
  /** The sizes it may take, smallest first (at most three: small, medium, large); default from
   * `size` (STANDARD_SIZES). */
  sizes?: WidgetSizeChoice[];
  /** A new placement's size, one of `sizes`; default the standard one of `size`. */
  w?: number;
  h?: number;
  /** May be placed more than once (two lists with other filters). */
  multiple?: boolean;
  /** An app's widget reads its data here. */
  dataUrl?: string;
  /** An app's widget about one thing the person picks (a schedule, a point): what it is called
   * ("Schedule"); the choices are read at `<dataUrl>/options` and the data at `<dataUrl>?item=`. */
  pick?: string;
  /** On a new person's Overview until they arrange their own. */
  byDefault?: boolean;
};

const SIZES: WidgetSize[] = ["s", "m", "l"];
export const BOARD_MAX = 40;
/** The tallest a widget is, in rows. */
export const WIDGET_MAX_H = 3;
export const WIDGET_MAX_SIZES = 3;

/** The sizes of a widget that declares only `size`: a count (s) is a tile or a small card, a
 * list (m) half a row or a third, a wide one (l) half or the whole width. */
export const STANDARD_SIZES: Record<WidgetSize, WidgetSizeChoice[]> = {
  s: [{ w: 3, h: 1 }, { w: 3, h: 2 }],
  m: [{ w: 4, h: 2 }, { w: 6, h: 3 }],
  l: [{ w: 6, h: 3 }, { w: 12, h: 3 }],
};
const STANDARD_DEFAULT: Record<WidgetSize, WidgetSizeChoice> = { s: { w: 3, h: 2 }, m: { w: 6, h: 3 }, l: { w: 12, h: 3 } };
const SIZE_NAMES = ["Small", "Medium", "Large"];

/** A card's height in pixels, `h` rows high. */
export function cardPixels(h: number): number {
  return h * GRID_ROW + (h - 1) * GRID_GAP;
}

/** The height in pixels a widget draws in, in a card `h` rows high (the card less its padding
 * and its title). */
export function bodyPixels(h: number): number {
  return h <= 1 ? cardPixels(1) - 42 : cardPixels(h) - 66;
}

/** How many list rows fit in a card `h` rows high (a row is a name and a line below it, with
 * "See all" under them). A one-row card holds a number, not a list. */
export function listRows(h: number): number {
  if (h <= 1) return 1;
  return Math.max(1, Math.floor((bodyPixels(h) - 26) / 44));
}

function validSize(raw: unknown): WidgetSizeChoice | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { w, h } = raw as Record<string, unknown>;
  if (!Number.isInteger(w) || !Number.isInteger(h)) return null;
  if ((w as number) < 1 || (w as number) > GRID_COLUMNS || (h as number) < 1 || (h as number) > WIDGET_MAX_H) return null;
  return { w: w as number, h: h as number };
}

/** The sizes a widget may take, smallest first, each once. */
export function sizesOf(def: Pick<WidgetDef, "size" | "sizes">): WidgetSizeChoice[] {
  const declared = (def.sizes ?? []).map(validSize).filter((item): item is WidgetSizeChoice => item !== null);
  const list = declared.length ? declared : STANDARD_SIZES[def.size] ?? STANDARD_SIZES.m;
  const seen = new Set<string>();
  return list.filter((item) => { const key = `${item.w}x${item.h}`; if (seen.has(key)) return false; seen.add(key); return true; })
    .sort((a, b) => a.w * a.h - b.w * b.h || a.h - b.h).slice(0, WIDGET_MAX_SIZES);
}

/** "Small", "Medium", "Large" (a widget with one size has only "Medium"). */
export function sizeName(index: number, count: number): string {
  if (count === 1) return t("Medium");
  if (count === 2) return t(index === 0 ? "Small" : "Large");
  return t(SIZE_NAMES[index] ?? "Large");
}

/** The allowed size closest to `w` x `h` (a board saved before sizes were fixed). */
export function nearestSize(def: Pick<WidgetDef, "size" | "sizes">, w: number, h: number): WidgetSizeChoice {
  const sizes = sizesOf(def);
  return sizes.reduce((best, item) => (Math.abs(item.w - w) + 3 * Math.abs(item.h - h) < Math.abs(best.w - w) + 3 * Math.abs(best.h - h) ? item : best), sizes[0]);
}

function appUrl(app: SuiteApp): string {
  return app.url.endsWith("/") ? app.url : `${app.url}/`;
}

/** An app's published widgets as catalog entries; an app without them (404, an error, another version) adds none. */
export async function fetchAppWidgets(app: SuiteApp, fetcher: typeof fetch = fetch): Promise<WidgetDef[]> {
  try {
    const response = await fetcher(`${appUrl(app)}api/widgets`, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) return [];
    const body = (await response.json()) as { version?: number; widgets?: unknown };
    if (body?.version !== WIDGETS_VERSION || !Array.isArray(body.widgets)) return [];
    return body.widgets.flatMap((raw): WidgetDef[] => {
      const item = raw as Record<string, unknown>;
      const id = typeof item.id === "string" && /^[a-z0-9][a-z0-9-]{0,40}$/.test(item.id) ? item.id : null;
      const title = typeof item.title === "string" ? item.title.slice(0, 80) : null;
      if (!id || !title) return [];
      const size = SIZES.includes(item.size as WidgetSize) ? (item.size as WidgetSize) : "m";
      const description = typeof item.description === "string" ? item.description.slice(0, 200) : undefined;
      const sizes = Array.isArray(item.sizes) ? item.sizes.slice(0, WIDGET_MAX_SIZES).map(validSize).filter((entry): entry is WidgetSizeChoice => entry !== null) : [];
      const pick = typeof item.pick === "string" && item.pick.trim() ? item.pick.slice(0, 40) : undefined;
      const dataUrl = `${appUrl(app)}api/widgets/${id}`;
      return [{
        id: `${app.id}:${id}`, app: app.id, title, description, size, ...(sizes.length ? { sizes } : {}), dataUrl, byDefault: item.default === true,
        ...(item.multiple === true || pick ? { multiple: true } : {}),
        ...(pick ? { pick, settings: ({ config, onChange }) => <PickField url={`${dataUrl}/options`} label={pick} config={config} onChange={onChange} /> } : {}),
      }];
    });
  } catch {
    return [];
  }
}

/** Every installed app's widgets, in the apps' order. */
export async function fetchSuiteWidgets(apps: SuiteApp[], fetcher: typeof fetch = fetch): Promise<WidgetDef[]> {
  const lists = await Promise.all(apps.filter((app) => appIdFor(app.id) !== "processcraft").map((app) => fetchAppWidgets(app, fetcher)));
  return lists.flat();
}

/** A new person's Overview: the catalog's widgets marked default, in its order. */
export function defaultLayout(catalog: WidgetDef[]): string[] {
  return catalog.filter((item) => item.byDefault).map((item) => item.id);
}

/** The layout as drawn: ids still in the catalog, each once. */
export function placedWidgets(layout: string[], catalog: WidgetDef[]): WidgetDef[] {
  const byId = new Map(catalog.map((item) => [item.id, item]));
  const seen = new Set<string>();
  return layout.flatMap((id) => {
    const item = byId.get(id);
    if (!item || seen.has(id)) return [];
    seen.add(id);
    return [item];
  });
}

/** `id` moved one place up (-1) or down (+1). */
export function moveWidget(layout: string[], id: string, step: -1 | 1): string[] {
  const at = layout.indexOf(id);
  const to = at + step;
  if (at < 0 || to < 0 || to >= layout.length) return layout;
  const next = [...layout];
  [next[at], next[to]] = [next[to], next[at]];
  return next;
}

/** A new placement's size in grid units: one of its sizes. */
export function widgetSize(item: WidgetDef): WidgetSizeChoice {
  const wanted = item.w !== undefined && item.h !== undefined ? { w: item.w, h: item.h } : STANDARD_DEFAULT[item.size] ?? STANDARD_DEFAULT.m;
  return nearestSize(item, wanted.w, wanted.h);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A saved board as drawn: an older saved order of ids (before the grid, 2026-10-23) is placed
 * row by row at each widget's size; placements keep their place, size, title and settings, a
 * size no longer allowed (a board saved before sizes were fixed) becoming the closest allowed.
 * Placements of widgets no longer in the catalog stay in the board (an app may be down for a
 * moment) and are left out by `placedItems`.
 */
export function boardOf(raw: unknown, catalog: WidgetDef[]): BoardItem[] {
  if (!Array.isArray(raw)) return [];
  const byId = new Map(catalog.map((item) => [item.id, item]));
  const placed: BoardItem[] = [];
  const seen = new Set<string>();
  const loose: Array<{ i: string; widget: string; w: number; h: number }> = [];
  for (const entry of raw.slice(0, BOARD_MAX)) {
    if (typeof entry === "string") {
      if (seen.has(entry)) continue;
      seen.add(entry);
      const def = byId.get(entry);
      loose.push({ i: entry, widget: entry, ...(def ? widgetSize(def) : { w: 6, h: 3 }) });
      continue;
    }
    if (!isObject(entry) || typeof entry.widget !== "string") continue;
    const i = typeof entry.i === "string" && entry.i ? entry.i : entry.widget;
    if (seen.has(i)) continue;
    seen.add(i);
    const numbers = ["x", "y", "w", "h"].every((key) => typeof entry[key] === "number");
    if (!numbers) {
      const def = byId.get(entry.widget);
      loose.push({ i, widget: entry.widget, ...(def ? widgetSize(def) : { w: 6, h: 3 }) });
      continue;
    }
    const def = byId.get(entry.widget);
    const size = def ? nearestSize(def, entry.w as number, entry.h as number) : { w: entry.w as number, h: entry.h as number };
    placed.push(fitCell({
      i, widget: entry.widget, x: entry.x as number, y: entry.y as number, w: size.w, h: size.h,
      ...(typeof entry.title === "string" && entry.title.trim() ? { title: entry.title.slice(0, 80) } : {}),
      ...(isObject(entry.config) ? { config: entry.config } : {}),
    }));
  }
  const cells = packCells(loose, placed);
  return [...placed, ...loose.map((item, index) => ({ ...cells[index], widget: item.widget }))];
}

/** The placements drawn: those whose widget is in the catalog, in reading order. */
export function placedItems(board: BoardItem[], catalog: WidgetDef[]): Array<{ item: BoardItem; def: WidgetDef }> {
  const byId = new Map(catalog.map((def) => [def.id, def]));
  return readingOrder(board).flatMap((item) => {
    const def = byId.get(item.widget);
    return def ? [{ item, def }] : [];
  });
}

/** A new placement of `def` (at `size`, one of its sizes) at the first free place (under the
 * others when the rows are full). */
export function addToBoard(board: BoardItem[], def: WidgetDef, size?: WidgetSizeChoice): BoardItem[] {
  if (board.length >= BOARD_MAX) return board;
  const { w, h } = size ? nearestSize(def, size.w, size.h) : widgetSize(def);
  const used = new Set(board.map((item) => item.i));
  let i = def.id;
  for (let n = 2; used.has(i); n += 1) i = `${def.id}~${n}`;
  const place = freePlace(board, w, h);
  return [...board, { i, widget: def.id, x: place.x, y: Math.min(place.y, bottom(board)), w, h, ...(def.defaultConfig ? { config: { ...def.defaultConfig } } : {}) }];
}

/** The address of a published widget's data: with the thing picked in its settings, if any. */
export function widgetDataUrl(item: Pick<WidgetDef, "dataUrl" | "pick">, config: WidgetConfig = {}): string | undefined {
  if (!item.dataUrl) return undefined;
  const picked = item.pick && typeof config.item === "string" && config.item ? config.item : "";
  return picked ? `${item.dataUrl}?item=${encodeURIComponent(picked)}` : item.dataUrl;
}

type PickOption = { value: string; label: string; detail?: string | null };

/** The choice of a widget about one thing (`pick`): the app's options, read once. Kept as
 * `{item, label}`: without one the app shows the first (or most relevant) of them. */
function PickField({ url, label, config, onChange }: { url: string; label: string; config: WidgetConfig; onChange: (config: WidgetConfig) => void }) {
  const [options, setOptions] = useState<PickOption[] | null>(null);
  useEffect(() => {
    let live = true;
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : { options: [] }))
      .then((body: { options?: unknown }) => {
        if (!live) return;
        const list = Array.isArray(body?.options) ? body.options : [];
        setOptions(list.flatMap((raw): PickOption[] => {
          const entry = raw as Record<string, unknown>;
          return typeof entry?.value === "string" && typeof entry.label === "string"
            ? [{ value: entry.value, label: entry.label.slice(0, 120), detail: typeof entry.detail === "string" ? entry.detail.slice(0, 120) : null }] : [];
        }).slice(0, 500));
      })
      .catch(() => { if (live) setOptions([]); });
    return () => { live = false; };
  }, [url]);
  const value = typeof config.item === "string" ? config.item : "";
  return <label>{t(label)}
    <select value={value} disabled={options === null} onChange={(event) => {
      const picked = options?.find((option) => option.value === event.target.value);
      onChange(picked ? { ...config, item: picked.value, label: picked.label } : { ...config, item: undefined, label: undefined });
    }}>
      <option value="">{options === null ? t("Loading") : t("The first one")}</option>
      {(options ?? []).map((option) => <option key={option.value} value={option.value}>{option.detail ? `${option.label} · ${option.detail}` : option.label}</option>)}
    </select>
  </label>;
}

function RemoteWidget({ item, w, h, config }: { item: WidgetDef; w: number; h: number; config?: WidgetConfig }) {
  const [data, setData] = useState<WidgetData | null>(null);
  const [failed, setFailed] = useState(false);
  const url = widgetDataUrl(item, config);
  useEffect(() => {
    if (!url) return;
    let live = true;
    const load = () => fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((body: WidgetData) => { if (live) { setData(body); setFailed(false); } })
      .catch(() => { if (live) setFailed(true); });
    void load();
    const timer = window.setInterval(load, WIDGET_POLL_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [url]);
  if (failed && !data) return <p className="muted small">{t("Could not read this widget.")}</p>;
  if (!data) return <LoaderCircle size={16} className="spin" aria-label={t("Loading")} />;
  return <WidgetBody data={data} w={w} h={h} rows={listRows(h)} />;
}


export type WidgetBoardProps = {
  catalog: WidgetDef[];
  /** The saved board (`BoardItem[]`), or an older ordered list of widget ids. */
  layout: Array<BoardItem | string>;
  onLayout: (layout: BoardItem[]) => void;
  /** Shown while the catalog is still being read from the apps. */
  loading?: boolean;
  /** The app names in the "Add a widget" window. */
  apps?: SuiteApp[];
  /** Back to the default widgets (shown while customizing, when the person has their own). */
  onReset?: () => void;
  /** Draw each app's mark before its widgets' titles (off on an app's own Overview). */
  marks?: boolean;
  /** Text of the empty board. */
  empty?: string;
};

/** A column's width in pixels on a board `width` wide (the 12 columns and their gaps). */
export function columnPixels(width: number): number {
  return Math.max(40, (width - (GRID_COLUMNS - 1) * GRID_GAP) / GRID_COLUMNS);
}

/** A card's width in pixels, `w` columns wide, on a board whose columns are `column` wide. */
export function cardWidth(w: number, column: number): number {
  return w * column + (w - 1) * GRID_GAP;
}

/** A board's width the previews assume (a laptop's page beside the menu). */
const PREVIEW_BOARD = 1040;

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const read = () => setWidth(node.getBoundingClientRect().width);
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** One widget in its card: the same frame on a board, in its settings, in the catalog and in the gallery. */
export function WidgetCard({ def, title, config, w, h, editing = false, setConfig, head, tools, mark, fold }: {
  def: WidgetDef; title?: string; config?: WidgetConfig; w: number; h: number; editing?: boolean; setConfig?: (config: WidgetConfig) => void;
  /** The title's own element (a board's drag handle). */
  head?: (title: ReactNode) => ReactNode; tools?: ReactNode; mark?: ReactNode; fold?: { folded: boolean; toggle: () => void };
}) {
  const settings = config ?? def.defaultConfig ?? {};
  // A widget about one picked thing is titled by it, unless the person named the card.
  const name = title || (def.pick && typeof settings.label === "string" && settings.label ? settings.label : def.title);
  // The title says on hover what the widget shows ("what is each thing here").
  const label = <>{mark}<span {...(def.description ? tipProps({ title: name, rows: [["", def.description]] }) : {})}>{name}</span></>;
  return <article className={`panel pc-wg-card pc-wg-h${h}${fold?.folded ? " pc-wg-folded" : ""}`} aria-label={name} data-widget={def.id}>
    <header className="pc-wg-card-head">
      {fold
        ? <h2><button type="button" className="pc-wg-fold" aria-expanded={!fold.folded} onClick={fold.toggle}>{label}<ChevronDown size={15} aria-hidden="true" /></button></h2>
        : head ? head(label) : <h2>{label}</h2>}
      {tools}
    </header>
    {!fold?.folded && <div className="pc-wg-body">{def.render ? def.render({ config: settings, w, h, rows: listRows(h), editing, setConfig }) : <RemoteWidget item={def} w={w} h={h} config={settings} />}</div>}
  </article>;
}

/** A card drawn at its real size on a board `board` pixels wide, scaled down to fit its box. */
function ScaledCard({ def, size, title, config, board = PREVIEW_BOARD }: { def: WidgetDef; size: WidgetSizeChoice; title?: string; config?: WidgetConfig; board?: number }) {
  const [ref, box] = useWidth<HTMLDivElement>();
  const width = cardWidth(size.w, columnPixels(board));
  const height = cardPixels(size.h);
  const scale = box ? Math.min(1, box / width) : 1;
  return <div ref={ref} className="pc-wg-scaled" style={{ height: height * scale }} aria-hidden="true" inert>
    <div style={{ width, height, transform: `scale(${scale})`, transformOrigin: "top left" }}>
      <WidgetCard def={def} title={title} config={config} w={size.w} h={size.h} />
    </div>
  </div>;
}

/** The size buttons: small, medium, large, each with its columns and rows. */
function SizePicker({ def, value, onChange, id }: { def: WidgetDef; value: WidgetSizeChoice; onChange: (size: WidgetSizeChoice) => void; id: string }) {
  const sizes = sizesOf(def);
  return <div className="pc-wg-sizes" role="radiogroup" aria-label={t("Size")} id={id}>
    {sizes.map((size, index) => {
      const on = size.w === value.w && size.h === value.h;
      return <button key={`${size.w}x${size.h}`} type="button" role="radio" aria-checked={on} className={`pc-wg-size${on ? " on" : ""}`} onClick={() => onChange(size)}
        title={t("{columns} of 12 columns, {rows} rows high", { columns: size.w, rows: size.h })}>
        <b>{sizeName(index, sizes.length)}</b><small>{size.w} × {size.h}</small>
      </button>;
    })}
  </div>;
}

/** A widget's settings: its title, its size (one of those it allows) and the widget's own fields,
 * with a preview at that size. The same form for every widget of every Overview. */
export function WidgetSettings({ item, def, onSave, onClose }: { item: BoardItem; def: WidgetDef; onSave: (item: BoardItem) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<BoardItem>(() => ({ ...item, ...nearestSize(def, item.w, item.h) }));
  const config = draft.config ?? def.defaultConfig ?? {};
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="dialog pc-wg-settings" role="dialog" aria-label={t("Widget settings")} onSubmit={(event) => { event.preventDefault(); onSave(fitCell(draft)); }}>
      <header><h2>{t("Widget settings")}</h2><button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="pc-wg-settings-body">
        <div className="pc-wg-settings-fields">
          <label>{t("Title")}<input id={`pc-wg-title-${item.i}`} value={draft.title ?? ""} maxLength={80} placeholder={def.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value || undefined })} /></label>
          <div className="pc-wg-settings-size"><span>{t("Size")}</span>
            <SizePicker id={`pc-wg-size-${item.i}`} def={def} value={draft} onChange={(size) => setDraft({ ...draft, ...size })} /></div>
          {def.settings?.({ config, onChange: (next) => setDraft({ ...draft, config: next }) })}
          {def.description && <p className="muted small">{def.description}</p>}
        </div>
        <section className="pc-wg-preview" aria-label={t("Preview")}>
          <ScaledCard def={def} size={draft} title={draft.title} config={config} />
        </section>
      </div>
      <footer>
        <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button type="submit" className="button button-primary">{t("Apply")}</button>
      </footer>
    </form>
  </div>;
}

/** "Add a widget": the apps at the left, their widgets at the right, each previewed at the size
 * picked for it. A widget already on the page (and not one placed more than once) is marked so. */
export function WidgetPicker({ catalog, used, appName, marks = true, onAdd, onClose }: {
  catalog: WidgetDef[]; used: Set<string>; appName: (id: string) => string; marks?: boolean;
  onAdd: (def: WidgetDef, size: WidgetSizeChoice) => void; onClose: () => void;
}) {
  const groups = [...new Set(catalog.map((item) => item.app))];
  const [group, setGroup] = useState(groups[0] ?? "");
  const [sizes, setSizes] = useState<Record<string, WidgetSizeChoice>>({});
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const shown = catalog.filter((item) => item.app === group);
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="dialog pc-wg-picker" role="dialog" aria-label={t("Add a widget")}>
      <header><h2>{t("Add a widget")}</h2><button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="pc-wg-picker-body">
        <nav className="pc-wg-picker-apps" aria-label={t("Apps")}>
          {groups.map((id) => <button key={id} type="button" className={`pc-wg-picker-app${id === group ? " on" : ""}`} aria-pressed={id === group} onClick={() => setGroup(id)}>
            {marks && appIdFor(id) ? <AppMark app={appIdFor(id)!} size={18} /> : null}<span>{appName(id)}</span><small>{catalog.filter((item) => item.app === id).length}</small>
          </button>)}
        </nav>
        <div className="pc-wg-picker-list">
          {!shown.length && <p className="muted small">{t("This app publishes no widget.")}</p>}
          {shown.map((def) => {
            const size = sizes[def.id] ?? widgetSize(def);
            const taken = !def.multiple && used.has(def.id);
            return <section key={def.id} className="pc-wg-tile" aria-label={def.title}>
              <div className="pc-wg-tile-head"><b>{def.title}</b>{def.description && <small>{def.description}</small>}</div>
              <SizePicker id={`pc-wg-pick-${def.id.replace(/[^a-z0-9-]/gi, "-")}`} def={def} value={size} onChange={(next) => setSizes({ ...sizes, [def.id]: next })} />
              <ScaledCard def={def} size={size} />
              <button type="button" className="button button-secondary button-small" disabled={taken} onClick={() => onAdd(def, size)}>
                {taken ? <><Check size={14} /> {t("On the page")}</> : <><Plus size={14} /> {t("Add")}</>}
              </button>
            </section>;
          })}
        </div>
      </div>
    </div>
  </div>;
}

export function WidgetBoard({ catalog, layout, onLayout, loading, apps = [], onReset, marks = true, empty }: WidgetBoardProps) {
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [setting, setSetting] = useState<string | null>(null);
  const board = useMemo(() => boardOf(layout, catalog), [layout, catalog]);
  const placed = placedItems(board, catalog);
  const byPlacement = new Map(placed.map((entry) => [entry.item.i, entry]));
  const used = new Set(board.map((item) => item.widget));
  const appName = (id: string) => (id === "processcraft" ? "PlantCraft" : appLabel(id, apps.find((app) => app.id === id)?.name ?? id));
  const cells = placed.map(({ item }) => item);
  const moved = (next: GridCell[]) => {
    const at = new Map(next.map((cell) => [cell.i, cell]));
    // Only the place changes: sizes are picked in the settings.
    onLayout(board.map((item) => {
      const cell = at.get(item.i);
      return cell ? { ...item, x: cell.x, y: cell.y } : item;
    }));
  };
  const remove = (i: string) => onLayout(board.filter((item) => item.i !== i));
  const keep = (i: string) => (config: WidgetConfig) => onLayout(board.map((item) => (item.i === i ? { ...item, config } : item)));
  const current = setting ? byPlacement.get(setting) : undefined;
  return <section className={`pc-wg${editing ? " pc-wg-editing" : ""}`} data-tour="widgets">
    <div className={`pc-wg-head${editing ? " pc-wg-head-editing" : ""}`} role={editing ? "region" : undefined} aria-label={editing ? t("Customizing this page") : undefined}>
      {editing && <p className="pc-wg-hint" aria-live="polite"><strong><SlidersHorizontal size={14} aria-hidden="true" /> {t("Customizing this page")}</strong> <span>{t("Drag a widget by its title to move it; its gear sets its size and what it shows. Changes are saved as you make them.")}</span></p>}
      {editing && <button type="button" className="button button-secondary button-small" onClick={() => setAdding(true)}><Plus size={14} /> {t("Add a widget")}</button>}
      {editing && onReset && <button type="button" className="button button-secondary button-small" onClick={() => { onReset(); setAdding(false); }}><RotateCcw size={14} /> {t("Restore the default")}</button>}
      {loading && <LoaderCircle size={14} className="spin" aria-label={t("Loading")} />}
      {editing
        ? <button type="button" className="button button-primary button-small" onClick={() => { setEditing(false); setAdding(false); }}><Check size={14} /> {t("Done")}</button>
        : <button type="button" className="pc-wg-customize" onClick={() => setEditing(true)} title={t("Customize this page")}><SlidersHorizontal size={14} /> {t("Customize")}</button>}
    </div>
    {editing && adding && <WidgetPicker catalog={catalog} used={used} appName={appName} marks={marks} onClose={() => setAdding(false)}
      onAdd={(def, size) => { onLayout(addToBoard(board, def, size)); setAdding(false); }} />}
    {!placed.length && !loading && <div className="panel pc-wg-empty"><p>{empty ?? t("No widgets yet. Press Customize, then Add a widget.")}</p></div>}
    <CardGrid cells={cells} editing={editing} resizable={false} onChange={moved} label={t("Widgets")}
      foldAfter={2} phoneHeight="content"
      render={(i, fold) => {
        const entry = byPlacement.get(i);
        if (!entry) return null;
        const { item, def } = entry;
        const title = item.title || def.title;
        // An app's mark before its widgets' titles; the platform's own (PlantCraft, Desk) go without.
        const mark = marks && appIdFor(def.app) && def.app !== "processcraft" && def.app !== "desk" ? <AppMark app={appIdFor(def.app)!} size={16} /> : null;
        return <WidgetCard def={def} title={item.title} config={item.config} w={item.w} h={item.h} editing={editing} setConfig={keep(item.i)} mark={mark} fold={fold}
          head={(label) => <h2 className={editing ? "pc-cards-handle" : undefined}>{editing && <GripVertical size={14} aria-hidden="true" className="pc-wg-grip" />}{label}</h2>}
          tools={editing && <span className="pc-wg-tools">
            <button type="button" className="pcs-icon-button" onClick={() => setSetting(item.i)} aria-label={t("Set up {title}", { title })}><Settings2 size={14} /></button>
            <button type="button" className="pcs-icon-button" onClick={() => remove(item.i)} aria-label={t("Remove {title}", { title })}><X size={14} /></button>
          </span>} />;
      }} />
    {current && <WidgetSettings item={current.item} def={current.def} onClose={() => setSetting(null)}
      onSave={(next) => { onLayout(board.map((item) => (item.i === next.i ? next : item))); setSetting(null); }} />}
  </section>;
}

/** Every widget of a catalog at every size it allows, at its real size on this page's width: the
 * widget test page. Its browser test fails when a widget spills out of its card. */
export function WidgetGallery({ catalog, apps = [] }: { catalog: WidgetDef[]; apps?: SuiteApp[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const column = columnPixels(width || PREVIEW_BOARD);
  const appName = (id: string) => (id === "processcraft" ? "PlantCraft" : appLabel(id, apps.find((app) => app.id === id)?.name ?? id));
  const groups = [...new Set(catalog.map((item) => item.app))];
  return <div ref={ref} className="pc-wg-gallery">
    {groups.map((group) => <section key={group} className="pc-wg-gallery-app" aria-label={appName(group)}>
      <h2>{appIdFor(group) ? <AppMark app={appIdFor(group)!} size={18} /> : null} {appName(group)}</h2>
      {catalog.filter((def) => def.app === group).map((def) => {
        const sizes = sizesOf(def);
        return <div key={def.id} className="pc-wg-gallery-widget">
          <h3>{def.title} <small className="muted">{def.id}</small></h3>
          <div className="pc-wg-gallery-row">
            {sizes.map((size, index) => <figure key={`${size.w}x${size.h}`} className="pc-wg-gallery-cell" data-widget={def.id} data-size={`${size.w}x${size.h}`}>
              <figcaption>{sizeName(index, sizes.length)} · {size.w} × {size.h}</figcaption>
              <div style={{ width: Math.min(cardWidth(size.w, column), width || Infinity), height: cardPixels(size.h) }}>
                <WidgetCard def={def} w={size.w} h={size.h} />
              </div>
            </figure>)}
          </div>
        </div>;
      })}
    </section>)}
  </div>;
}
