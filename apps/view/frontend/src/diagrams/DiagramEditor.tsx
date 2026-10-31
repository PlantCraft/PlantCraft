/** The diagram editor: drag equipment from the library onto the canvas, join it by dragging from
 * one port to another, and bind what each element shows in the panel at the right. Everything
 * snaps to the grid; Ctrl+Z / Ctrl+Y undo and redo, Delete removes, Ctrl+C / Ctrl+V / Ctrl+D copy,
 * arrows nudge, R turns and F flips. Nothing is saved before Save. */
import { AssetSearch, PageTabs, SourcePicker, errorMessage as message, useAssistantPage, type AssetOption, type SourceRef } from "@plantcraft/ui";
import { ArrowLeft, ArrowRight, Boxes, Copy, FilePlus2, FlipHorizontal2, History, Sparkles, Hash, Minus, Plus, Redo2, RotateCw, Save, Search, Trash2, Type, Undo2, X, ZoomIn, ZoomOut, Maximize } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { Folder } from "../types";
import { ErrorBox } from "../ui";
import { diagramsApi, type DiagramStart } from "./api";
import { DiagramCanvas, type PortHit } from "./DiagramCanvas";
import { WINDOWS } from "./DiagramPage";
import { StartDialog, type StartMode } from "./StartDialog";
import { VersionsDialog } from "./VersionsDialog";
import {
  knownPage, LABEL_POSITIONS, linePath, MAX_PAGES, movableSegment, movedPage, nextId, onPage, pagesOf, placedOnPage, resized, withoutPage, withPage, segmentMoved, seriesTimes, shownAt, snap, symbolBox,
  type Corner, type Diagram, type Page, type Part, type DiagramData, type DiagramDraft, type Element, type Indicator, type Item, type LevelBinding, type Limits, type LineElement, type OnBinding, type Point, type StateBinding, type SymbolDef, type SymbolElement, type TextElement, type ValueElement,
} from "./model";

const HISTORY = 100;
const DRAG_TYPE = "application/x-plantcraft-symbol";
// Apps' results a symbol's colour can come from (app.toml [consumes] of the producers).
const RESULTS: Array<[string, string]> = [
  ["alarmcraft.alarm_state", "Alarm state (Alarms)"],
  ["linkcraft.loop_health", "Loop health (Analytics)"],
  ["linkcraft.signal_quality", "Signal quality (Analytics)"],
];
const MEDIA_CHOICES = ["", "water", "cooling water", "steam", "gas", "fuel gas", "oil", "air", "nitrogen", "product"];

type Drag =
  | { kind: "move"; start: Point; origin: Map<string, Point>; moved: boolean }
  | { kind: "line"; from: PortHit; to: Point }
  | { kind: "marquee"; start: Point; to: Point; add: boolean }
  | { kind: "pan"; start: [number, number]; scroll: [number, number] }
  | { kind: "resize"; id: string; corner: Corner; start: Point; origin: SymbolElement }
  | { kind: "segment"; id: string; index: number; start: Point; origin: LineElement; path: Point[] };

const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];

function useHistory(initial: DiagramDraft) {
  const [state, setState] = useState({ past: [] as DiagramDraft[], present: initial, future: [] as DiagramDraft[] });
  const set = useCallback((next: DiagramDraft | ((current: DiagramDraft) => DiagramDraft), record = true) => {
    setState((current) => {
      const value = typeof next === "function" ? next(current.present) : next;
      if (value === current.present) return current;
      if (!record) return { ...current, present: value };
      return { past: [...current.past, current.present].slice(-HISTORY), present: value, future: [] };
    });
  }, []);
  /** Records the state an uncommitted change (a drag) started from. */
  const commit = useCallback((from: DiagramDraft) => {
    setState((current) => (from === current.present ? current : { past: [...current.past, from].slice(-HISTORY), present: current.present, future: [] }));
  }, []);
  const undo = useCallback(() => setState((current) => current.past.length ? { past: current.past.slice(0, -1), present: current.past[current.past.length - 1], future: [current.present, ...current.future] } : current), []);
  const redo = useCallback(() => setState((current) => current.future.length ? { past: [...current.past, current.present], present: current.future[0], future: current.future.slice(1) } : current), []);
  return { draft: state.present, set, commit, undo, redo, canUndo: state.past.length > 0, canRedo: state.future.length > 0 };
}

/** Where an element sits (its top left), to move it. */
function originOf(element: Element): Point | null {
  if (element.type === "line") return null;
  return [element.x, element.y];
}

function moved(element: Element, dx: number, dy: number, origin: Point, grid: number): Element {
  if (element.type === "line") return element;
  return { ...element, x: snap(origin[0] + dx, grid), y: snap(origin[1] + dy, grid) };
}

/** A new symbol kept on the canvas, when it was dropped past an edge. */
function inside(element: SymbolElement, diagram: DiagramDraft): SymbolElement {
  const x = Math.min(Math.max(0, element.x), Math.max(0, diagram.width - element.w));
  const y = Math.min(Math.max(0, element.y), Math.max(0, diagram.height - element.h));
  return { ...element, x: snap(x, diagram.grid), y: snap(y, diagram.grid) };
}

function newSymbol(def: SymbolDef, elements: Element[], at: Point, grid: number): SymbolElement {
  // Library drawings are small; on a 1600 px canvas a pump reads well at about 90 px.
  const scale = Math.min(3, Math.max(1, 90 / Math.max(def.w, def.h)));
  const w = Math.round(def.w * scale), h = Math.round(def.h * scale);
  return {
    id: nextId(elements, def.id.split(".")[0].replace(/[^A-Za-z0-9_-]/g, "").slice(0, 12) || "s"), type: "symbol", symbol: def.id,
    x: snap(at[0] - w / 2, grid), y: snap(at[1] - h / 2, grid), w, h, rotate: 0, flip: false, label: "", label_position: "below", asset_id: null,
  };
}

/** A copy of the elements, with new ids, moved by `offset`; lines keep only the ends copied with them. */
function copies(picked: Element[], all: Element[], offset: number): Element[] {
  const ids = new Map<string, string>();
  const taken = [...all];
  for (const element of picked) {
    const id = nextId(taken, element.id.replace(/\d+$/, "") || "e");
    ids.set(element.id, id);
    taken.push({ ...element, id } as Element);
  }
  return picked.flatMap((element): Element[] => {
    const id = ids.get(element.id)!;
    if (element.type === "line") {
      const start = element.start && ids.has(element.start.element) ? { ...element.start, element: ids.get(element.start.element)! } : null;
      const end = element.end && ids.has(element.end.element) ? { ...element.end, element: ids.get(element.end.element)! } : null;
      if ((element.start && !start) || (element.end && !end)) return [];
      return [{ ...element, id, start, end, points: element.points.map(([x, y]) => [x + offset, y + offset] as Point) }];
    }
    return [{ ...element, id, x: element.x + offset, y: element.y + offset } as Element];
  });
}

/** One property: a label over its input; `group` for a picker that names its own input. */
function Field({ label, children, wide, group }: { label: string; children: ReactNode; wide?: boolean; group?: boolean }) {
  const className = `dg-field${wide ? " dg-field-wide" : ""}`;
  if (group) return <div className={className} role="group" aria-label={label}><span>{label}</span>{children}</div>;
  return <label className={className}><span>{label}</span>{children}</label>;
}

function num(text: string, fallback: number): number {
  const value = Number(text);
  return Number.isFinite(value) ? value : fallback;
}

