/** Pure helpers of the dashboard page: card defaults, labels, formatting, layout moves. */
import { APP_NAMES, appIdFor } from "@plantcraft/ui/appMarks";
import { fileStamp, fileTime, fileTimeHeader, fitCell, freePlace, gridGap, gridRow, packCells, type GridCell } from "@plantcraft/ui";
import { locale, t } from "./i18n";
import type { Aggregation, Card, CardData, CardItem, Dashboard, DashboardDraft, Kind, Page, State, Variable } from "./types";

/** The old "dashboard's asset" (before variables): the asset variable `asset` now. */
export const CONTEXT = "$context";
export const CONTEXT_VARIABLE = "asset";
/** Every signal of an asset (an item's role). */
export const ALL_ROLES = "*";
/** "All" values of a variable. */
export const ALL_VALUES = "$__all";

export const KINDS: Kind[] = ["stat", "trend", "gauge", "bar", "table", "scatter", "text", "diagram", "apc"];
/** Kinds without signals of their own: a note, a saved diagram, a multivariable controller. */
export const NO_ITEM_KINDS: Kind[] = ["text", "diagram", "apc"];
export const KIND_LABELS: Record<Kind, string> = { stat: "Stat", gauge: "Gauge", trend: "Time series", bar: "Bar chart", table: "Table", scatter: "Scatter (X-Y)", text: "Text", diagram: "Process display", apc: "Multivariable controller" };
export const KIND_HINTS: Record<Kind, string> = {
  stat: "Big numbers, one per signal, coloured by their thresholds, with or without their line.",
  gauge: "Each value on a dial, with its threshold bands.",
  trend: "Lines over time: up to 12 signals, or every signal of an asset.",
  bar: "One bar per signal to compare them, horizontal or vertical, or bar gauges.",
  table: "Last, mean, min, max and more of each signal, coloured by state.",
  scatter: "One signal against another: x, then y.",
  text: "A note: what the dashboard is for, who to call.",
  diagram: "A saved diagram, live and scaled to the panel; a click opens it.",
  apc: "An APC's MVs and CVs: value, limits, target and status, read only.",
};
/** The most signals each kind takes. */
export function maxItemsOf(kind: Kind): number {
  return kind === "scatter" ? 2 : NO_ITEM_KINDS.includes(kind) ? 0 : 12;
}
/** Kinds that show one value with an aggregation (the "Value" choice). */
export const VALUE_KINDS: Kind[] = ["stat", "gauge", "bar"];
export const AGG_LABELS: Record<Aggregation, string> = { last: "Last value", mean: "Mean", min: "Minimum", max: "Maximum", std: "Standard deviation" };
export const WINDOWS = ["15m", "1h", "8h", "24h", "7d", "30d"];
/** The suite's grid (@plantcraft/ui CardGrid): 12 columns, and rows of one unit. A card spans
 * 2 to 12 columns and 1 to 12 rows. */
export const WIDTHS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
export const HEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
export const ROW_PX = 91;
export const GAP_PX = 14;
/** A chart, dial or table needs two rows; a stat or a note fits in one. */
export function minHeight(kind: Kind): number {
  return kind === "stat" || kind === "text" ? 1 : 2;
}
/** The height in pixels of a card `rows` rows high (on a wide screen), at the display size in
 * effect: the suite's grid rows follow the text (ROW_PX and GAP_PX are the default's). */
export function cardPixels(rows: number): number {
  return rows * gridRow() + (rows - 1) * gridGap();
}
export const REFRESH = [0, 15, 30, 60, 300];
export const PAGE_SECONDS = [0, 30, 60, 300];
export const MAX_PAGES = 10;
export const MAX_CARDS_PER_PAGE = 30;

export function windowLabel(window: string): string {
  const match = /^(\d+)([smhd])$/.exec(window);
  if (!match) return window;
  const count = Number(match[1]);
  const unit = { s: ["second", "seconds"], m: ["minute", "minutes"], h: ["hour", "hours"], d: ["day", "days"] }[match[2] as "s"]!;
  return t("{count} {unit}", { count, unit: count === 1 ? unit[0] : unit[1] });
}

export function refreshLabel(seconds: number): string {
  if (!seconds) return t("Manual refresh");
  return seconds < 60 ? t("Every {n} s", { n: seconds }) : t("Every {n} min", { n: seconds / 60 });
}

