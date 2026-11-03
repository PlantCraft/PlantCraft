/** Diagrams (View › Diagrams): the shapes the API saves and reads, and the pure functions the
 * page and the editor share: where a symbol's ports are once it is moved, turned and flipped, the
 * path of a line, and what a binding's value means at any instant of the window (the same rules
 * as `diagrams/read.py` on the server, so playback colours the plant as live view does). */

import { t } from "../i18n";

export type State = "ok" | "warning" | "alarm" | "unknown";
export type Dir = "n" | "s" | "e" | "w";
export type Point = [number, number];

export interface Port { id: string; x: number; y: number; dir: Dir; kind?: string }
export interface Anchor { id: string; x: number; y: number; align: "start" | "middle" | "end" }
export interface SymbolDef {
  id: string; title: string; category: string; w: number; h: number; svg: string;
  ports: Port[]; anchors: Anchor[]; keywords: string[]; standard?: string; asset_types?: string[];
  /** A shape that may take any proportions (a unit block); every other drawing keeps its own. */
  stretch?: boolean;
}

/** A card item: a signal, an asset and a role, or an app's result about one of them. */
export interface Item { signal_id?: string | null; asset_id?: string | null; role?: string | null; result?: string | null; label?: string }
export interface Limits { low_alarm?: number | null; low_warning?: number | null; high_warning?: number | null; high_alarm?: number | null }
export interface StateBinding { item: Item; limits?: Limits }
export interface LevelBinding { item: Item; min: number; max: number }
export interface OnBinding { item: Item; above: number }
export interface LinkTo { kind: "page" | "area" | "diagram" | "dashboard" | "asset" | "trend"; target: string }

/** An `area` link's part of the canvas ("x,y,w,h"), or null when it does not read as one. */
export function areaOf(target: string): { x: number; y: number; w: number; h: number } | null {
  const [x, y, w, h] = target.split(",").map((part) => Number(part.trim()));
  return [x, y, w, h].every(Number.isFinite) && w > 0 && h > 0 ? { x, y, w, h } : null;
}

export type LabelPosition = "below" | "above" | "left" | "right" | "inside" | "none";
export const LABEL_POSITIONS: LabelPosition[] = ["below", "above", "left", "right", "inside", "none"];

interface Base { id: string; page?: string; link?: LinkTo | null }
export interface SymbolElement extends Base {
  type: "symbol"; symbol: string; x: number; y: number; w: number; h: number;
  rotate: 0 | 90 | 180 | 270; flip: boolean; label: string;
  label_position: LabelPosition; asset_id?: string | null;
  state?: StateBinding | null; level?: LevelBinding | null; running?: OnBinding | null;
}
/** The ISA-101 analog indicator under a value (Indicator in diagrams/model.py). */
export interface Indicator { min?: number | null; max?: number | null; normal_low?: number | null; normal_high?: number | null; setpoint?: Item | null; width: number }
export interface ValueElement extends Base {
  type: "value"; x: number; y: number; item: Item; label: string; show_label: boolean;
  show_unit: boolean; decimals?: number | null; size: number; limits?: Limits; indicator?: Indicator | null;
}
export interface Endpoint { element: string; port: string }
export interface LineElement extends Base {
  type: "line"; kind: "process" | "signal" | "utility"; medium: string; points: Point[];
  start?: Endpoint | null; end?: Endpoint | null; arrow: "none" | "end" | "start" | "both";
  label: string; flow?: OnBinding | null;
}
export interface TextElement extends Base {
  type: "text"; x: number; y: number; text: string; size: number; align: "start" | "middle" | "end"; bold: boolean;
}
export type Element = SymbolElement | ValueElement | LineElement | TextElement;
export type Slot = "state" | "level" | "running" | "value" | "setpoint" | "flow";

/** A page of a diagram: a unit or an area of the plant. */
export interface Page { id: string; name: string }
/** A named part of a large page, "x,y,w,h": a tab of the viewer zooms to it. */
export interface Part { id: string; name: string; area: string }

export interface DiagramDraft {
  name: string; description: string; folder_id: string; tags: string[];
  width: number; height: number; grid: number; refresh_seconds: number; default_window: string;
  pages?: Page[]; parts?: Part[]; elements: Element[];
}
export interface Diagram extends DiagramDraft {
  diagram_id: string; element_count: number; can_edit: boolean;
  created_by?: string | null; created_at?: string; updated_by?: string | null; updated_at: string;
}
export type DiagramSummary = Pick<Diagram, "diagram_id" | "name" | "description" | "folder_id" | "tags" | "updated_by" | "updated_at" | "element_count" | "can_edit">;