function optionalNumber(text: string): number | null {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function LimitsFields({ value, onChange }: { value: Limits | undefined; onChange: (limits: Limits) => void }) {
  const limits = value ?? {};
  const keys: Array<[keyof Limits, string]> = [["low_alarm", "Low alarm"], ["low_warning", "Low warning"], ["high_warning", "High warning"], ["high_alarm", "High alarm"]];
  return <div className="dg-limits">
    {keys.map(([key, label]) => <Field key={key} label={t(label)}>
      <input type="number" value={limits[key] ?? ""} onChange={(event) => onChange({ ...limits, [key]: optionalNumber(event.target.value) })} />
    </Field>)}
  </div>;
}

function source(item: Item | undefined | null): SourceRef {
  return item ? { asset_id: item.asset_id ?? null, role: item.role ?? null, signal_id: item.signal_id ?? null } : {};
}

function itemOf(ref: SourceRef): Item | null {
  if (ref.signal_id) return { signal_id: ref.signal_id };
  if (ref.asset_id && ref.role) return { asset_id: ref.asset_id, role: ref.role };
  return null;
}

/** What a binding reads: a signal, or a role of an asset (the symbol's own first). */
function SignalField({ label, item, assets, onChange }: { label: string; item: Item | null | undefined; assets: AssetOption[]; onChange: (item: Item | null) => void }) {
  return <SourcePicker label={label} value={source(item)} assets={assets} onChange={(ref) => onChange(itemOf(ref))}
    searchSignals={(text) => api.signals(text)} />;
}

function StateFields({ element, assets, onChange }: { element: SymbolElement; assets: AssetOption[]; onChange: (state: StateBinding | null) => void }) {
  const current = element.state;
  const mode = !current ? "" : current.item.result ? current.item.result : "signal";
  const subject = current?.item.asset_id ?? element.asset_id ?? null;
  return <>
    <Field label={t("Colour from")}>
      <select value={mode} onChange={(event) => {
        const next = event.target.value;
        if (!next) onChange(null);
        else if (next === "signal") onChange({ item: element.asset_id ? { asset_id: element.asset_id, role: "pv" } : { signal_id: "" }, limits: {} });
        else onChange({ item: subject ? { asset_id: subject, result: next } : { asset_id: "", result: next } });
      }}>
        <option value="">{t("Nothing (stays neutral)")}</option>
        {RESULTS.map(([kind, label]) => <option key={kind} value={kind}>{t(label)}</option>)}
        <option value="signal">{t("Limits on a signal")}</option>
      </select>
    </Field>
    {current?.item.result && <Field label={t("About the asset")} wide group>
      <AssetSearch assets={assets} value={current.item.asset_id ?? ""} label={t("Asset")} onPick={(id) => onChange({ item: { asset_id: id, result: current.item.result } })} />
    </Field>}
    {current && !current.item.result && <>
      <SignalField label={t("Signal")} item={current.item} assets={assets} onChange={(item) => onChange(item ? { ...current, item } : { ...current, item: { signal_id: "" } })} />
      <LimitsFields value={current.limits} onChange={(limits) => onChange({ ...current, limits })} />
    </>}
  </>;
}

/** Pick an asset for a symbol and it shows that asset at once: its name, its state (a loop's
 * health, else its alarms), its level and whether it runs, from the roles it has. */
export function withAsset(element: SymbolElement, def: SymbolDef | undefined, asset: AssetOption): SymbolElement {
  const roles = asset.signals ?? {};
  const role = (...names: string[]) => names.find((name) => name in roles) ?? null;
  const out: SymbolElement = { ...element, asset_id: asset.id, label: element.label || asset.name };
  if (!element.state) out.state = { item: { asset_id: asset.id, result: asset.kind === "loop" ? "linkcraft.loop_health" : "alarmcraft.alarm_state" } };
  const level = role("level", "lvl", "pv");
  if (!element.level && def && /pc-level/.test(def.svg) && level) out.level = { item: { asset_id: asset.id, role: level }, min: 0, max: 100 };
  const running = role("running", "run", "status", "state", "speed", "flow");
  if (!element.running && def && /pc-run/.test(def.svg) && running) out.running = { item: { asset_id: asset.id, role: running }, above: 0.5 };
  return out;
}

function SymbolPanel({ element, def, assets, diagrams, onChange }: { element: SymbolElement; def?: SymbolDef; assets: AssetOption[]; diagrams: Array<{ id: string; name: string }>; onChange: (element: SymbolElement) => void }) {
  const set = (patch: Partial<SymbolElement>) => onChange({ ...element, ...patch });
  const hasLevel = def ? /pc-level/.test(def.svg) : false;
  const hasRun = def ? /pc-run/.test(def.svg) : false;
  const asset = assets.find((item) => item.id === element.asset_id);
  return <>
    <h3>{def?.title ?? element.symbol}</h3>
    <Field label={t("Asset it draws")} wide group>
      <AssetSearch assets={assets} value={element.asset_id ?? ""} label={t("Asset")} placeholder={t("Find an asset (P-101, TK-1...)")}
        onPick={(id) => { const found = assets.find((item) => item.id === id); onChange(found ? withAsset(element, def, found) : { ...element, asset_id: null }); }} />
    </Field>
    <Field label={t("Label")}><input value={element.label} maxLength={80} onChange={(event) => set({ label: event.target.value })} /></Field>
    <Field label={t("Label place")}>
      <select value={element.label_position} onChange={(event) => set({ label_position: event.target.value as SymbolElement["label_position"] })}>
        {LABEL_POSITIONS.map((place) => <option key={place} value={place}>{t(place[0].toUpperCase() + place.slice(1))}</option>)}
      </select>
    </Field>
    <div className="dg-row">
      <Field label={t("Width")}><input type="number" min={4} value={element.w} onChange={(event) => set({ w: Math.max(4, num(event.target.value, element.w)) })} /></Field>
      <Field label={t("Height")}><input type="number" min={4} value={element.h} onChange={(event) => set({ h: Math.max(4, num(event.target.value, element.h)) })} /></Field>
    </div>
    <h4>{t("What it shows")}</h4>
    <StateFields element={element} assets={assets} onChange={(state) => set({ state })} />
    {hasLevel && <>
      <Field label={t("Fill level from")}>
        <select value={element.level ? "on" : ""} onChange={(event) => set({ level: event.target.value ? { item: element.asset_id ? { asset_id: element.asset_id, role: asset?.signals && "level" in asset.signals ? "level" : "pv" } : { signal_id: "" }, min: 0, max: 100 } : null })}>
          <option value="">{t("Nothing")}</option><option value="on">{t("A signal")}</option>
        </select>
      </Field>
      {element.level && <>
        <SignalField label={t("Level signal")} item={element.level.item} assets={assets} onChange={(item) => set({ level: { ...(element.level as LevelBinding), item: item ?? { signal_id: "" } } })} />
        <div className="dg-row">
          <Field label={t("Empty at")}><input type="number" value={element.level.min} onChange={(event) => set({ level: { ...(element.level as LevelBinding), min: num(event.target.value, 0) } })} /></Field>
          <Field label={t("Full at")}><input type="number" value={element.level.max} onChange={(event) => set({ level: { ...(element.level as LevelBinding), max: num(event.target.value, 100) } })} /></Field>
        </div>
      </>}
    </>}
    {hasRun && <>
      <Field label={t("Running from")}>
        <select value={element.running ? "on" : ""} onChange={(event) => set({ running: event.target.value ? { item: element.asset_id ? { asset_id: element.asset_id, role: "pv" } : { signal_id: "" }, above: 0.5 } : null })}>
          <option value="">{t("Nothing")}</option><option value="on">{t("A signal above a value")}</option>
        </select>
      </Field>
      {element.running && <>
        <SignalField label={t("Running signal")} item={element.running.item} assets={assets} onChange={(item) => set({ running: { ...(element.running as OnBinding), item: item ?? { signal_id: "" } } })} />
        <Field label={t("Running above")}><input type="number" value={element.running.above} onChange={(event) => set({ running: { ...(element.running as OnBinding), above: num(event.target.value, 0.5) } })} /></Field>
      </>}
    </>}
    <LinkFields element={element} diagrams={diagrams} onChange={(link) => set({ link })} />
  </>;
}

/** The pages of the diagram being edited, for links to another page. */
const NO_PAGES: Page[] = [];
const PagesContext = createContext<Page[]>(NO_PAGES);

function LinkFields({ element, diagrams, onChange }: { element: Element; diagrams: Array<{ id: string; name: string }>; onChange: (link: Element["link"]) => void }) {
  const link = element.link;
  const pages = useContext(PagesContext);
  return <>
    <Field label={t("A click opens")}>
      <select value={link?.kind ?? ""} onChange={(event) => { const kind = event.target.value as NonNullable<Element["link"]>["kind"] | ""; onChange(kind ? { kind, target: kind === "trend" ? "" : link?.target ?? "" } : null); }}>
        <option value="">{element.type === "symbol" ? t("Its asset's page") : t("Nothing")}</option>
        {pages.length > 1 && <option value="page">{t("Another page")}</option>}
        <option value="area">{t("A part of this drawing (zoomed in)")}</option>
        <option value="diagram">{t("Another process display")}</option>
        <option value="dashboard">{t("A dashboard")}</option>
        <option value="asset">{t("An asset")}</option>
        <option value="trend">{t("A trend of its signals")}</option>
      </select>
    </Field>
    {link?.kind === "page" && <Field label={t("Page")}>
      <select value={link.target} onChange={(event) => onChange({ ...link, target: event.target.value })}>
        <option value="">{t("Choose…")}</option>
        {pages.filter((item) => item.id !== element.page).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </Field>}
    {link?.kind === "diagram" && <Field label={t("Process display")}>
      <select value={link.target} onChange={(event) => onChange({ ...link, target: event.target.value })}>
        <option value="">{t("Choose…")}</option>
        {diagrams.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </Field>}
    {link?.kind === "area" && <Field label={t("Part: x, y, width, height")}>
      <input value={link.target} placeholder="1600, 0, 1600, 900" onChange={(event) => onChange({ ...link, target: event.target.value })} />
    </Field>}
    {(link?.kind === "dashboard" || link?.kind === "asset") && <Field label={link.kind === "asset" ? t("Asset id") : t("Dashboard id")}>
      <input value={link.target} onChange={(event) => onChange({ ...link, target: event.target.value })} />
    </Field>}
  </>;
}

function ValuePanel({ element, assets, onChange }: { element: ValueElement; assets: AssetOption[]; onChange: (element: ValueElement) => void }) {
  const set = (patch: Partial<ValueElement>) => onChange({ ...element, ...patch });
  const indicator = element.indicator;
  const setIndicator = (patch: Partial<Indicator>) => indicator && set({ indicator: { ...indicator, ...patch } });
  return <>
    <h3>{t("Value")}</h3>
    <SignalField label={t("Signal")} item={element.item} assets={assets} onChange={(item) => set({ item: item ?? { signal_id: "" } })} />
    <Field label={t("Label")}><input value={element.label} placeholder={t("PV, SP, OUT...")} maxLength={80} onChange={(event) => set({ label: event.target.value })} /></Field>
    <div className="dg-row">
      <Field label={t("Decimals")}><input type="number" min={0} max={6} value={element.decimals ?? ""} placeholder={t("Auto")} onChange={(event) => set({ decimals: optionalNumber(event.target.value) })} /></Field>
      <Field label={t("Size")}><input type="number" min={8} max={72} value={element.size} onChange={(event) => set({ size: Math.min(72, Math.max(8, num(event.target.value, 14))) })} /></Field>
    </div>
    <label className="dg-check"><input type="checkbox" checked={element.show_label} onChange={(event) => set({ show_label: event.target.checked })} /> {t("Show the label")}</label>
    <label className="dg-check"><input type="checkbox" checked={element.show_unit} onChange={(event) => set({ show_unit: event.target.checked })} /> {t("Show the unit")}</label>
    <h4>{t("Colour by limits")}</h4>
    <LimitsFields value={element.limits} onChange={(limits) => set({ limits })} />
    <h4>{t("Analog indicator (ISA-101)")}</h4>
    <label className="dg-check"><input type="checkbox" checked={Boolean(element.indicator)} onChange={(event) => set({ indicator: event.target.checked ? { width: 120, setpoint: element.item.asset_id ? { asset_id: element.item.asset_id, role: "sp" } : null } : null })} /> {t("Show a bar with the normal range, the limits as LL, L, H, HH and the setpoint")}</label>
    {indicator && <>
      <div className="dg-row">
        <Field label={t("Scale from")}><input type="number" value={indicator.min ?? ""} placeholder={t("Signal's range")} onChange={(event) => setIndicator({ min: optionalNumber(event.target.value) })} /></Field>
        <Field label={t("Scale to")}><input type="number" value={indicator.max ?? ""} placeholder={t("Signal's range")} onChange={(event) => setIndicator({ max: optionalNumber(event.target.value) })} /></Field>
      </div>
      <div className="dg-row">
        <Field label={t("Normal from")}><input type="number" value={indicator.normal_low ?? ""} placeholder={t("Low warning")} onChange={(event) => setIndicator({ normal_low: optionalNumber(event.target.value) })} /></Field>
        <Field label={t("Normal to")}><input type="number" value={indicator.normal_high ?? ""} placeholder={t("High warning")} onChange={(event) => setIndicator({ normal_high: optionalNumber(event.target.value) })} /></Field>
      </div>
      <SignalField label={t("Setpoint")} item={indicator.setpoint} assets={assets} onChange={(setpoint) => setIndicator({ setpoint })} />
      <Field label={t("Width")}><input type="number" min={40} max={600} value={indicator.width} onChange={(event) => setIndicator({ width: Math.min(600, Math.max(40, num(event.target.value, 120))) })} /></Field>
    </>}
  </>;
}

function LinePanel({ element, assets, onChange }: { element: LineElement; assets: AssetOption[]; onChange: (element: LineElement) => void }) {
  const set = (patch: Partial<LineElement>) => onChange({ ...element, ...patch });
  return <>
    <h3>{t("Line")}</h3>
    <Field label={t("Kind")}>
      <select value={element.kind} onChange={(event) => set({ kind: event.target.value as LineElement["kind"] })}>
        <option value="process">{t("Process (piping)")}</option><option value="signal">{t("Signal")}</option><option value="utility">{t("Utility")}</option>
      </select>
    </Field>
    {element.kind === "process" && <Field label={t("What runs in it")}>
      <select value={element.medium} onChange={(event) => set({ medium: event.target.value })}>
        {MEDIA_CHOICES.map((medium) => <option key={medium} value={medium}>{medium ? t(medium[0].toUpperCase() + medium.slice(1)) : t("Process")}</option>)}
      </select>
    </Field>}
    <Field label={t("Arrow")}>
      <select value={element.arrow} onChange={(event) => set({ arrow: event.target.value as LineElement["arrow"] })}>
        <option value="end">{t("At the end")}</option><option value="start">{t("At the start")}</option><option value="both">{t("Both ends")}</option><option value="none">{t("None")}</option>
      </select>
    </Field>
    <Field label={t("Label")}><input value={element.label} maxLength={80} onChange={(event) => set({ label: event.target.value })} /></Field>
    <Field label={t("Flow shown from")}>
      <select value={element.flow ? "on" : ""} onChange={(event) => set({ flow: event.target.value ? { item: { signal_id: "" }, above: 0.5 } : null })}>
        <option value="">{t("Nothing")}</option><option value="on">{t("A signal above a value")}</option>
      </select>
    </Field>
    {element.flow && <>
      <SignalField label={t("Flow signal")} item={element.flow.item} assets={assets} onChange={(item) => set({ flow: { ...(element.flow as OnBinding), item: item ?? { signal_id: "" } } })} />
      <Field label={t("Flowing above")}><input type="number" value={element.flow.above} onChange={(event) => set({ flow: { ...(element.flow as OnBinding), above: num(event.target.value, 0.5) } })} /></Field>
    </>}
    {element.points.length > 0 && <button className="button button-secondary" onClick={() => set({ points: element.start && element.end ? [] : element.points })}>{t("Square the route again")}</button>}
  </>;
}

function TextPanel({ element, onChange }: { element: TextElement; onChange: (element: TextElement) => void }) {
  const set = (patch: Partial<TextElement>) => onChange({ ...element, ...patch });
  return <>
    <h3>{t("Text")}</h3>
    <Field label={t("Text")} wide><textarea rows={3} value={element.text} maxLength={400} onChange={(event) => set({ text: event.target.value })} /></Field>
    <div className="dg-row">
      <Field label={t("Size")}><input type="number" min={8} max={72} value={element.size} onChange={(event) => set({ size: Math.min(72, Math.max(8, num(event.target.value, 14))) })} /></Field>
      <Field label={t("Align")}>
        <select value={element.align} onChange={(event) => set({ align: event.target.value as TextElement["align"] })}>
          <option value="start">{t("Left")}</option><option value="middle">{t("Centre")}</option><option value="end">{t("Right")}</option>
        </select>
      </Field>
    </div>
    <label className="dg-check"><input type="checkbox" checked={element.bold} onChange={(event) => set({ bold: event.target.checked })} /> {t("Bold")}</label>
  </>;
}

function DiagramPanel({ draft, folders, onChange }: { draft: DiagramDraft; folders: Folder[]; onChange: (patch: Partial<DiagramDraft>) => void }) {
  return <>
    <h3>{t("Process display")}</h3>
    <Field label={t("Name")} wide><input value={draft.name} maxLength={80} onChange={(event) => onChange({ name: event.target.value })} /></Field>
    <Field label={t("Description")} wide><textarea rows={2} value={draft.description} maxLength={400} onChange={(event) => onChange({ description: event.target.value })} /></Field>
    <Field label={t("Folder")}>
      <select value={draft.folder_id} onChange={(event) => onChange({ folder_id: event.target.value })}>
        <option value="">{t("General")}</option>
        {folders.filter((folder) => folder.can_edit !== false).map((folder) => <option key={folder.folder_id} value={folder.folder_id}>{folder.name}</option>)}
      </select>
    </Field>
    <div className="dg-row">
      <Field label={t("Width")}><input type="number" min={200} max={8000} value={draft.width} onChange={(event) => onChange({ width: Math.min(8000, Math.max(200, num(event.target.value, draft.width))) })} /></Field>
      <Field label={t("Height")}><input type="number" min={200} max={8000} value={draft.height} onChange={(event) => onChange({ height: Math.min(8000, Math.max(200, num(event.target.value, draft.height))) })} /></Field>
    </div>
    <div className="dg-row">
      <Field label={t("Grid")}><input type="number" min={0} max={100} value={draft.grid} onChange={(event) => onChange({ grid: Math.min(100, Math.max(0, num(event.target.value, 10))) })} /></Field>
      <Field label={t("Refresh")}>
        <select value={draft.refresh_seconds} onChange={(event) => onChange({ refresh_seconds: Number(event.target.value) })}>
          {[0, 5, 15, 30, 60].map((seconds) => <option key={seconds} value={seconds}>{seconds ? t("every {n} s", { n: seconds }) : t("Off")}</option>)}
        </select>
      </Field>
    </div>
    <Field label={t("Window it opens with")}>
      <select value={draft.default_window} onChange={(event) => onChange({ default_window: event.target.value })}>
        {WINDOWS.map((window) => <option key={window} value={window}>{window}</option>)}
      </select>
    </Field>
    <PartsEditor draft={draft} onChange={onChange} />
    <p className="dg-hint">{t("Drag equipment from the library onto the canvas. Drag from a port (the small circles) to another to join them with a line. Click an element to bind what it shows.")}</p>
  </>;
}

/** The parts of a large drawing: each a tab of the viewer, after "Overview", that zooms to
 * its rectangle (x, y, width, height on the canvas). */
function PartsEditor({ draft, onChange }: { draft: DiagramDraft; onChange: (patch: Partial<DiagramDraft>) => void }) {
  const parts = draft.parts ?? [];
  const set = (index: number, patch: Partial<Part>) => onChange({ parts: parts.map((part, at) => (at === index ? { ...part, ...patch } : part)) });
  return <>
    <h3>{t("Parts")}</h3>
    <p className="dg-hint">{t("Tabs over the drawing: Overview (the whole drawing), then each part, zoomed in. A part is x, y, width, height on the canvas.")}</p>
    {parts.map((part, index) => <div className="dg-row" key={part.id}>
      <Field label={t("Name")}><input value={part.name} maxLength={60} onChange={(event) => set(index, { name: event.target.value })} /></Field>
      <Field label={t("Part")}><input value={part.area} maxLength={80} placeholder="0, 0, 1600, 900" onChange={(event) => set(index, { area: event.target.value })} /></Field>
      <button type="button" className="icon-button" aria-label={t("Remove the part {name}", { name: part.name })} onClick={() => onChange({ parts: parts.filter((_, at) => at !== index) })}><Trash2 size={14} /></button>
    </div>)}
    <button type="button" className="button button-secondary button-small" onClick={() => onChange({ parts: [...parts, { id: nextPartId(parts), name: t("Part {n}", { n: parts.length + 1 }), area: `0,0,${Math.round(draft.width / 2)},${Math.round(draft.height / 2)}` }] })}><Plus size={14} /> {t("Add a part")}</button>
  </>;
}

function nextPartId(parts: Part[]): string {
  for (let n = 1; ; n += 1) if (!parts.some((part) => part.id === `part${n}`)) return `part${n}`;
}

/** The library at the left: search, categories, each symbol drawn small; drag one onto the canvas or click it. */
function Palette({ library, onAdd }: { library: SymbolDef[]; onAdd: (def: SymbolDef) => void }) {
  const [q, setQ] = useState("");
  const words = q.trim().toLowerCase();
  const shown = library.filter((def) => !words || [def.title, def.id, def.category, ...(def.keywords ?? [])].some((text) => text.toLowerCase().includes(words)));
  const groups = new Map<string, SymbolDef[]>();
  for (const def of shown) groups.set(def.category, [...(groups.get(def.category) ?? []), def]);
  return <aside className="dg-palette" aria-label={t("Symbol library")}>
    <label className="tc-find"><Search size={14} aria-hidden /><input type="search" aria-label={t("Find a symbol")} placeholder={t("Pump, tank, valve...")} value={q} onChange={(event) => setQ(event.target.value)} /></label>
    {library.length === 0 && <p className="dg-hint">{t("The symbol library is empty.")}</p>}
    {[...groups.entries()].map(([category, defs]) => <details key={category} open={Boolean(words) || groups.size <= 4 || category === [...groups.keys()][0]}>
      <summary>{category} <small>{defs.length}</small></summary>
      <div className="dg-palette-grid">
        {defs.map((def) => <button key={def.id} type="button" className="dg-palette-item" title={def.title} draggable
          onDragStart={(event) => { event.dataTransfer.setData(DRAG_TYPE, def.id); event.dataTransfer.effectAllowed = "copy"; }}
          onClick={() => onAdd(def)}>
          <svg viewBox={`-4 -4 ${def.w + 8} ${def.h + 8}`} className="dg-drawing" aria-hidden dangerouslySetInnerHTML={{ __html: def.svg }} />
          <span>{def.title}</span>
        </button>)}
      </div>
    </details>)}
  </aside>;
}

export function DiagramEditor({ diagramId, initial, baseUpdatedAt, symbols, library, onSaved, onCancel }: {
  diagramId: string | null; initial: DiagramDraft; baseUpdatedAt: string | null;
  symbols: Map<string, SymbolDef>; library: SymbolDef[];
  onSaved: (diagram: Diagram) => void; onCancel: () => void;
}) {
  const { draft, set, commit, undo, redo, canUndo, canRedo } = useHistory(initial);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drag, setDrag] = useState<Drag | null>(null);
  const [zoom, setZoom] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [diagrams, setDiagrams] = useState<Array<{ id: string; name: string }>>([]);
  const [preview, setPreview] = useState<DiagramData | null>(null);
  const [starting, setStarting] = useState<StartMode | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [showVersions, setShowVersions] = useState(false);
  const [page, setPage] = useState(() => knownPage(initial, new URLSearchParams(globalThis.location.search).get("page")));
  const pages = pagesOf(draft);
  const current = knownPage(draft, page);
  const visible = useMemo(() => onPage(draft, current), [draft, current]);
  const svg = useRef<SVGSVGElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const clipboard = useRef<Element[]>([]);
  const dragStart = useRef<DiagramDraft | null>(null);
  const base = useRef(baseUpdatedAt);
  const dirty = draft !== initial;

  useEffect(() => {
    api.assets(null).then((found) => setAssets(found)).catch(() => setAssets([]));
    api.folders().then(setFolders).catch(() => setFolders([]));
    diagramsApi.list().then((found) => setDiagrams(found.filter((item) => item.diagram_id !== diagramId).map((item) => ({ id: item.diagram_id, name: item.name })))).catch(() => setDiagrams([]));
  }, [diagramId]);

  // Fit the canvas to the stage at first.
  const fit = useCallback(() => {
    const box = stage.current?.getBoundingClientRect();
    if (!box) return;
    setZoom(Math.max(0.1, Math.min((box.width - 24) / draft.width, (box.height - 24) / draft.height)));
  }, [draft.width, draft.height]);
  useEffect(() => { if (zoom === 0) fit(); }, [zoom, fit]);

  // The values of what is bound, read as the editor, a moment after the bindings change.
  const bindingKey = useMemo(() => JSON.stringify(draft.elements.map((element) => element.type === "symbol" ? [element.id, element.state, element.level, element.running] : element.type === "value" ? [element.id, element.item, element.limits, element.indicator?.setpoint] : element.type === "line" ? [element.id, element.flow] : null)), [draft.elements]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      diagramsApi.preview({ ...draft, elements: finishedAll(draft.elements) }, "15m").then(setPreview).catch(() => setPreview(null));
    }, 600);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bindingKey]);
  const times = useMemo(() => (preview ? seriesTimes(preview) : {}), [preview]);
  const shows = useMemo(() => shownAt(draft.elements, preview, times, null), [draft.elements, preview, times]);

  useAssistantPage({ place: t("View › Process › Editing {name}", { name: draft.name }), page: "dashcraft:diagram-editor",
    facts: { elements: draft.elements.length, symbols: draft.elements.filter((element) => element.type === "symbol").length } });

  const toCanvas = useCallback((clientX: number, clientY: number): Point => {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix) return [0, 0];
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return [point.x, point.y];
  }, []);

  const update = useCallback((element: Element) => set((current) => ({ ...current, elements: current.elements.map((item) => item.id === element.id ? element : item) })), [set]);
  const add = useCallback((elements: Element[]) => {
    const placed = draft.pages?.length ? elements.map((element) => ({ ...element, page: current })) : elements;
    set((now) => ({ ...now, elements: [...now.elements, ...placed] }));
    setSelected(new Set(placed.map((element) => element.id)));
  }, [set, draft.pages, current]);

  const removeSelected = useCallback(() => {
    if (!selected.size) return;
    set((current) => ({
      ...current,
      elements: current.elements.filter((element) => !selected.has(element.id) && !(element.type === "line" && ((element.start && selected.has(element.start.element)) || (element.end && selected.has(element.end.element))))),
    }));
    setSelected(new Set());
  }, [selected, set]);

  const transformSelected = useCallback((change: (element: SymbolElement) => SymbolElement) => {
    set((current) => ({ ...current, elements: current.elements.map((element) => element.type === "symbol" && selected.has(element.id) ? change(element) : element) }));
  }, [selected, set]);

  const nudge = useCallback((dx: number, dy: number) => {
    set((current) => ({ ...current, elements: current.elements.map((element) => selected.has(element.id) && element.type !== "line" ? { ...element, x: element.x + dx, y: element.y + dy } : element) }));
  }, [selected, set]);

  const centre = useCallback((): Point => {
    const box = stage.current?.getBoundingClientRect();
    return box ? toCanvas(box.left + box.width / 2, box.top + box.height / 2) : [draft.width / 2, draft.height / 2];
  }, [toCanvas, draft.width, draft.height]);

  const addValue = useCallback(() => {
    const [x, y] = centre();
    const symbol = draft.elements.find((element): element is SymbolElement => element.type === "symbol" && selected.has(element.id));
    const at: Point = symbol ? [symbol.x + symbol.w + 8, symbol.y] : [x, y];
    add([{ id: nextId(draft.elements, "v"), type: "value", x: snap(at[0], draft.grid), y: snap(at[1], draft.grid), item: symbol?.asset_id ? { asset_id: symbol.asset_id, role: "pv" } : { signal_id: "" }, label: symbol?.asset_id ? "PV" : "", show_label: true, show_unit: true, decimals: null, size: 18, limits: {} }]);
  }, [add, centre, draft.elements, draft.grid, selected]);

  const addText = useCallback(() => {
    const [x, y] = centre();
    add([{ id: nextId(draft.elements, "t"), type: "text", x: snap(x, draft.grid), y: snap(y, draft.grid), text: t("Text"), size: 16, align: "start", bold: false }]);
  }, [add, centre, draft.elements, draft.grid]);

  // Keys, while the focus is not in a field of the panel.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable]"))) return;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "z") { event.preventDefault(); if (event.shiftKey) redo(); else undo(); return; }
      if (mod && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
      if (mod && event.key.toLowerCase() === "a") { event.preventDefault(); setSelected(new Set(visible.elements.map((element) => element.id))); return; }
      if (mod && event.key.toLowerCase() === "c") { clipboard.current = draft.elements.filter((element) => selected.has(element.id)); return; }
      if (mod && event.key.toLowerCase() === "v" && clipboard.current.length) { event.preventDefault(); add(copies(clipboard.current, draft.elements, draft.grid * 2 || 20)); return; }
      if (mod && event.key.toLowerCase() === "d") { event.preventDefault(); add(copies(draft.elements.filter((element) => selected.has(element.id)), draft.elements, draft.grid * 2 || 20)); return; }
      if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); removeSelected(); return; }
      if (event.key === "Escape") { setSelected(new Set()); setDrag(null); return; }
      const step = event.shiftKey ? (draft.grid || 10) * 5 : draft.grid || 1;
      const arrows: Record<string, Point> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (arrows[event.key] && selected.size) { event.preventDefault(); nudge(...arrows[event.key]); return; }
      if (event.key.toLowerCase() === "r" && selected.size) transformSelected((element) => ({ ...element, rotate: ((element.rotate + 90) % 360) as SymbolElement["rotate"] }));
      if (event.key.toLowerCase() === "f" && selected.size) transformSelected((element) => ({ ...element, flip: !element.flip }));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [add, draft.elements, visible.elements, draft.grid, nudge, redo, removeSelected, selected, transformSelected, undo]);

  // Leaving with unsaved changes asks first.
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function onElementDown(event: ReactPointerEvent, element: Element) {
    if (event.button !== 0) return;
    event.stopPropagation();
    const picked = new Set(selected);
    if (event.shiftKey) { if (picked.has(element.id)) picked.delete(element.id); else picked.add(element.id); }
    else if (!picked.has(element.id)) { picked.clear(); picked.add(element.id); }
    setSelected(picked);
    const origin = new Map<string, Point>();
    for (const item of draft.elements) { const at = picked.has(item.id) ? originOf(item) : null; if (at) origin.set(item.id, at); }
    dragStart.current = draft;
    svg.current?.setPointerCapture?.(event.pointerId);
    setDrag({ kind: "move", start: toCanvas(event.clientX, event.clientY), origin, moved: false });
  }

  function onPortDown(event: ReactPointerEvent, hit: PortHit) {
    if (event.button !== 0) return;
    svg.current?.setPointerCapture?.(event.pointerId);
    setDrag({ kind: "line", from: hit, to: hit.point });
  }

  function onCanvasDown(event: ReactPointerEvent) {
    if (event.button === 1 || (event.button === 0 && event.altKey)) {
      const box = stage.current;
      if (box) setDrag({ kind: "pan", start: [event.clientX, event.clientY], scroll: [box.scrollLeft, box.scrollTop] });
      return;
    }
    if (event.button !== 0) return;
    svg.current?.setPointerCapture?.(event.pointerId);
    const at = toCanvas(event.clientX, event.clientY);
    if (!event.shiftKey) setSelected(new Set());
    setDrag({ kind: "marquee", start: at, to: at, add: event.shiftKey });
  }

  function onPointerMove(event: ReactPointerEvent) {
    if (!drag) return;
    if (drag.kind === "pan") {
      const box = stage.current;
      if (box) { box.scrollLeft = drag.scroll[0] - (event.clientX - drag.start[0]); box.scrollTop = drag.scroll[1] - (event.clientY - drag.start[1]); }
      return;
    }
    const at = toCanvas(event.clientX, event.clientY);
    if (drag.kind === "move") {
      const dx = at[0] - drag.start[0], dy = at[1] - drag.start[1];
      if (!drag.moved && Math.hypot(dx, dy) < 3) return;
      if (!drag.moved) setDrag({ ...drag, moved: true });
      set((current) => ({ ...current, elements: current.elements.map((element) => { const origin = drag.origin.get(element.id); return origin ? moved(element, dx, dy, origin, current.grid) : element; }) }), false);
    } else if (drag.kind === "resize") {
      const changed = resized(drag.origin, drag.corner, at[0] - drag.start[0], at[1] - drag.start[1], event.shiftKey, draft.grid, 16, symbols.get(drag.origin.symbol));
      set((current) => ({ ...current, elements: current.elements.map((element) => element.id === drag.id ? changed : element) }), false);
    } else if (drag.kind === "segment") {
      const [a, b] = [drag.path[drag.index], drag.path[drag.index + 1]];
      const offset = a[1] === b[1] ? at[1] - drag.start[1] : at[0] - drag.start[0];
      const points = segmentMoved(drag.origin, drag.path, drag.index, offset, draft.grid);
      set((current) => ({ ...current, elements: current.elements.map((element) => element.id === drag.id ? { ...drag.origin, points } : element) }), false);
    } else if (drag.kind === "line") setDrag({ ...drag, to: at });
    else if (drag.kind === "marquee") setDrag({ ...drag, to: at });
  }

  function onPointerUp(event: ReactPointerEvent) {
    if (!drag) return;
    if ((drag.kind === "move" && drag.moved) || drag.kind === "resize" || drag.kind === "segment") { if (dragStart.current) commit(dragStart.current); }
    if (drag.kind === "line") {
      const target = (document.elementFromPoint(event.clientX, event.clientY) as globalThis.Element | null);
      const portEl = target?.closest(".dg-port");
      const symbolEl = target?.closest("[data-element]");
      const to = portEl ? portEl.parentElement?.getAttribute("data-port-of") : null;
      const portId = portEl?.getAttribute("data-port") ?? "";
      const element = to ?? symbolEl?.getAttribute("data-element") ?? null;
      const end = element && element !== drag.from.element && draft.elements.find((item) => item.id === element && item.type === "symbol") ? { element, port: portEl ? portId : "" } : null;
      const distance = Math.hypot(drag.to[0] - drag.from.point[0], drag.to[1] - drag.from.point[1]);
      if (end || distance > 12) {
        const line: LineElement = {
          id: nextId(draft.elements, "l"), type: "line", kind: portKind(drag.from), medium: "", start: { element: drag.from.element, port: drag.from.port },
          end, points: end ? [] : [[snap(drag.to[0], draft.grid), snap(drag.to[1], draft.grid)]], arrow: "end", label: "",
        };
        add([line]);
      }
    }
    if (drag.kind === "marquee") {
      const [x0, y0] = drag.start, [x1, y1] = drag.to;
      const left = Math.min(x0, x1), right = Math.max(x0, x1), top = Math.min(y0, y1), bottom = Math.max(y0, y1);
      if (right - left > 4 || bottom - top > 4) {
        const inside = visible.elements.filter((element) => {
          if (element.type === "line") return false;
          const box = element.type === "symbol" ? symbolBox(element, symbols.get(element.symbol)) : { x: element.x, y: element.y, w: 10, h: 10 };
          return box.x >= left && box.x + box.w <= right && box.y >= top && box.y + box.h <= bottom;
        });
        setSelected((current) => new Set([...(drag.add ? current : []), ...inside.map((element) => element.id)]));
      }
    }
    setDrag(null);
    dragStart.current = null;
  }

  function onHandleDown(event: ReactPointerEvent, start: (at: Point) => Drag) {
    if (event.button !== 0) return;
    event.stopPropagation();
    dragStart.current = draft;
    svg.current?.setPointerCapture?.(event.pointerId);
    setDrag(start(toCanvas(event.clientX, event.clientY)));
  }

  function portKind(hit: PortHit): LineElement["kind"] {
    const element = draft.elements.find((item) => item.id === hit.element);
    const def = element?.type === "symbol" ? symbols.get(element.symbol) : undefined;
    const kind = def?.ports.find((port) => port.id === hit.port)?.kind;
    return kind === "signal" ? "signal" : kind === "utility" ? "utility" : "process";
  }

  function onDrop(event: DragEvent) {
    const symbolId = event.dataTransfer.getData(DRAG_TYPE);
    const def = symbols.get(symbolId);
    if (!def) return;
    event.preventDefault();
    add([inside(newSymbol(def, draft.elements, toCanvas(event.clientX, event.clientY), draft.grid), draft)]);
  }

  function drawn(start: DiagramStart) {
    set((now) => {
      const nowPages = pagesOf(now);
      const others = now.pages?.length ? now.elements.filter((element) => (element.page || nowPages[0].id) !== current) : [];
      const elements = [...others, ...placedOnPage(start.diagram.elements, others, now.pages?.length ? current : undefined)];
      return { ...now, name: now.name.trim() && now.name !== t("New process display") ? now.name : start.diagram.name, width: Math.max(now.pages?.length ? now.width : 0, start.diagram.width), height: Math.max(now.pages?.length ? now.height : 0, start.diagram.height), elements };
    });
    setSelected(new Set());
    setNotes(start.notes);
    setStarting(null);
    setZoom(0);
  }

  function broughtBack(diagram: DiagramDraft, version: number) {
    set((current) => ({ ...current, ...diagram, folder_id: current.folder_id }));
    setSelected(new Set());
    setNotes([t("Version {version} is on the canvas. Save to keep it as the process display; Undo takes it away.", { version })]);
    setShowVersions(false);
    setZoom(0);
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      const body = { ...draft, name: draft.name.trim() || t("New process display"), elements: finishedAll(draft.elements) };
      const saved = diagramId ? await diagramsApi.save(diagramId, body, base.current) : await diagramsApi.create(body);
      base.current = saved.updated_at;
      onSaved(saved);
    } catch (err) { setError(message(err)); } finally { setSaving(false); }
  }

  const single = selected.size === 1 ? draft.elements.find((element) => selected.has(element.id)) ?? null : null;
  const hasSymbols = draft.elements.some((element) => element.type === "symbol" && selected.has(element.id));
  const handles = useMemo(() => {
    if (!single || drag?.kind === "move") return null;
    const size = 9 / (zoom || 1);
    if (single.type === "symbol") {
      const box = symbolBox(single, symbols.get(single.symbol));
      return <g className="dg-handles">{CORNERS.map((corner) => {
        const x = corner.includes("w") ? box.x - 4 : box.x + box.w + 4, y = corner.includes("n") ? box.y - 4 : box.y + box.h + 4;
        return <rect key={corner} className={`dg-handle dg-handle-${corner}`} data-handle={corner} x={x - size / 2} y={y - size / 2} width={size} height={size}
          onPointerDown={(event) => onHandleDown(event, (at) => ({ kind: "resize", id: single.id, corner, start: at, origin: single }))}><title>{t("Drag to resize; Shift frees the proportions")}</title></rect>;
      })}</g>;
    }
    if (single.type === "line") {
      const path = linePath(single, new Map(draft.elements.map((element) => [element.id, element])), symbols, draft.grid);
      return <g className="dg-handles">{path.slice(0, -1).map((a, index) => {
        if (!movableSegment(single, path, index)) return null;
        const b = path[index + 1];
        if (a[0] !== b[0] && a[1] !== b[1]) return null;
        const level = a[1] === b[1];
        return <rect key={index} className={`dg-handle dg-handle-${level ? "ns" : "ew"}`} data-segment={index} x={(a[0] + b[0]) / 2 - size / 2} y={(a[1] + b[1]) / 2 - size / 2} width={size} height={size}
          onPointerDown={(event) => onHandleDown(event, (at) => ({ kind: "segment", id: single.id, index, start: at, origin: single, path }))}><title>{t("Drag to move this stretch of the line")}</title></rect>;
      })}</g>;
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [single, drag?.kind, zoom, draft.elements, symbols]);
  const overlay = drag?.kind === "line" ? <path className="dg-draft-line" d={`M${drag.from.point[0]} ${drag.from.point[1]} L${drag.to[0]} ${drag.to[1]}`} />
    : drag?.kind === "marquee" ? <rect className="dg-marquee" x={Math.min(drag.start[0], drag.to[0])} y={Math.min(drag.start[1], drag.to[1])} width={Math.abs(drag.to[0] - drag.start[0])} height={Math.abs(drag.to[1] - drag.start[1])} />
      : handles;
  const incomplete = draft.elements.length - draft.elements.filter(complete).length;

  return <PagesContext.Provider value={pages.length > 1 ? pages : NO_PAGES}><div className="dg-editor">
    <div className="dg-toolbar" role="toolbar" aria-label={t("Process display editor")}>
      <strong className="dg-toolbar-name">{draft.name || t("New process display")}</strong>
      <button className="icon-button" onClick={undo} disabled={!canUndo} title={t("Undo (Ctrl+Z)")} aria-label={t("Undo")}><Undo2 size={16} /></button>
      <button className="icon-button" onClick={redo} disabled={!canRedo} title={t("Redo (Ctrl+Y)")} aria-label={t("Redo")}><Redo2 size={16} /></button>
      <span className="dg-sep" />
      <button className="button button-secondary" onClick={addValue} title={t("A value of a signal, beside the selected symbol")}><Hash size={15} /> {t("Value")}</button>
      <button className="button button-secondary" onClick={addText}><Type size={15} /> {t("Text")}</button>
      <button className="button button-secondary" onClick={() => setStarting("assets")} aria-label={t("From assets")} title={t("Lay out a unit from its equipment, loops and relations")}><Boxes size={15} /> <span className="dg-wide">{t("From assets")}</span></button>
      <button className="button button-secondary" onClick={() => setStarting("assistant")} aria-label={t("Draft with assistant")} title={t("Describe the process display; the assistant drafts it")}><Sparkles size={15} /> <span className="dg-wide">{t("Draft with assistant")}</span></button>
      <span className="dg-sep" />
      <button className="icon-button" disabled={!hasSymbols} onClick={() => transformSelected((element) => ({ ...element, rotate: ((element.rotate + 90) % 360) as SymbolElement["rotate"] }))} title={t("Turn (R)")} aria-label={t("Turn")}><RotateCw size={16} /></button>
      <button className="icon-button" disabled={!hasSymbols} onClick={() => transformSelected((element) => ({ ...element, flip: !element.flip }))} title={t("Flip (F)")} aria-label={t("Flip")}><FlipHorizontal2 size={16} /></button>
      <button className="icon-button" disabled={!selected.size} onClick={() => add(copies(draft.elements.filter((element) => selected.has(element.id)), draft.elements, draft.grid * 2 || 20))} title={t("Duplicate (Ctrl+D)")} aria-label={t("Duplicate")}><Copy size={16} /></button>
      <button className="icon-button" disabled={!selected.size} onClick={removeSelected} title={t("Delete (Del)")} aria-label={t("Delete")}><Trash2 size={16} /></button>
      <span className="dg-sep" />
      <button className="icon-button" onClick={() => setZoom((value) => Math.max(0.1, value / 1.25))} aria-label={t("Zoom out")}><ZoomOut size={16} /></button>
      <span className="dg-zoom">{Math.round(zoom * 100)}%</span>
      <button className="icon-button" onClick={() => setZoom((value) => Math.min(4, value * 1.25))} aria-label={t("Zoom in")}><ZoomIn size={16} /></button>
      <button className="icon-button" onClick={fit} title={t("Fit")} aria-label={t("Fit")}><Maximize size={16} /></button>
      <span className="dg-grow" />
      {incomplete > 0 && <small className="dg-hint" title={t("Values and lines with nothing picked are left out when saving")}>{t("{n} unfinished", { n: incomplete })}</small>}
      {diagramId && <button className="icon-button" onClick={() => setShowVersions(true)} title={t("Versions")} aria-label={t("Versions")}><History size={16} /></button>}
      <button className="button button-secondary" onClick={onCancel}><X size={15} /> {t("Cancel")}</button>
      <button className="button button-primary" onClick={() => void save()} disabled={saving}><Save size={15} /> {saving ? t("Saving…") : t("Save")}</button>
    </div>
    {error && <ErrorBox text={error} />}
    {notes.length > 0 && <div className="dg-notes" role="status">
      <ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul>
      <button className="icon-button" onClick={() => setNotes([])} aria-label={t("Close the notes")}><X size={14} /></button>
    </div>}
    <div className="tc-pages dg-pages">
      {pages.length > 1 && <PageTabs label={t("Pages of {name}", { name: draft.name })} tabs={pages.map((item) => ({ to: item.id, label: item.name, active: item.id === current }))}
        href={(to) => `${globalThis.location.pathname}?page=${encodeURIComponent(to)}`} navigate={(to) => { setPage(to); setSelected(new Set()); setZoom(0); }} />}
      <div className="tc-page-tools">
        {pages.length > 1 && <>
          <label className="tc-page-name"><span className="sr-only">{t("Page name")}</span>
            <input aria-label={t("Page name")} maxLength={60} value={pages.find((item) => item.id === current)?.name ?? ""}
              onChange={(event) => set((now) => ({ ...now, pages: pagesOf(now).map((item) => (item.id === current ? { ...item, name: event.target.value } : item)) }))}
              onBlur={(event) => { if (!event.target.value.trim()) set((now) => ({ ...now, pages: pagesOf(now).map((item, index) => (item.id === current ? { ...item, name: t("Page {n}", { n: index + 1 }) } : item)) })); }} /></label>
          <button className="icon-button" aria-label={t("Move page earlier")} title={t("Move page earlier")} onClick={() => set((now) => movedPage(now, current, -1))}><ArrowLeft size={14} /></button>
          <button className="icon-button" aria-label={t("Move page later")} title={t("Move page later")} onClick={() => set((now) => movedPage(now, current, 1))}><ArrowRight size={14} /></button>
          <button className="icon-button danger" aria-label={t("Remove page")} title={t("Remove page and what is drawn on it")}
            onClick={() => { const left = pages.filter((item) => item.id !== current); set((now) => withoutPage(now, current)); setPage(left[0]?.id ?? ""); setSelected(new Set()); }}><Trash2 size={14} /></button>
        </>}
        <button className="button button-secondary" disabled={pages.length >= MAX_PAGES} title={t("Another unit or area of the plant, on its own page")}
          onClick={() => { const [next, id] = withPage(draft, t("Page {n}", { n: pages.length + 1 })); set(next); setPage(id); setSelected(new Set()); }}><FilePlus2 size={15} /> {t("Add page")}</button>
      </div>
    </div>
    {showVersions && diagramId && <VersionsDialog diagramId={diagramId} onPick={broughtBack} onClose={() => setShowVersions(false)} />}
    {starting && <StartDialog mode={starting} assets={assets} replaces={draft.elements.length > 0} onDrawn={drawn} onClose={() => setStarting(null)} />}
    <div className="dg-workspace">
      <Palette library={library} onAdd={(def) => add([newSymbol(def, draft.elements, centre(), draft.grid)])} />
      <div className="dg-editor-stage" ref={stage} onDragOver={(event) => { if (event.dataTransfer.types.includes(DRAG_TYPE)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; } }} onDrop={onDrop}
        onWheel={(event) => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); setZoom((value) => Math.min(4, Math.max(0.1, value * (event.deltaY < 0 ? 1.1 : 1 / 1.1)))); } }}>
        <div style={{ width: draft.width * (zoom || 1), height: draft.height * (zoom || 1) }} onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
          <DiagramCanvas svgRef={svg} diagram={visible} symbols={symbols} shows={shows} selected={selected} showPorts
            onElementDown={onElementDown} onPortDown={onPortDown} onCanvasDown={onCanvasDown} overlay={overlay} className="dg-editing" />
        </div>
      </div>
      <aside className="dg-inspector" aria-label={t("Properties")}>
        {!single && selected.size > 1 && <><h3>{t("{n} elements", { n: selected.size })}</h3><p className="dg-hint">{t("Drag to move them together; arrows nudge, R turns, F flips, Delete removes.")}</p></>}
        {!single && selected.size <= 1 && <DiagramPanel draft={draft} folders={folders} onChange={(patch) => set((current) => ({ ...current, ...patch }))} />}
        {single?.type === "symbol" && <SymbolPanel element={single} def={symbols.get(single.symbol)} assets={assets} diagrams={diagrams} onChange={update} />}
        {single?.type === "value" && <ValuePanel element={single} assets={assets} onChange={update} />}
        {single?.type === "line" && <LinePanel element={single} assets={assets} onChange={update} />}
        {single?.type === "text" && <TextPanel element={single} onChange={update} />}
        {single && <BindingState element={single} data={preview} />}
        {single?.type !== "line" && single && <div className="dg-row">
          <Field label="X"><input type="number" value={Math.round(single.x)} onChange={(event) => update({ ...single, x: num(event.target.value, single.x) })} /></Field>
          <Field label="Y"><input type="number" value={Math.round(single.y)} onChange={(event) => update({ ...single, y: num(event.target.value, single.y) })} /></Field>
        </div>}
        {single?.type === "symbol" && <div className="dg-row">
          <button className="button button-secondary" onClick={() => update({ ...single, w: Math.round(single.w * 0.8), h: Math.round(single.h * 0.8) })}><Minus size={14} /> {t("Smaller")}</button>
          <button className="button button-secondary" onClick={() => update({ ...single, w: Math.round(single.w * 1.25), h: Math.round(single.h * 1.25) })}><Plus size={14} /> {t("Larger")}</button>
        </div>}
      </aside>
    </div>
  </div></PagesContext.Provider>;
}