let counter = 0;
export function newCardId(existing: Card[]): string {
  const used = new Set(existing.map((card) => card.card_id));
  let id = "";
  do id = `c${Date.now().toString(36).slice(-5)}${(counter++).toString(36)}`; while (used.has(id));
  return id;
}

export function defaultCard(kind: Kind, existing: Card[], item?: CardItem): Card {
  return {
    card_id: newCardId(existing),
    title: "",
    kind,
    items: item ? [item] : [],
    agg: "last",
    window: kind === "trend" || kind === "scatter" || kind === "apc" ? "8h" : kind === "table" ? "24h" : "1h",
    field: {},
    overrides: [],
    options: {},
    width: kind === "stat" || kind === "gauge" ? 3 : kind === "trend" || kind === "diagram" || kind === "apc" ? 8 : 6,
    height: kind === "trend" || kind === "table" || kind === "scatter" || kind === "bar" || kind === "diagram" || kind === "apc" ? 4 : kind === "text" ? 2 : 2,
    ...(kind === "text" ? { text: "" } : {}),
    ...(kind === "diagram" ? { diagram_id: "" } : {}),
    ...(kind === "apc" ? { apc_id: "" } : {}),
  };
}

export const EMPTY_DRAFT: DashboardDraft = { name: t("New dashboard"), description: "", context_kind: null, variables: [], refresh_seconds: 60, pages: [], page_seconds: 0, cards: [], folder_id: "", tags: [], default_window: null, shared_cursor: false, kiosk: false };

/** A card saved before round 7 (an imported file) in the round 7 shape, as the server reads it
 * (legacy.py): kinds kpi and spark are stats, the four limits are threshold steps. */
export function upgradeCard(raw: Card & Record<string, unknown>): Card {
  const card: Record<string, unknown> = { ...raw };
  const options: Record<string, unknown> = { ...((card.options as object) ?? {}) };
  const field: Record<string, unknown> = { ...((card.field as object) ?? {}) };
  if (card.kind === "kpi" || card.kind === "spark") { options.graph ??= card.kind === "spark" ? "area" : "none"; card.kind = "stat"; }
  const old = card.thresholds as Record<string, number | null | undefined> | undefined;
  delete card.thresholds;
  if (old && !field.thresholds && Object.values(old).some((value) => typeof value === "number")) {
    const steps: Array<{ value?: number; level: string }> = [{ level: typeof old.low_alarm === "number" ? "alarm" : typeof old.low_warn === "number" ? "warning" : "ok" }];
    if (typeof old.low_alarm === "number") steps.push({ value: old.low_alarm, level: typeof old.low_warn === "number" ? "warning" : "ok" });
    if (typeof old.low_warn === "number") steps.push({ value: old.low_warn, level: "ok" });
    if (typeof old.high_warn === "number") steps.push({ value: old.high_warn, level: "warning" });
    if (typeof old.high_alarm === "number") steps.push({ value: old.high_alarm, level: "alarm" });
    field.thresholds = { steps };
  }
  for (const [from, to] of [["decimals", "decimals"], ["gauge_min", "min"], ["gauge_max", "max"]] as const) {
    if (from in card) { const value = card[from]; delete card[from]; if (value !== null && value !== undefined) field[to] ??= value; }
  }
  card.items = ((card.items as CardItem[]) ?? []).map((item) => (item.asset_id === CONTEXT ? { ...item, asset_id: `$${CONTEXT_VARIABLE}` } : item));
  return { overrides: [], ...card, field, options } as unknown as Card;
}

/** A dashboard's variables, with the old asset picker (`context_kind`) as the variable `asset`. */
export function variablesOf(dashboard: Partial<Pick<Dashboard, "variables" | "context_kind">>): Variable[] {
  const found = dashboard.variables ?? [];
  if (dashboard.context_kind && !found.some((item) => item.type === "asset")) return [{ name: CONTEXT_VARIABLE, label: dashboard.context_kind, type: "asset", asset_kind: dashboard.context_kind }, ...found];
  return found;
}