export interface BindingRow {
  element: string; slot: Slot; label: string; signal?: string | null; unit?: string; kind?: string;
  value?: number | string | null; at?: string | null; state: State; error?: string | null;
  stale?: boolean; summary?: string; fraction?: number | null; on?: boolean | null; history?: boolean;
  role?: string | null; asset?: string | null; result?: string; low?: number | null; high?: number | null;
}
export interface Series { t: string[]; v: Array<number | string | null>; error?: string }
export interface DiagramData {
  read_at: string;
  range: { start: string; end: string; step: number; live: boolean };
  bindings: BindingRow[];
  series: Record<string, Series>;
}

export const STALE_SECONDS = 900;

export function emptyDiagram(name = t("New process display")): DiagramDraft {
  return { name, description: "", folder_id: "", tags: [], width: 1200, height: 700, grid: 10, refresh_seconds: 15, default_window: "1h", elements: [] };
}

export const MAX_PAGES = 30;

/** The pages of a diagram, in order; a diagram without pages is one page, id "". */
export function pagesOf(diagram: Pick<DiagramDraft, "pages" | "name">): Page[] {
  return diagram.pages?.length ? diagram.pages : [{ id: "", name: diagram.name }];
}

/** The id of the page an element is on (its own, else the first). */
export function pageOf(element: Element, pages: Page[]): string {
  return element.page && pages.some((page) => page.id === element.page) ? element.page : pages[0]?.id ?? "";
}

/** The page `page` exists (else the first page's id). */
export function knownPage(diagram: Pick<DiagramDraft, "pages" | "name">, page: string | null | undefined): string {
  const pages = pagesOf(diagram);
  return pages.find((item) => item.id === page)?.id ?? pages[0].id;
}

/** The diagram with only the elements of one page, as the canvas draws it. */
export function onPage<T extends DiagramDraft>(diagram: T, page: string): T {
  const pages = pagesOf(diagram);
  if (pages.length < 2) return diagram;
  return { ...diagram, elements: diagram.elements.filter((element) => pageOf(element, pages) === page) };
}

/** A diagram that has pages: a one-page diagram first gets its page (named "Page 1"), then a new
 * one is added after it. Returns the diagram and the new page's id. */
export function withPage<T extends DiagramDraft>(diagram: T, name: string): [T, string] {
  const pages = diagram.pages?.length ? diagram.pages : [{ id: "p1", name: t("Page {n}", { n: 1 }) }];
  const first = pages[0].id;
  const elements = diagram.pages?.length ? diagram.elements : diagram.elements.map((element) => ({ ...element, page: first }));
  let n = pages.length + 1;
  while (pages.some((page) => page.id === `p${n}`)) n += 1;
  const id = `p${n}`;
  return [{ ...diagram, pages: [...pages, { id, name }], elements }, id];
}

/** A diagram without one of its pages and the elements on it; the last page cannot go. */
export function withoutPage<T extends DiagramDraft>(diagram: T, page: string): T {
  const pages = pagesOf(diagram);
  if (pages.length < 2) return diagram;
  const left = pages.filter((item) => item.id !== page);
  const elements = diagram.elements.filter((element) => pageOf(element, pages) !== page)
    .map((element) => (element.link?.kind === "page" && element.link.target === page ? { ...element, link: null } : element));
  return { ...diagram, pages: left, elements };
}