/** The values the editor reads for the selected element, or why they cannot be read. */
function BindingState({ element, data }: { element: Element; data: DiagramData | null }) {
  const rows = (data?.bindings ?? []).filter((row) => row.element === element.id);
  if (!rows.length) return null;
  return <ul className="dg-binding-state">
    {rows.map((row) => <li key={row.slot} data-state={row.error ? "unknown" : row.state}>
      <b>{t(row.slot[0].toUpperCase() + row.slot.slice(1))}</b> {row.error ? row.error : `${row.label}: ${row.value ?? "—"} ${row.unit ?? ""}`}
    </li>)}
  </ul>;
}

const named = (item: Item | null | undefined) => Boolean(item && (item.signal_id || (item.asset_id && (item.role || item.result))));

/** An element whose bindings all name something. */
function complete(element: Element): boolean {
  return finished(element) === element;
}

/** The element as it is saved: a binding with nothing picked is left out, and so is a value
 * with no signal or an empty text. */
export function finished(element: Element): Element | null {
  if (element.type === "value") return named(element.item) ? element : null;
  if (element.type === "text") return element.text.trim() ? element : null;
  if (element.type === "line") return !element.flow || named(element.flow.item) ? element : { ...element, flow: null };
  const drop = (["state", "level", "running"] as const).filter((slot) => element[slot] && !named(element[slot]!.item));
  if (!drop.length) return element;
  const out = { ...element };
  for (const slot of drop) out[slot] = null;
  return out;
}

function finishedAll(elements: Element[]): Element[] {
  return elements.map(finished).filter((element): element is Element => element !== null);
}