export function draftOf(dashboard: Partial<Dashboard> & Pick<Dashboard, "name">): DashboardDraft {
  return {
    name: dashboard.name, description: dashboard.description ?? "", context_kind: dashboard.context_kind ?? null, refresh_seconds: dashboard.refresh_seconds ?? 60,
    variables: variablesOf(dashboard),
    pages: dashboard.pages ?? [], page_seconds: dashboard.page_seconds ?? 0, cards: (dashboard.cards ?? []).map((card) => upgradeCard(card as Card & Record<string, unknown>)),
    folder_id: dashboard.folder_id ?? "", tags: dashboard.tags ?? [], default_window: dashboard.default_window ?? null,
    shared_cursor: Boolean(dashboard.shared_cursor), kiosk: Boolean(dashboard.kiosk),
  };
}

/** The dashboard as a file to take to another installation (Config › JSON), and back. */
export const EXPORT_FORMAT = "processcraft-dashboard";
export function exportDashboard(draft: DashboardDraft): string {
  const { folder_id: _folder, ...rest } = draft;
  return JSON.stringify({ format: EXPORT_FORMAT, version: 1, dashboard: rest }, null, 2);
}
/** A dashboard read from an exported file (or a bare dashboard object); throws on anything else. */
export function importDashboard(text: string): DashboardDraft {
  const parsed: unknown = JSON.parse(text);
  const found = parsed && typeof parsed === "object" && "dashboard" in parsed ? (parsed as { dashboard: unknown }).dashboard : parsed;
  if (!found || typeof found !== "object" || typeof (found as { name?: unknown }).name !== "string" || !Array.isArray((found as { cards?: unknown }).cards)) {
    throw new Error(t("This file is not a View dashboard."));
  }
  return { ...draftOf(found as Dashboard), folder_id: "" };
}

/** Who a folder lets in, in words: "Everyone", or how many people and groups. */
export function accessLabel(entries: string[]): string {
  if (!entries.length) return t("Everyone");
  const groups = entries.filter((entry) => entry.startsWith("group:")).length;
  const people = entries.length - groups;
  const groupWords = groups === 1 ? t("1 group") : groups ? t("{n} groups", { n: groups }) : "";
  const peopleWords = people === 1 ? t("1 person") : people ? t("{n} people", { n: people }) : "";
  return [groupWords, peopleWords].filter(Boolean).join(", ");
}

/** Dashboards whose name, description or tags hold every word typed. */
export function matchesSearch(item: Pick<Dashboard, "name" | "description" | "tags">, text: string): boolean {
  const words = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = [item.name, item.description, ...(item.tags ?? [])].join(" ").toLowerCase();
  return words.every((word) => haystack.includes(word));
}

export function pageSecondsLabel(seconds: number): string {
  if (!seconds) return t("Never");
  return seconds < 60 ? t("Every {n} s", { n: seconds }) : t("Every {n} min", { n: seconds / 60 });
}

/** The page shown: the one named in the address, else the first; null without pages. */
export function currentPage(pages: Page[], wanted: string | null): Page | null {
  return pages.find((page) => page.page_id === wanted) ?? pages[0] ?? null;
}

/** The cards of one page (a card without a page is on the first). */
export function cardsOn(draft: Pick<DashboardDraft, "pages" | "cards">, page: Page | null): Card[] {
  if (!page || !draft.pages.length) return draft.cards;
  const first = draft.pages[0].page_id;
  return draft.cards.filter((card) => (card.page_id ?? first) === page.page_id);
}

function newPageId(pages: Page[]): string {
  const used = new Set(pages.map((page) => page.page_id));
  let n = pages.length + 1;
  while (used.has(`p${n}`)) n += 1;
  return `p${n}`;
}

/** A new, empty page at the end. A dashboard without pages first gets its one page named
 * "Page 1", and every card a page, so moving or removing pages never moves a card. */
export function addPage(draft: DashboardDraft): [DashboardDraft, string] {
  const pages = draft.pages.length ? draft.pages : [{ page_id: "p1", name: t("Page {n}", { n: 1 }) }];
  const first = pages[0].page_id;
  const page = { page_id: newPageId(pages), name: t("Page {n}", { n: pages.length + 1 }) };
  const cards = draft.cards.map((card) => ({ ...card, page_id: card.page_id ?? first }));
  return [{ ...draft, pages: [...pages, page], cards }, page.page_id];
}

/** Remove a page and its cards. */
export function removePage(draft: DashboardDraft, pageId: string): DashboardDraft {
  const page = draft.pages.find((item) => item.page_id === pageId);
  if (!page) return draft;
  const gone = new Set(cardsOn(draft, page).map((card) => card.card_id));
  return { ...draft, pages: draft.pages.filter((item) => item.page_id !== pageId), cards: draft.cards.filter((card) => !gone.has(card.card_id)) };
}