/** A diagram with one page moved one place earlier (-1) or later (1). */
export function movedPage<T extends DiagramDraft>(diagram: T, page: string, by: -1 | 1): T {
  const pages = [...pagesOf(diagram)];
  const at = pages.findIndex((item) => item.id === page);
  const to = at + by;
  if (at < 0 || to < 0 || to >= pages.length || !diagram.pages?.length) return diagram;
  [pages[at], pages[to]] = [pages[to], pages[at]];
  return { ...diagram, pages };
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** ok, warning or alarm for a number against its limits; unknown for anything else. */
export function limitState(limits: Limits | undefined | null, value: unknown): State {
  const number = finite(value);
  if (number === null) return "unknown";
  const l = limits ?? {};
  if ((l.low_alarm != null && number <= l.low_alarm) || (l.high_alarm != null && number >= l.high_alarm)) return "alarm";
  if ((l.low_warning != null && number <= l.low_warning) || (l.high_warning != null && number >= l.high_warning)) return "warning";
  return "ok";
}

/** What a binding's slot shows for one value (`judge` in diagrams/read.py). */
export interface Shown { state: State; value: number | string | null; fraction?: number | null; on?: boolean | null; unit: string; error?: string | null; stale?: boolean; summary?: string; label: string; at?: string | null;
  /** The signal's range (its low and high), for an indicator without its own. */
  low?: number | null; high?: number | null;
  /** The most urgent active alarm's priority (Alarms' alarm_state): the alarm mark's shape. */
  priority?: "critical" | "high" | "medium" | "low" | null }

export function judge(slot: Slot, binding: Record<string, unknown>, row: BindingRow, value: number | string | null, stale = false): Shown {
  const base: Shown = { state: "unknown", value, unit: row.unit ?? "", error: row.error, stale, summary: row.summary, label: row.label, at: row.at, low: row.low, high: row.high };
  if (row.error) return base;
  const number = finite(value);
  if (slot === "state" || slot === "value") {
    base.state = row.kind === "result" ? row.state : limitState(binding.limits as Limits | undefined, value);
  } else if (slot === "setpoint") {
    base.state = number === null ? "unknown" : "ok";
  } else if (slot === "level") {
    const low = Number(binding.min ?? 0), high = Number(binding.max ?? 100);
    base.fraction = number === null ? null : Math.min(1, Math.max(0, (number - low) / (high - low)));
    base.state = number === null ? "unknown" : "ok";
  } else {
    base.on = number === null ? null : number > Number(binding.above ?? 0.5);
    base.state = number === null ? "unknown" : "ok";
  }
  if (stale) base.state = "unknown";
  return base;
}

/** Every binding of a diagram: (element, slot, binding), as `bindings()` in diagrams/model.py. */
export function bindingsOf(elements: Element[]): Array<[string, Slot, Record<string, unknown>]> {
  const out: Array<[string, Slot, Record<string, unknown>]> = [];
  for (const element of elements) {
    if (element.type === "symbol") {
      for (const slot of ["state", "level", "running"] as const) if (element[slot]) out.push([element.id, slot, element[slot] as unknown as Record<string, unknown>]);
    } else if (element.type === "value") {
      out.push([element.id, "value", { item: element.item, limits: element.limits }]);
      if (element.indicator?.setpoint) out.push([element.id, "setpoint", { item: element.indicator.setpoint }]);
    }
    else if (element.type === "line" && element.flow) out.push([element.id, "flow", element.flow as unknown as Record<string, unknown>]);
  }
  return out;
}

/** The index of the last sample at or before `at` (ms), or -1. Times are ISO strings in order. */
export function indexAt(times: number[], at: number): number {
  let low = 0, high = times.length - 1, found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (times[mid] <= at) { found = mid; low = mid + 1; } else high = mid - 1;
  }
  return found;
}

/** The series as numbers of milliseconds, read once per answer. */
export function seriesTimes(data: DiagramData): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  for (const [signal, line] of Object.entries(data.series)) out[signal] = line.t.map((stamp) => Date.parse(stamp));
  return out;
}

/** What each element's slots show: now (cursor null, the values read) or at the cursor (ms,
 * from the window's series; a value is the last non-empty sample at or before it). */
export function shownAt(elements: Element[], data: DiagramData | null, times: Record<string, number[]>, cursor: number | null): Map<string, Partial<Record<Slot, Shown>>> {
  const out = new Map<string, Partial<Record<Slot, Shown>>>();
  if (!data) return out;
  const rows = new Map(data.bindings.map((row) => [`${row.element}/${row.slot}`, row]));
  for (const [element, slot, binding] of bindingsOf(elements)) {
    const row = rows.get(`${element}/${slot}`);
    if (!row) continue;
    let value: number | string | null = row.value ?? null;
    let at = row.at ?? null;
    let stale = Boolean(row.stale);
    let error = row.error;
    if (cursor !== null && row.kind !== "result" && row.signal) {
      const line = data.series[row.signal];
      const stamps = times[row.signal] ?? [];
      value = null; at = null;
      if (line) {
        for (let index = indexAt(stamps, cursor); index >= 0; index -= 1) {
          const candidate = line.v[index];
          if (candidate !== null && candidate !== undefined) { value = candidate; at = line.t[index]; break; }
        }
        error = error || line.error;
      }
      stale = false;
    }
    const shown = judge(slot, binding, { ...row, error, at }, value, stale);
    if (cursor !== null && row.kind === "result") { shown.state = "unknown"; shown.summary = row.summary; }
    out.set(element, { ...(out.get(element) ?? {}), [slot]: shown });
  }
  return out;
}

/** A value as the diagram writes it: the decimals asked for, else as many as its size needs. */
export function formatValue(value: number | string | null | undefined, decimals?: number | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (!Number.isFinite(value)) return "—";
  if (decimals !== null && decimals !== undefined) return value.toFixed(decimals);
  const size = Math.abs(value);
  return value.toFixed(size >= 1000 ? 0 : size >= 100 ? 1 : size >= 1 ? 2 : 3);
}

// Geometry -------------------------------------------------------------------------------------

export interface Box { x: number; y: number; w: number; h: number }

const TURN: Record<Dir, Dir> = { n: "e", e: "s", s: "w", w: "n" };
const MIRROR: Record<Dir, Dir> = { n: "n", s: "s", e: "w", w: "e" };
const BACK: Record<Dir, Dir> = { n: "s", s: "n", e: "w", w: "e" };

/** Where the drawing sits in the element's box before it is turned: the same scale both ways (a
 * pump is never squashed) and centred, as `preserveAspectRatio="xMidYMid meet"` draws it. A
 * shape that stretches (`stretch`, a unit block) fills the box. */
export function fitted(element: { w: number; h: number }, def: { w: number; h: number; stretch?: boolean }): Box & { sx: number; sy: number } {
  if (def.stretch) return { x: 0, y: 0, w: element.w, h: element.h, sx: element.w / def.w, sy: element.h / def.h };
  const scale = Math.min(element.w / def.w, element.h / def.h);
  const w = def.w * scale, h = def.h * scale;
  return { x: (element.w - w) / 2, y: (element.h - h) / 2, w, h, sx: scale, sy: scale };
}

/** A point of the element's own box (0..w, 0..h) on the canvas, after it is flipped (left to
 * right) and turned clockwise about the box's centre. */
function place(element: SymbolElement, px: number, py: number): Point {
  if (element.flip) px = element.w - px;
  const cx = element.w / 2, cy = element.h / 2;
  const turns = (element.rotate / 90) % 4;
  for (let i = 0; i < turns; i += 1) [px, py] = [cx - (py - cy), cy + (px - cx)];
  return [element.x + px, element.y + py];
}

/** A point of the symbol's own drawing (its viewBox) on the canvas: scaled into its box without
 * distortion (`fitted`), flipped and turned. */
export function placePoint(element: SymbolElement, def: { w: number; h: number; stretch?: boolean }, x: number, y: number): Point {
  const fit = fitted(element, def);
  return place(element, fit.x + x * fit.sx, fit.y + y * fit.sy);
}

export function placeDir(element: SymbolElement, dir: Dir): Dir {
  let out = element.flip ? MIRROR[dir] : dir;
  for (let i = 0; i < (element.rotate / 90) % 4; i += 1) out = TURN[out];
  return out;
}

/** The symbol's box on the canvas once turned (a quarter turn swaps width and height about the
 * centre); given its drawing, the box the drawing really covers (`fitted`), which the selection,
 * the labels and the lines go by. */
export function symbolBox(element: SymbolElement, def?: { w: number; h: number; stretch?: boolean } | null): Box {
  const local = def ? fitted(element, def) : { x: 0, y: 0, w: element.w, h: element.h };
  const a = place(element, local.x, local.y), b = place(element, local.x + local.w, local.y + local.h);
  return { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(b[0] - a[0]), h: Math.abs(b[1] - a[1]) };
}

/** Where a line meets a symbol: its port (unknown port or symbol: the box's centre, and no way
 * out), the way out, and the box the drawing covers. */
export function endpointOf(end: Endpoint, elements: Map<string, Element>, symbols: Map<string, SymbolDef>): { point: Point; dir: Dir | null; box: Box } | null {
  const element = elements.get(end.element);
  if (!element || element.type !== "symbol") return null;
  const def = symbols.get(element.symbol);
  const box = symbolBox(element, def);
  const port = def?.ports.find((item) => item.id === end.port);
  if (!def || !port) return { point: [box.x + box.w / 2, box.y + box.h / 2], dir: null, box };
  return { point: placePoint(element, def, port.x, port.y), dir: placeDir(element, port.dir), box };
}

/** How far a line runs straight out of a port before it may turn, and how far it keeps off a
 * symbol it goes round. */
const STUB = 20;
const CLEAR = 20;
const STEP: Record<Dir, Point> = { n: [0, -1], s: [0, 1], e: [1, 0], w: [-1, 0] };
const EPSILON = 0.01;

function same(a: number, b: number): boolean {
  return Math.abs(a - b) < EPSILON;
}