/** Move a page one place earlier (-1) or later (+1), its cards with it. */
export function movePage(draft: DashboardDraft, pageId: string, step: -1 | 1): DashboardDraft {
  const index = draft.pages.findIndex((page) => page.page_id === pageId);
  const target = index + step;
  if (index < 0 || target < 0 || target >= draft.pages.length) return draft;
  const first = draft.pages[0].page_id;
  const pages = [...draft.pages];
  [pages[index], pages[target]] = [pages[target], pages[index]];
  // Cards without a page were on the old first page: name it before the first one changes.
  return { ...draft, pages, cards: draft.cards.map((card) => ({ ...card, page_id: card.page_id ?? first })) };
}

export function renamePage(draft: DashboardDraft, pageId: string, name: string): DashboardDraft {
  return { ...draft, pages: draft.pages.map((page) => (page.page_id === pageId ? { ...page, name } : page)) };
}

/** The variable a value is entirely (`$loop` or `${loop}`), else null. */
export function variableOf(value: string | null | undefined): string | null {
  const match = /^\$\{?([A-Za-z][A-Za-z0-9_]{0,29})\}?$/.exec(value ?? "");
  return match && value !== ALL_VALUES ? match[1] : null;
}

/** `${loop}` and `$loop` replaced by the variable's shown values (several joined by commas). */
export function interpolate(text: string, values: Record<string, string[]>): string {
  if (!text || !text.includes("$")) return text;
  return text.replace(/\$\{([A-Za-z][A-Za-z0-9_]{0,29})\}|\$([A-Za-z][A-Za-z0-9_]{0,29})\b/g, (whole, a, b) => {
    const found = values[a ?? b];
    return found?.length ? found.join(", ") : whole;
  });
}

/** Whether cards name a variable (by an asset, a signal id, a window or a repeat). */
export function usesVariable(cards: Card[], name: string): boolean {
  const named = (text?: string | null) => Boolean(text) && new RegExp(`\\$\\{?${name}\\b`).test(text ?? "");
  return cards.some((card) => card.repeat?.variable === name || named(card.window) || named(card.title) || named(card.text)
    || card.items.some((item) => named(item.asset_id) || named(item.signal_id) || named(item.label)));
}

/** Kept for older callers: whether cards use the old dashboard's asset. */
export function usesContext(cards: Card[]): boolean {
  return usesVariable(cards, CONTEXT_VARIABLE) || cards.some((card) => card.items.some((item) => item.asset_id === CONTEXT));
}

/** A card's heading: its title (variables filled in), else what it shows ("FIC-101 PV · mean"). */
export function cardTitle(card: Card, values: Record<string, string[]> = {}): string {
  if (card.title.trim()) return interpolate(card.title.trim(), values);
  const names = card.items.map((item) => interpolate(itemName(item), values)).filter(Boolean);
  const subject = names.length > 2 ? t("{first} and {count} more", { first: names[0], count: names.length - 1 }) : names.join(", ");
  if (card.kind === "text") return "";
  if (card.kind === "diagram") return t(KIND_LABELS.diagram);
  const graph = card.kind === "stat" && card.options?.graph === "area";
  if (VALUE_KINDS.includes(card.kind) && !graph && !card.items.every((item) => item.result)) return `${subject} · ${AGG_LABELS[card.agg].toLowerCase()}`;
  return subject || t(KIND_LABELS[card.kind]);
}

export type Mode = "variable" | "asset" | "signal";

/** How an item names its signal. A signal item still being picked has ``signal_id: ""``. */
export function itemMode(item: CardItem): Mode {
  if (item.signal_id !== undefined && item.signal_id !== null) return "signal";
  return variableOf(item.asset_id) || item.asset_id === CONTEXT ? "variable" : "asset";
}