/** The path without repeated points and without corners that do not turn. */
export function simplified(path: Point[]): Point[] {
  const out: Point[] = [];
  for (const point of path) {
    const last = out[out.length - 1];
    if (last && same(last[0], point[0]) && same(last[1], point[1])) continue;
    if (out.length >= 2) {
      const [p, q] = [out[out.length - 2], last];
      if ((same(p[0], q[0]) && same(q[0], point[0])) || (same(p[1], q[1]) && same(q[1], point[1]))) out.pop();
    }
    out.push(point);
  }
  return out;
}

function heading(a: Point, b: Point): Dir | null {
  if (same(a[1], b[1])) return b[0] > a[0] ? "e" : "w";
  if (same(a[0], b[0])) return b[1] > a[1] ? "s" : "n";
  return null;
}

/** Whether the segment a-b runs through the inside of the box (along its outline is fine). */
export function crosses(a: Point, b: Point, box: Box): boolean {
  const left = box.x + 1, right = box.x + box.w - 1, top = box.y + 1, bottom = box.y + box.h - 1;
  if (right <= left || bottom <= top) return false;
  const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
  return x1 > left && x0 < right && y1 > top && y0 < bottom;
}

/** What a square path costs: leaving or entering a port the wrong way, doubling back or running
 * through a symbol are all but ruled out; then each bend counts, then the length. */
function cost(path: Point[], aDir: Dir | null, bDir: Dir | null, avoid: Box[]): number {
  let total = 0;
  let before: Dir | null = null;
  for (let index = 1; index < path.length; index += 1) {
    const [a, b] = [path[index - 1], path[index]];
    const dir = heading(a, b);
    if (dir === null) return Infinity;
    if (index === 1 && aDir && dir !== aDir) total += 10000;
    if (index === path.length - 1 && bDir && dir !== BACK[bDir]) total += 10000;
    if (before && dir === BACK[before]) total += 10000;
    if (before && dir !== before) total += 40;
    for (const box of avoid) if (crosses(a, b, box)) total += 2000;
    total += (Math.abs(b[0] - a[0]) + Math.abs(b[1] - a[1])) * 0.1;
    before = dir;
  }
  return total;
}

/** The corners of a line from its two ends: straight out of each port (`aDir`, `bDir`) for a
 * short stub, then square bends, as few as it can, round the symbols in `avoid` (the boxes of
 * its two ends) rather than through them; the corners between the ends sit on the grid. Of the
 * paths with up to four bends between the stubs, the cheapest (`cost`) wins. */
export function route(a: Point, aDir: Dir | null, b: Point, bDir: Dir | null, avoid: Box[] = [], grid = 10): Point[] {
  const unit = grid > 0 ? grid : 1;
  const down = (value: number) => Math.floor(value / unit) * unit, up = (value: number) => Math.ceil(value / unit) * unit;
  const stub = (point: Point, dir: Dir | null): Point => {
    if (!dir) return point;
    const [dx, dy] = STEP[dir];
    const reach = (value: number, step: number) => (step > 0 ? up(value + STUB) : step < 0 ? down(value - STUB) : value);
    return [reach(point[0], dx), reach(point[1], dy)];
  };
  const a2 = stub(a, aDir), b2 = stub(b, bDir);
  const xs = new Set([a2[0], b2[0], snap((a2[0] + b2[0]) / 2, grid)]);
  const ys = new Set([a2[1], b2[1], snap((a2[1] + b2[1]) / 2, grid)]);
  for (const box of avoid) {
    xs.add(down(box.x - CLEAR)).add(up(box.x + box.w + CLEAR));
    ys.add(down(box.y - CLEAR)).add(up(box.y + box.h + CLEAR));
  }
  const middles: Point[][] = [];
  for (const x of xs) middles.push([[x, a2[1]], [x, b2[1]]]);
  for (const y of ys) middles.push([[a2[0], y], [b2[0], y]]);
  for (const x of xs) for (const y of ys) middles.push([[x, a2[1]], [x, y], [b2[0], y]], [[a2[0], y], [x, y], [x, b2[1]]]);
  let best: Point[] = [a, b];
  let bestCost = Infinity;
  for (const middle of middles) {
    const path = simplified([a, a2, ...middle, b2, b]);
    const value = cost(path, aDir, bDir, avoid);
    if (value < bestCost - EPSILON) { best = path; bestCost = value; }
  }
  return best;
}

/** The path with its first end on the centre of a symbol (a line to no port) cut where it
 * leaves the symbol's drawing, so it meets the outline instead of running under the drawing. */
function cutAt(path: Point[], box: Box): Point[] {
  const inside = (p: Point) => p[0] > box.x && p[0] < box.x + box.w && p[1] > box.y && p[1] < box.y + box.h;
  let index = 0;
  while (index < path.length - 2 && inside(path[index + 1])) index += 1;
  const [p, q] = [path[index], path[index + 1]];
  if (!inside(p) || inside(q)) return path.slice(index);
  const dx = q[0] - p[0], dy = q[1] - p[1];
  let t = 1;
  if (dx > 0) t = Math.min(t, (box.x + box.w - p[0]) / dx);
  if (dx < 0) t = Math.min(t, (box.x - p[0]) / dx);
  if (dy > 0) t = Math.min(t, (box.y + box.h - p[1]) / dy);
  if (dy < 0) t = Math.min(t, (box.y - p[1]) / dy);
  return [[p[0] + dx * t, p[1] + dy * t], ...path.slice(index + 1)];
}

/** The middle of the side of a box that faces a point, and the way out of that side. */
function facing(box: Box, toward: Point): { point: Point; dir: Dir } {
  const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
  const dx = (toward[0] - cx) / Math.max(box.w, 1), dy = (toward[1] - cy) / Math.max(box.h, 1);
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? { point: [box.x + box.w, cy], dir: "e" } : { point: [box.x, cy], dir: "w" };
  return dy >= 0 ? { point: [cx, box.y + box.h], dir: "s" } : { point: [cx, box.y], dir: "n" };
}

/** Every corner of a line on the canvas: its ends on their ports and its own points between
 * (none: a square route between the ports, an end on no port at the side that faces the other
 * end). With its own points, an end on a symbol's centre is cut at the drawing's outline. */
export function linePath(line: LineElement, elements: Map<string, Element>, symbols: Map<string, SymbolDef>, grid = 10): Point[] {
  const start = line.start ? endpointOf(line.start, elements, symbols) : null;
  const end = line.end ? endpointOf(line.end, elements, symbols) : null;
  const points = line.points.map((point) => [point[0], point[1]] as Point);
  if (start && end && points.length === 0) {
    // An end on no port joins the middle of the side of its symbol that faces the other end.
    const a = start.dir ? start : facing(start.box, end.point), b = end.dir ? end : facing(end.box, start.point);
    return route(a.point, a.dir, b.point, b.dir, [start.box, end.box], grid);
  }
  let out = [...(start ? [start.point] : []), ...points, ...(end ? [end.point] : [])];
  if (out.length < 2) return out;
  if (start && !start.dir) out = cutAt(out, start.box);
  if (end && !end.dir) out = cutAt([...out].reverse(), end.box).reverse();
  return out;
}

/** Arrowheads by kind of line, in canvas units (they zoom with the drawing): length and half width. */
export const ARROWS: Record<LineElement["kind"], [number, number]> = { process: [13, 5], signal: [10, 4], utility: [11, 4.5] };
/** A straight run at least this long carries a small flow arrow at its middle (process lines). */
export const FLOW_RUN = 220;

export interface LineDrawing { stroke: Point[]; heads: Point[][]; flows: Array<{ at: Point; angle: number }> }

/** How a line's path is drawn: filled arrowheads with their tips on the ends (`arrow`), each
 * along its last stretch, the stroke cut short under them so it never pokes past the tip, and
 * flow arrows on the long straight runs of a process line that has a direction. */
export function lineDrawing(path: Point[], kind: LineElement["kind"], arrow: LineElement["arrow"]): LineDrawing {
  const [length, half] = ARROWS[kind] ?? ARROWS.process;
  const stroke = path.map((point) => [point[0], point[1]] as Point);
  const heads: Point[][] = [];
  const head = (tip: Point, from: Point, end: "start" | "end") => {
    const dx = tip[0] - from[0], dy = tip[1] - from[1], run = Math.hypot(dx, dy);
    if (run < 1) return;
    const ux = dx / run, uy = dy / run;
    const base: Point = [tip[0] - ux * length, tip[1] - uy * length];
    heads.push([tip, [base[0] - uy * half, base[1] + ux * half], [base[0] + uy * half, base[1] - ux * half]]);
    // The stroke stops a little inside the head, where the head is wider than the stroke (on a
    // stretch shorter than the head, at the stretch's start).
    const back = Math.min(length - 2, run);
    const cut: Point = [tip[0] - ux * back, tip[1] - uy * back];
    if (end === "end") stroke[stroke.length - 1] = cut; else stroke[0] = cut;
  };
  if (path.length >= 2) {
    if (arrow === "end" || arrow === "both") head(path[path.length - 1], path[path.length - 2], "end");
    if (arrow === "start" || arrow === "both") head(path[0], path[1], "start");
  }
  const flows: LineDrawing["flows"] = [];
  if (kind === "process" && (arrow === "end" || arrow === "start")) {
    for (let index = 1; index < path.length; index += 1) {
      const [a, b] = arrow === "end" ? [path[index - 1], path[index]] : [path[index], path[index - 1]];
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) < FLOW_RUN) continue;
      flows.push({ at: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], angle: (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI });
    }
  }
  return { stroke, heads, flows };
}