export function itemName(item: CardItem): string {
  if (item.label) return item.label;
  const variable = item.asset_id === CONTEXT ? CONTEXT_VARIABLE : variableOf(item.asset_id);
  if (item.result) {
    const what = resultLabel(item.result);
    return variable ? what : `${item.asset_id ?? item.signal_id ?? ""} ${what}`.trim();
  }
  if (item.signal_id) return item.signal_id;
  if (item.role === ALL_ROLES) {
    // Every signal of an asset: named by the asset (`${loop}` is filled in by the title).
    const asset = variable ? `\${${variable}}` : item.asset_id ?? "";
    return item.roles?.length ? `${asset} ${item.roles.map((r) => r.toUpperCase()).join(", ")}`.trim() : t("{asset} signals", { asset }).trim();
  }
  const role = (item.role ?? "").toUpperCase();
  return variable ? role : `${item.asset_id ?? ""} ${role}`.trim();
}

/** A value for people: numbers with the card's decimals (else a sensible number), text as is. */
export function formatValue(value: number | string | null | undefined, decimals?: number | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (!Number.isFinite(value)) return "—";
  const digits = decimals ?? (Math.abs(value) >= 1000 ? 0 : Math.abs(value) >= 10 ? 1 : 2);
  return value.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Status tone (brandTheme STATUS_TONES ids) of a value state. */
export function stateStatus(state: State | undefined): string {
  return state === "alarm" ? "critical" : state === "warning" ? "medium" : state === "ok" ? "normal" : "inactive";
}

export function stateLabel(state: State | undefined): string {
  return state === "alarm" ? t("Critical") : state === "warning" ? t("Warning") : state === "ok" ? t("Within limits") : state === "unknown" ? t("Unknown") : "";
}

/** The grid cells of cards (cards without a place flow in, in order, as the server places them). */
export function cellsOf(cards: Card[]): GridCell[] {
  const placed = cards.filter((card) => typeof card.x === "number" && typeof card.y === "number").map((card) => fitCell({ i: card.card_id, x: card.x as number, y: card.y as number, w: card.width, h: card.height }));
  const loose = cards.filter((card) => !(typeof card.x === "number" && typeof card.y === "number")).map((card) => ({ i: card.card_id, w: card.width, h: card.height }));
  const byId = new Map([...placed, ...packCells(loose, placed)].map((cell) => [cell.i, cell]));
  return cards.map((card) => byId.get(card.card_id)!);
}

/** Cards moved and resized to `cells` (cards of other pages untouched). */
export function withCells(cards: Card[], cells: GridCell[]): Card[] {
  const byId = new Map(cells.map((cell) => [cell.i, cell]));
  return cards.map((card) => {
    const cell = byId.get(card.card_id);
    return cell ? { ...card, x: cell.x, y: cell.y, width: Math.max(2, cell.w), height: Math.max(minHeight(card.kind), cell.h) } : card;
  });
}

/** A new card's place on its page: the first free place for its size. */
export function placeNew(card: Card, onPage: Card[]): Card {
  const { x, y } = freePlace(cellsOf(onPage), card.width, card.height);
  return { ...card, x, y };
}

/** A card shown once per value of the variable it repeats for (Grafana's repeat options): the
 * cards to draw with the values each reads, and their grid cells. Side by side, the copies share
 * full rows (`max_per_row` each); one under the other, they keep the card's width. The cards
 * under a repeated card move down by the rows its copies add. */
export interface Shown { card: Card; key: string; values: Record<string, string[]>; texts: Record<string, string[]> }
export function repeatCards(cards: Card[], values: Record<string, string[]>, texts: Record<string, string[]>): { shown: Shown[]; cells: GridCell[] } {
  let cells = cellsOf(cards);
  const shown: Shown[] = cards.map((card) => ({ card, key: card.card_id, values, texts }));
  const order = cards.map((card, index) => ({ card, index })).filter(({ card }) => card.repeat && (values[card.repeat.variable]?.length ?? 0) > 1)
    .sort((a, b) => cells[a.index].y - cells[b.index].y);
  for (const { card } of order) {
    const cell = cells.find((item) => item.i === card.card_id)!;
    const name = card.repeat!.variable;
    const picked = values[name];
    const across = card.repeat!.direction !== "v";
    const perRow = across ? Math.max(1, Math.min(card.repeat!.max_per_row, picked.length)) : 1;
    const width = across ? Math.max(2, Math.floor(12 / perRow)) : cell.w;
    const rows = Math.ceil(picked.length / perRow);
    const block = rows * cell.h;
    const copies: GridCell[] = picked.map((_, n) => ({
      i: n ? `${card.card_id}~${n}` : card.card_id,
      x: across ? Math.min(12 - width, (n % perRow) * width) : cell.x,
      y: cell.y + Math.floor(n / perRow) * cell.h, w: width, h: cell.h,
    }));
    const others = cells.filter((item) => item.i !== card.card_id).map((item) => {
      if (item.y >= cell.y + cell.h) return { ...item, y: item.y + block - cell.h };
      // A card beside a repeat that fills whole rows goes under the copies.
      if (across && item.y >= cell.y && item.y < cell.y + cell.h) return { ...item, y: cell.y + block + (item.y - cell.y) };
      return item;
    });
    cells = [...others, ...copies];
    const at = shown.findIndex((item) => item.key === card.card_id);
    shown.splice(at, 1, ...picked.map((value, n) => ({
      card, key: n ? `${card.card_id}~${n}` : card.card_id,
      values: { ...values, [name]: [value] },
      texts: { ...texts, [name]: [texts[name]?.[n] ?? value] },
    })));
  }
  return { shown, cells };
}

/** "Updated 19 Oct, 14:05 by ana" */
export function when(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

/** The page's view settings kept in the address, so a link opens the same view. Variables are
 * `var-<name>` (repeated for several values), as Grafana writes them; `asset` is the old picker. */
export interface ViewState { vars: Record<string, string[]>; window: string | null; screen: boolean; edit: boolean; page: string | null }

export function readView(search: string): ViewState {
  const params = new URLSearchParams(search);
  const window = params.get("w");
  const vars: Record<string, string[]> = {};
  for (const [key, value] of params.entries()) {
    if (key.startsWith("var-") && value) (vars[key.slice(4)] ??= []).push(value);
  }
  const old = params.get("asset");
  if (old && !vars[CONTEXT_VARIABLE]) vars[CONTEXT_VARIABLE] = [old];
  return {
    vars,
    window: window && /^\d{1,5}[smhd]$/.test(window) ? window : null,
    screen: params.get("screen") === "1",
    edit: params.get("edit") === "1",
    page: params.get("page") || null,
  };
}

export function writeView(view: ViewState): string {
  const params = new URLSearchParams();
  if (view.page) params.set("page", view.page);
  for (const [name, values] of Object.entries(view.vars ?? {})) for (const value of values) params.append(`var-${name}`, value);
  if (view.window) params.set("w", view.window);
  if (view.screen) params.set("screen", "1");
  if (view.edit) params.set("edit", "1");
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** An app result as people read it: "linkcraft.loop_health" is "Loop health (Link)", the app's
 * short name inside the suite (D10); an app merged into another goes by the new one's name
 * ("cpmcraft." is Link's). */
export function resultLabel(result: string): string {
  const [app, name = ""] = result.split(".");
  const words = name.replace(/_/g, " ");
  const family = appIdFor(app);
  const known = family ? APP_NAMES[family] : null;
  const appName = known ?? app;
  return `${words.charAt(0).toUpperCase()}${words.slice(1)} (${appName})`;
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  // Quote what a spreadsheet would split, and keep a cell from being read as a formula.
  const safe = /^[=+\-@\t\r]/.test(text) && !/^-?\d/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The data a card shows, as CSV: one row per sample for a trend, one row per item otherwise. */
export function cardCsv(data: CardData): string {
  const rows: unknown[][] = [];
  if (data.lines) {
    rows.push([fileTimeHeader(), "label", "signal", "value", "unit"]);
    for (const line of data.lines) line.t.forEach((time, index) => rows.push([fileTime(time), line.label, line.signal, line.v[index], line.unit]));
  } else if (data.kind === "table") {
    rows.push(["label", "signal", "last", "mean", "min", "max", "unit", fileTimeHeader("at"), "state"]);
    for (const row of data.rows ?? []) rows.push([row.label, row.signal, row.values?.last, row.values?.mean, row.values?.min, row.values?.max, row.unit, fileTime(row.at), row.state]);
  } else {
    rows.push(["label", "signal", "value", "unit", "aggregation", fileTimeHeader("at"), "state"]);
    for (const row of data.rows ?? []) rows.push([row.label, row.signal ?? row.result, row.value, row.unit, row.agg, fileTime(row.at), row.state]);
  }
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/** A file name for a card's CSV: its title, the window and when it was read. */
export function cardCsvName(card: Card, data: CardData): string {
  const slug = cardTitle(card).toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || card.card_id;
  return `${slug}-${data.window}-${fileStamp(data.read_at)}.csv`;
}