/** Where a line's label goes: over the middle of its longest level stretch, else beside the
 * middle of its longest upright one. */
export function labelSpot(path: Point[]): { at: Point; anchor: "middle" | "start" } | null {
  let best: [Point, Point] | null = null, upright: [Point, Point] | null = null;
  const run = (pair: [Point, Point] | null) => (pair ? Math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]) : -1);
  for (let index = 1; index < path.length; index += 1) {
    const pair: [Point, Point] = [path[index - 1], path[index]];
    if (Math.abs(pair[0][0] - pair[1][0]) < Math.abs(pair[0][1] - pair[1][1])) { if (run(pair) > run(upright)) upright = pair; } else if (run(pair) > run(best)) best = pair;
  }
  if (best) return { at: [(best[0][0] + best[1][0]) / 2, (best[0][1] + best[1][1]) / 2 - 7], anchor: "middle" };
  if (upright) return { at: [Math.max(upright[0][0], upright[1][0]) + 7, (upright[0][1] + upright[1][1]) / 2], anchor: "start" };
  return null;
}

export function snap(value: number, grid: number): number {
  return grid > 0 ? Math.round(value / grid) * grid : Math.round(value);
}

/** Colour of a line by what runs in it (`medium`): the suite's series colours, named once. */
export const MEDIA: Record<string, string> = {
  process: "var(--pc-text-2)",
  water: "var(--pc-series-1)",
  "cooling water": "var(--pc-series-1)",
  steam: "var(--pc-series-4)",
  gas: "var(--pc-series-3)",
  "fuel gas": "var(--pc-series-5)",
  fuel: "var(--pc-series-5)",
  oil: "var(--pc-series-6)",
  air: "var(--pc-series-2)",
  nitrogen: "var(--pc-series-7)",
  product: "var(--pc-series-8)",
};

export function mediumColor(medium: string): string | undefined {
  return MEDIA[medium.trim().toLowerCase()];
}

/** The part of a symbol's drawing that fills with its level (`pc-level`): the first rectangle
 * of that class, in the drawing's own units. */
export function levelBox(svg: string): { x: number; y: number; w: number; h: number } | null {
  const match = /<rect\b[^>]*\bclass="[^"]*\bpc-level\b[^"]*"[^>]*>/.exec(svg);
  if (!match) return null;
  const read = (name: string) => { const found = new RegExp(`\\b${name}="([-0-9.]+)"`).exec(match[0]); return found ? Number(found[1]) : NaN; };
  const box = { x: read("x"), y: read("y"), w: read("width"), h: read("height") };
  if (!Number.isFinite(box.w) || !Number.isFinite(box.h)) return null;
  return { x: Number.isFinite(box.x) ? box.x : 0, y: Number.isFinite(box.y) ? box.y : 0, w: box.w, h: box.h };
}

/** The vessel's outline (`class="pc-state"`) as a bare shape, to clip its liquid by: the level
 * fills the vessel's own shape (heads, cone, sphere), never a rectangle over it (owner,
 * 2026-10-27). Null when the drawing has no such outline. */
export function outlineOf(svg: string): string | null {
  const match = /<(path|rect|circle|ellipse|polygon)\b[^>]*\bclass="[^"]*\bpc-state\b[^"]*"[^>]*>/.exec(svg);
  if (!match) return null;
  const tag = match[0].replace(/\s(class|fill|stroke[-a-z]*)="[^"]*"/g, "");
  return tag.endsWith("/>") ? tag : `${tag.slice(0, -1)}/>`;
}

/** A fresh element id not used yet in the diagram: `p1`, `p2`... */
export function nextId(elements: Element[], prefix: string): string {
  const taken = new Set(elements.map((element) => element.id));
  for (let n = 1; ; n += 1) if (!taken.has(`${prefix}${n}`)) return `${prefix}${n}`;
}

/** Elements drawn elsewhere (from assets, by the assistant) put on `page` beside `kept`: an id
 * another page already uses gets a new one, and the lines follow their symbols' new ids. */
export function placedOnPage(elements: Element[], kept: Element[], page: string | undefined): Element[] {
  const taken = [...kept];
  const renamed = new Map<string, string>();
  for (const element of elements) {
    const id = taken.some((item) => item.id === element.id) ? nextId([...taken, ...elements], element.id.replace(/\d+$/, "") || "e") : element.id;
    renamed.set(element.id, id);
    taken.push({ ...element, id });
  }
  const end = (point: Endpoint | null | undefined) => (point ? { ...point, element: renamed.get(point.element) ?? point.element } : point);
  return elements.map((element) => {
    const moved = { ...element, id: renamed.get(element.id) ?? element.id, ...(page ? { page } : {}) };
    return moved.type === "line" ? { ...moved, start: end(moved.start), end: end(moved.end) } : moved;
  });
}

export type Corner = "nw" | "ne" | "sw" | "se";

/** A symbol resized by dragging one corner of its box by (dx, dy): the opposite corner stays,
 * and turned symbols resize as they are seen. The box keeps its proportions unless `free`; given
 * the symbol's drawing (`def`), it takes the drawing's own proportions, from the box the drawing
 * covers, so a box drawn out of shape comes back to it on the first drag. */
export function resized(element: SymbolElement, corner: Corner, dx: number, dy: number, free: boolean, grid: number, min = 16, def?: { w: number; h: number; stretch?: boolean } | null): SymbolElement {
  const own = !free && def && !def.stretch;
  const box = symbolBox(element, own ? def : null);
  const west = corner.includes("w"), north = corner.includes("n");
  let w = Math.max(min, box.w + (west ? -dx : dx));
  let h = Math.max(min, box.h + (north ? -dy : dy));
  if (own) {
    // The longer side snaps to the grid and the other follows it, so the ratio stays exact.
    const ratio = box.w / box.h;
    const scale = Math.max(w / box.w, h / box.h, min / Math.min(box.w, box.h));
    if (ratio >= 1) { w = Math.max(min, snap(box.w * scale, grid)); h = w / ratio; } else { h = Math.max(min, snap(box.h * scale, grid)); w = h * ratio; }
  } else {
    if (!free) {
      const scale = Math.max(w / box.w, h / box.h);
      w = Math.max(min, box.w * scale);
      h = Math.max(min, box.h * scale);
    }
    w = Math.max(min, snap(w, grid));
    h = Math.max(min, snap(h, grid));
  }
  const x = west ? box.x + box.w - w : box.x;
  const y = north ? box.y + box.h - h : box.y;
  const turned = element.rotate % 180 !== 0;
  const ew = turned ? h : w, eh = turned ? w : h;
  return { ...element, w: Math.round(ew), h: Math.round(eh), x: Math.round(x + w / 2 - ew / 2), y: Math.round(y + h / 2 - eh / 2) };
}

/** The corners a line keeps as its own points: its drawn path without the ends on symbols. */
export function ownPoints(line: LineElement, path: Point[]): Point[] {
  return path.slice(line.start ? 1 : 0, line.end ? path.length - 1 : path.length).map((point) => [point[0], point[1]] as Point);
}

/** Whether segment `index` of a line's path (from `path[index]` to `path[index + 1]`) can be
 * dragged across itself and leave every bend square: it is level or upright, neither of its
 * points is an end on a symbol, and the segments either side turn off it at a right angle. */
export function movableSegment(line: LineElement, path: Point[], index: number): boolean {
  if (index < 0 || index >= path.length - 1) return false;
  if ((line.start && index === 0) || (line.end && index + 1 === path.length - 1)) return false;
  const a = path[index], b = path[index + 1];
  const level = a[1] === b[1];
  if (!level && a[0] !== b[0]) return false;
  const along = (p: Point, q: Point) => (level ? p[1] === q[1] : p[0] === q[0]);
  if (index > 0 && along(path[index - 1], a)) return false;
  if (index + 2 < path.length && along(b, path[index + 2])) return false;
  return true;
}

/** The line's own points after segment `index` of its path moved across itself by `offset`
 * (a level segment up or down, an upright one left or right), so the bends stay square. */
export function segmentMoved(line: LineElement, path: Point[], index: number, offset: number, grid: number): Point[] {
  const a = path[index], b = path[index + 1];
  const level = a[1] === b[1];
  const moved = path.map((point, at) => {
    if (at !== index && at !== index + 1) return point;
    return level ? [point[0], snap(a[1] + offset, grid)] as Point : [snap(a[0] + offset, grid), point[1]] as Point;
  });
  return ownPoints(line, moved);
}
