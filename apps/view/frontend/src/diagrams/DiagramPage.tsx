/** One diagram: live values and colours, a time bar to play the window back, full screen (a
 * kiosk: the canvas only), public links, and the editor (`DiagramEditor`) for those who may
 * change it. `/diagrams/new` opens the editor on an empty canvas. The same viewer serves a public
 * link (`PublicDiagramPage`, `share/diagram/<token>`), read-only and without sign-in. */
import { PageTabs, displayTimeZone, errorMessage as message, isoOf, localOf, useAssistantPage } from "@plantcraft/ui";
import { ArrowLeft, Clock, Globe2, Maximize2, Minimize2, Pause, Pencil, Play, Radio, Scan, ZoomIn, ZoomOut } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { t } from "../i18n";
import { ShareDialog } from "../Dialogs";
import { windowLabel } from "../model";
import { navigate } from "../nav";
import type { Me, PublicDiagram, TrendPeriod } from "../types";
import { ErrorBox, Heading, Loading } from "../ui";
import { diagramsApi, publicDiagramsApi } from "./api";
import { AssetPanel } from "./AssetPanel";
import { DiagramCanvas, type ViewBox } from "./DiagramCanvas";
import { areaOf, bindingsOf, emptyDiagram, knownPage, MEDIA, onPage, pagesOf, seriesTimes, shownAt, type Diagram, type DiagramData, type DiagramDraft, type Element, type SymbolDef } from "./model";
import { clampView, fullView, zoomAt, zoomLevel } from "./zoom";
import "./diagrams.css";

const DiagramEditor = lazy(() => import("./DiagramEditor").then((m) => ({ default: m.DiagramEditor })));
const TrendDialog = lazy(() => import("../TrendsPage").then((m) => ({ default: m.TrendDialog })));
export const WINDOWS = ["15m", "1h", "8h", "24h", "7d"];
const SPEEDS = [1, 10, 60, 600];

let symbolCache: Promise<SymbolDef[]> | null = null;
/** The library, read once per page load. */
export function useSymbols(): [Map<string, SymbolDef>, SymbolDef[], string] {
  const [list, setList] = useState<SymbolDef[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    symbolCache ??= diagramsApi.symbols();
    symbolCache.then(setList).catch((err) => { symbolCache = null; setError(message(err)); });
  }, []);
  return [useMemo(() => new Map(list.map((item) => [item.id, item])), [list]), list, error];
}

function clock(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: displayTimeZone() });
}

/** Playing the window back: kept by the viewer, so the time bar may move (into full screen's
 * time popover) without stopping it. */
function usePlayback(data: DiagramData | null, cursor: number | null, onCursor: (at: number | null) => void) {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(60);
  const start = data ? Date.parse(data.range.start) : 0;
  const stop = data ? Date.parse(data.range.end) : 0;
  useEffect(() => {
    if (!playing || cursor === null) return undefined;
    const timer = window_setInterval(() => {
      const next = (cursor ?? start) + speed * 250;
      if (next >= stop) { setPlaying(false); onCursor(stop); } else onCursor(next);
    }, 250);
    return () => clearInterval(timer);
  }, [playing, cursor, speed, start, stop, onCursor]);
  return { playing, setPlaying, speed, setSpeed, start, stop };
}

type Playback = ReturnType<typeof usePlayback>;

/** The time bar: Live, or a cursor over the window read, played at 1x to 600x. */
function TimeBar({ data, window, onWindow, cursor, onCursor, end, onEnd, playback }: {
  data: DiagramData | null; window: string; onWindow: (window: string) => void;
  cursor: number | null; onCursor: (at: number | null) => void; end: string | null; onEnd: (end: string | null) => void;
  playback: Playback;
}) {
  const { playing, setPlaying, speed, setSpeed, start, stop } = playback;
  const live = cursor === null && end === null;
  const goLive = () => { setPlaying(false); onEnd(null); onCursor(null); };
  return <div className="dg-timebar" role="group" aria-label={t("Time")}>
    <div className="dg-timebar-row">
      <span className="dg-timebar-label">{t("Period")}</span>
      <div className="segmented" role="radiogroup" aria-label={t("Period")}>
        {WINDOWS.map((item) => <button key={item} type="button" role="radio" aria-checked={window === item} className={window === item ? "on" : ""}
          onClick={() => onWindow(item)} title={t("The values of the last {span}", { span: windowLabel(item) })}>{windowLabel(item)}</button>)}
      </div>
      <span className="dg-timebar-label">{t("ending")}</span>
      <div className="segmented" role="radiogroup" aria-label={t("Ending")}>
        <button type="button" role="radio" aria-checked={end === null} className={end === null ? "on" : ""} onClick={() => { setPlaying(false); onCursor(null); onEnd(null); }}>{t("Now")}</button>
        <button type="button" role="radio" aria-checked={end !== null} className={end !== null ? "on" : ""}
          onClick={() => { if (end === null) { setPlaying(false); onCursor(null); onEnd(new Date(Date.now() - 86_400_000).toISOString()); } }}>{t("At a date")}</button>
      </div>
      {end !== null && <input type="datetime-local" aria-label={t("Period ends")} value={localOf(end)}
        onChange={(event) => { setPlaying(false); onCursor(null); onEnd(event.target.value ? isoOf(event.target.value) || null : null); }} />}
    </div>
    <div className="dg-timebar-row">
      <button className="icon-button" aria-label={playing ? t("Pause") : t("Play the period")} title={playing ? t("Pause") : t("Play the period")} disabled={!data}
        onClick={() => { if (playing) { setPlaying(false); return; } if (cursor === null || cursor >= stop) onCursor(start); setPlaying(true); }}>
        {playing ? <Pause size={16} /> : <Play size={16} />}
      </button>
      <label className="dg-speed" title={t("How fast the period plays: 60× shows one minute of the plant per second")}>
        <span className="sr-only">{t("Speed")}</span>
        <select aria-label={t("Speed")} value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
          {SPEEDS.map((item) => <option key={item} value={item}>{t("{n}× speed", { n: item })}</option>)}
        </select>
      </label>
      <input type="range" aria-label={t("Instant shown")} min={start} max={stop} step={1000} value={cursor ?? stop} disabled={!data}
        onChange={(event) => { setPlaying(false); onCursor(Number(event.target.value)); }} />
      <time className={live ? "dg-live" : ""}>{live ? t("Now") : clock(cursor ?? stop)}</time>
      <button className={`button ${live ? "button-primary" : "button-secondary"}`} onClick={goLive} aria-pressed={live} title={t("Show the values now, refreshed on their own")}>
        <Radio size={15} /> {t("Live")}
      </button>
    </div>
  </div>;
}

/** Full screen's time: one button in the top strip saying what is shown
 * (Live and the period, or the instant played back); the time bar opens under it on a click
 * (stays until clicked again or elsewhere) or while the pointer rests on it. */
function TimePopover({ summary, live, children }: { summary: string; live: boolean; children: ReactNode }) {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pinned) return undefined;
    const outside = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) setPinned(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [pinned]);
  const open = pinned || hover;
  return <div ref={box} className="dg-full-time" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
    <button type="button" className={`button button-secondary${live ? " dg-full-live" : ""}`} aria-expanded={open} aria-haspopup="dialog"
      title={t("Period, playback and live")} onClick={() => setPinned((was) => !was)}>
      {live ? <Radio size={15} /> : <Clock size={15} />} {summary}
    </button>
    {open && <div className="dg-full-time-panel" role="dialog" aria-label={t("Time")}>{children}</div>}
  </div>;
}

// setInterval of the browser (not the time bar's `window` prop, a string).
const window_setInterval = (handler: () => void, ms: number) => globalThis.setInterval(handler, ms);

/** Which media and states the diagram uses, named under it. */
function Legend({ diagram }: { diagram: DiagramDraft }) {
  const media = [...new Set(diagram.elements.filter((element) => element.type === "line" && element.kind === "process" && element.medium).map((element) => (element as { medium: string }).medium.toLowerCase()))].filter((medium) => MEDIA[medium]);
  const kinds = new Set(diagram.elements.filter((element) => element.type === "line").map((element) => (element as { kind: string }).kind));
  return <div className="dg-legend" aria-label={t("Legend")}>
    <span><i className="dg-swatch" style={{ background: "var(--pc-good-soft)", borderColor: "var(--pc-good-border)" }} /> {t("OK")}</span>
    <span><i className="dg-swatch" style={{ background: "var(--pc-attention-soft)", borderColor: "var(--pc-attention-border)" }} /> {t("Warning")}</span>
    <span><i className="dg-swatch" style={{ background: "var(--pc-problem-soft)", borderColor: "var(--pc-problem-border)" }} /> {t("Critical")}</span>
    <span><i className="dg-swatch" style={{ background: "var(--pc-inactive-soft)", borderColor: "var(--pc-inactive-border)" }} /> {t("Unknown")}</span>
    {media.map((medium) => <span key={medium} style={{ color: MEDIA[medium] }}><i /> <span style={{ color: "var(--pc-text-2)" }}>{medium}</span></span>)}
    {kinds.has("signal") && <span><i style={{ background: "repeating-linear-gradient(90deg, var(--pc-text-3) 0 6px, transparent 6px 10px)" }} /> {t("Signal")}</span>}
    {kinds.has("utility") && <span><i style={{ background: "repeating-linear-gradient(90deg, var(--pc-text-2) 0 2px, transparent 2px 6px)" }} /> {t("Utility")}</span>}
  </div>;
}

/** What a click on an element opens: another display or a dashboard (its link), a trend of its
 * signals over the display (a value, or a "trend" link), or the panel of the asset it draws
 * (never away from the display only to come back). */
export type Opened = { kind: "go"; to: string } | { kind: "trend"; signals: string[] } | { kind: "asset"; id: string };
export function openOf(element: Element, data: DiagramData | null, from?: { id: string; page?: string }): Opened | null {
  const link = element.link;
  if (link?.kind === "diagram" && link.target) return { kind: "go", to: `/diagrams/${encodeURIComponent(link.target)}${backQuery(from)}` };
  if (link?.kind === "dashboard" && link.target) return { kind: "go", to: `/d/${encodeURIComponent(link.target)}` };
  if (link?.kind === "asset" && link.target) return { kind: "asset", id: link.target };
  const signals = [...new Set((data?.bindings ?? []).filter((row) => row.element === element.id && row.signal).map((row) => row.signal as string))];
  if (link?.kind === "trend" || (!link && element.type === "value")) return signals.length ? { kind: "trend", signals } : null;
  if (element.type === "symbol" && element.asset_id) return { kind: "asset", id: element.asset_id };
  return null;
}

/** The address part that lets the display opened by a link lead back here (`?from=`, and the page). */
export function backQuery(from?: { id: string; page?: string }): string {
  if (!from?.id) return "";
  const params = new URLSearchParams({ from: from.id });
  if (from.page) params.set("from_page", from.page);
  return `?${params.toString()}`;
}

/** Where "Back" leads: the display (and its page) whose link opened this one. */
export function backOf(search: string): { to: string; id: string } | null {
  const params = new URLSearchParams(search);
  const id = params.get("from");
  if (!id) return null;
  const page = params.get("from_page");
  return { id, to: `/diagrams/${encodeURIComponent(id)}${page ? `?page=${encodeURIComponent(page)}` : ""}` };
}

type Shown = DiagramDraft & { diagram_id: string; can_edit?: boolean };

/** The canvas as the viewer shows it: the whole drawing, or a part of it to look at closely.
 *The wheel or a double click zooms about the pointer, a drag moves a zoomed
 * drawing, the buttons zoom about the middle or fit the whole; a drag never opens what it started
 * on. */
function ZoomStage({ width, height, reset, goTo, onView, children }: { width: number; height: number; reset: string; goTo?: { area: ViewBox | null; at: number }; onView?: (view: ViewBox | null) => void; children: (view: ViewBox | null, svgRef: RefObject<SVGSVGElement | null>, show: (area: ViewBox) => void) => ReactNode }) {
  const [view, setView] = useState<ViewBox | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ x: number; y: number; view: ViewBox; inverse: DOMMatrix; moved: boolean } | null>(null);
  const dragged = useRef(false);
  useEffect(() => { setView(null); }, [reset, width, height]);
  useEffect(() => { onView?.(view); }, [view, onView]);
  const canvasPoint = useCallback((clientX: number, clientY: number): [number, number] | null => {
    const matrix = svgRef.current?.getScreenCTM();
    if (!matrix) return null;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return [point.x, point.y];
  }, []);
  const zoom = useCallback((factor: number, at?: [number, number] | null) => {
    setView((current) => {
      const now = current ?? fullView(width, height);
      const [px, py] = at ?? [now.x + now.w / 2, now.y + now.h / 2];
      const next = zoomAt(now, factor, px, py, width, height);
      return next.w >= width ? null : next;
    });
  }, [width, height]);
  useEffect(() => {
    const box = stage.current;
    if (!box) return undefined;
    const wheel = (event: WheelEvent) => {
      // Out of a whole drawing the wheel scrolls the page, as anywhere else.
      if (event.deltaY > 0 && !view) return;
      const at = canvasPoint(event.clientX, event.clientY);
      if (!at) return;
      event.preventDefault();
      zoom(Math.exp(-event.deltaY * 0.0015), at);
    };
    box.addEventListener("wheel", wheel, { passive: false });
    return () => box.removeEventListener("wheel", wheel);
  }, [view, zoom, canvasPoint]);
  const level = view ? zoomLevel(view, width) : 1;
  // The part asked for, at the canvas's proportions, centred on it.
  const show = useCallback((area: ViewBox) => {
    const w = Math.max(area.w, (area.h / height) * width);
    const next = clampView({ x: area.x + area.w / 2 - w / 2, y: area.y + area.h / 2 - ((w / width) * height) / 2, w, h: (w / width) * height }, width, height);
    setView(next.w >= width ? null : next);
  }, [width, height]);
  useEffect(() => { if (goTo) { if (goTo.area) show(goTo.area); else setView(null); } }, [goTo, show]);
  return <div ref={stage} className={`dg-zoom-stage${view ? " dg-zoomed" : ""}`}
    onPointerDown={(event) => {
      const matrix = svgRef.current?.getScreenCTM();
      if (event.button !== 0 || !view || !matrix) return;
      drag.current = { x: event.clientX, y: event.clientY, view, inverse: matrix.inverse(), moved: false };
    }}
    onPointerMove={(event) => {
      const start = drag.current;
      if (!start) return;
      if (!start.moved) {
        if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return;
        start.moved = true;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      const from = new DOMPoint(start.x, start.y).matrixTransform(start.inverse);
      const to = new DOMPoint(event.clientX, event.clientY).matrixTransform(start.inverse);
      setView(clampView({ ...start.view, x: start.view.x - (to.x - from.x), y: start.view.y - (to.y - from.y) }, width, height));
    }}
    onPointerUp={() => { dragged.current = Boolean(drag.current?.moved); drag.current = null; }}
    onPointerCancel={() => { drag.current = null; }}
    onClickCapture={(event) => { if (dragged.current) { dragged.current = false; event.stopPropagation(); event.preventDefault(); } }}
    onDoubleClick={(event) => zoom(2, canvasPoint(event.clientX, event.clientY))}>
    {children(view, svgRef, show)}
    <div className="dg-zoom" onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
      <button type="button" className="icon-button" title={t("Zoom out")} aria-label={t("Zoom out")} disabled={!view} onClick={() => zoom(0.5)}><ZoomOut size={16} /></button>
      <span className="dg-zoom-level" aria-live="polite">{Math.round(level * 100)} %</span>
      <button type="button" className="icon-button" title={t("Zoom in")} aria-label={t("Zoom in")} disabled={level >= 8} onClick={() => zoom(2)}><ZoomIn size={16} /></button>
      <button type="button" className="icon-button" title={t("Show the whole drawing")} aria-label={t("Show the whole drawing")} disabled={!view} onClick={() => setView(null)}><Scan size={16} /></button>
    </div>
  </div>;
}

/** The viewer; with `token`, a public link's: data read through the link, no links to follow,
 * no editing, sharing or assistant. */
function Viewer({ diagram, symbols, me, onEdit, token }: { diagram: Shown; symbols: Map<string, SymbolDef>; me?: Me; onEdit?: () => void; token?: string }) {
  const isPublic = Boolean(token);
  const [window, setWindow] = useState(diagram.default_window || "1h");
  const [end, setEnd] = useState<string | null>(null);
  const [data, setData] = useState<DiagramData | null>(null);
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState<number | null>(null);
  // Full screen is the browser's own, the stage alone with its trend and
  // asset panel inside; `?screen=1` (a kiosk opened by address, no click to ask the browser
  // with) and a browser that refuses fill the window instead.
  const stage = useRef<HTMLDivElement>(null);
  const [kiosk, setKiosk] = useState(() => new URLSearchParams(globalThis.location.search).get("screen") === "1");
  const [screen, setScreen] = useState(false);
  const full = kiosk || screen;
  useEffect(() => {
    const changed = () => setScreen(Boolean(stage.current) && document.fullscreenElement === stage.current);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  const enterFull = () => { const box = stage.current; if (!box?.requestFullscreen) { setKiosk(true); return; } box.requestFullscreen().catch(() => setKiosk(true)); };
  const leaveFull = () => { setKiosk(false); if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined); };
  const [trend, setTrend] = useState<{ title: string; signals: string[] } | null>(null);
  const [asset, setAsset] = useState<{ id: string; name: string; element: string } | null>(null);
  const [sharing, setSharing] = useState(false);
  // Opened from another display's link: a way back to it (and to the page it was on).
  const back = useMemo(() => (isPublic ? null : backOf(globalThis.location.search)), [diagram.diagram_id, isPublic]);
  const [backName, setBackName] = useState("");
  useEffect(() => {
    setBackName("");
    if (back) diagramsApi.get(back.id).then((found) => setBackName(found.name)).catch(() => setBackName(""));
  }, [back]);
  const [page, setPageState] = useState(() => knownPage(diagram, new URLSearchParams(globalThis.location.search).get("page")));
  const pages = pagesOf(diagram);
  const setPage = useCallback((next: string) => {
    setPageState(next);
    const params = new URLSearchParams(globalThis.location.search);
    if (next && next !== pages[0].id) params.set("page", next); else params.delete("page");
    const search = params.toString();
    globalThis.history.replaceState(globalThis.history.state, "", `${globalThis.location.pathname}${search ? `?${search}` : ""}`);
  }, [pages]);
  const shown = useMemo(() => onPage(diagram, page), [diagram, page]);
  // A plant on one page has parts: tabs "Overview" (the whole drawing, the
  // way back from any zoom) and one per part. The tab of the part in view is the active one.
  const parts = useMemo(() => (pages.length > 1 ? [] : (diagram.parts ?? []).flatMap((part) => { const box = areaOf(part.area); return box ? [{ ...part, box }] : []; })), [diagram.parts, pages.length]);
  const [goTo, setGoTo] = useState<{ area: ViewBox | null; at: number } | undefined>(() => {
    const wanted = new URLSearchParams(globalThis.location.search).get("part");
    const box = wanted ? areaOf((diagram.parts ?? []).find((part) => part.id === wanted)?.area ?? "") : null;
    return box ? { area: box, at: 0 } : undefined;
  });
  const [seen, setSeen] = useState<ViewBox | null>(null);
  const inView = !seen ? "" : parts.find(({ box }) => {
    const cx = seen.x + seen.w / 2, cy = seen.y + seen.h / 2;
    return cx >= box.x && cx <= box.x + box.w && cy >= box.y && cy <= box.y + box.h && seen.w <= box.w * 1.2;
  })?.id ?? null;
  const openPart = useCallback((to: string) => {
    const box = parts.find((part) => part.id === to)?.box ?? null;
    setGoTo({ area: box, at: Date.now() });
    const params = new URLSearchParams(globalThis.location.search);
    if (box) params.set("part", to); else params.delete("part");
    const search = params.toString();
    globalThis.history.replaceState(globalThis.history.state, "", `${globalThis.location.pathname}${search ? `?${search}` : ""}`);
  }, [parts]);
  const pageTabs = pages.length > 1 && <PageTabs label={t("Pages of {name}", { name: diagram.name })} tabs={pages.map((item) => ({ to: item.id, label: item.name, active: item.id === page }))}
    href={(to) => `${globalThis.location.pathname}?page=${encodeURIComponent(to)}`} navigate={setPage} />;
  const partTabs = parts.length > 0 && <PageTabs label={t("Parts of {name}", { name: diagram.name })}
    tabs={[{ to: "", label: t("Overview"), active: inView === "" }, ...parts.map((part) => ({ to: part.id, label: part.name, active: inView === part.id }))]}
    href={(to) => `${globalThis.location.pathname}${to ? `?part=${encodeURIComponent(to)}` : ""}`} navigate={openPart} />;
  const live = cursor === null && end === null;
  const playback = usePlayback(data, cursor, setCursor);
  const request = useRef(0);
  const read = useCallback(() => {
    const mine = ++request.current;
    const only = pages.length > 1 ? page : null;
    (token ? publicDiagramsApi.data(token, window, end, only) : diagramsApi.data(diagram.diagram_id, window, end, only)).then((answer) => { if (mine === request.current) { setData(answer); setError(""); } })
      .catch((err) => { if (mine === request.current) setError(message(err)); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diagram.diagram_id, token, window, end, page]);
  useEffect(() => { read(); }, [read]);
  useEffect(() => {
    if (!live || !diagram.refresh_seconds) return undefined;
    const timer = globalThis.setInterval(read, diagram.refresh_seconds * 1000);
    return () => clearInterval(timer);
  }, [live, diagram.refresh_seconds, read]);
  useEffect(() => {
    // Esc closes the asset panel first (it listens itself), then leaves the kiosk.
    const leave = (event: KeyboardEvent) => { if (event.key === "Escape" && !asset) setKiosk(false); };
    globalThis.addEventListener("keydown", leave);
    return () => globalThis.removeEventListener("keydown", leave);
  }, [asset]);
  const times = useMemo(() => (data ? seriesTimes(data) : {}), [data]);
  const shows = useMemo(() => shownAt(shown.elements, data, times, cursor), [shown.elements, data, times, cursor]);
  const problems = (data?.bindings ?? []).filter((row) => row.error);
  const alarms = (data?.bindings ?? []).filter((row) => row.state === "alarm").length;
  useAssistantPage(isPublic ? null : {
    place: t("View › Process › {name}", { name: diagram.name }), page: "dashcraft:diagram",
    subject: `diagram:${diagram.diagram_id}`, title: diagram.name,
    facts: { elements: diagram.elements.length, bindings: bindingsOf(diagram.elements).length, alarms, problems: problems.length },
    view: { window, end: end ?? "now", values: (data?.bindings ?? []).slice(0, 60).map((row) => `${row.label}: ${row.error ? row.error : `${row.value ?? "—"} ${row.unit ?? ""} (${row.state})`}`) },
  });
  const editable = Boolean(diagram.can_edit && me?.can_edit && !isPublic);
  // The trend opens on the display's window: the last hour live, the very period played back.
  const trendPeriod: TrendPeriod = !live && data ? { mode: "fixed", window, start: data.range.start, end: data.range.end } : { mode: "relative", window };
  const timeBar = <TimeBar data={data} window={window} onWindow={(next) => { setWindow(next); setCursor(null); }} cursor={cursor} onCursor={setCursor} end={end} onEnd={setEnd} playback={playback} />;
  return <>
    <Heading title={diagram.name} assistant={!isPublic}
      actions={<>
        {back && <button className="button button-secondary" onClick={() => navigate(back.to)} title={t("Back to the process display this one was opened from")}><ArrowLeft size={16} /> {backName || t("Back")}</button>}
        <button className="button button-secondary" onClick={enterFull} title={t("The process display alone, live, for a control room screen. Esc leaves it.")}><Maximize2 size={16} /> {t("Full screen")}</button>
        {editable && me?.public_links && <button className="button button-secondary" onClick={() => setSharing(true)}><Globe2 size={16} /> {t("Share")}</button>}
        {editable && <button className="button button-primary" onClick={onEdit}><Pencil size={16} /> {t("Edit")}</button>}
      </>} />
    {error && <ErrorBox text={error} />}
    {pageTabs && !full && <div className="tc-pages dg-pages">{pageTabs}</div>}
    {partTabs && !full && <div className="tc-pages dg-pages">{partTabs}</div>}
    {!full && timeBar}
    <div ref={stage} className={`dg-stage${full ? " dg-stage-full" : ""}`}>
      {/* Full screen keeps a strip of its own on top: the name, the tabs,
          the time and the way out, never over the drawing. */}
      {full && <div className="dg-full-bar">
        <span className="dg-full-name" title={diagram.name}>{diagram.name}</span>
        <div className="dg-full-tabs">{pageTabs || partTabs}</div>
        <TimePopover live={live} summary={live ? t("Live · {span}", { span: windowLabel(window) }) : clock(cursor ?? Date.parse(data?.range.end ?? ""))}>{timeBar}</TimePopover>
        {!isPublic && <button className="icon-button" aria-label={t("Leave full screen")} title={t("Leave full screen")} onClick={leaveFull}><Minimize2 size={16} /></button>}
      </div>}
      <div className="dg-stage-body">
      <ZoomStage width={shown.width} height={shown.height} reset={`${diagram.diagram_id}/${page}`} goTo={goTo} onView={setSeen}>
        {(view, svgRef, show) => <DiagramCanvas diagram={shown} symbols={symbols} shows={shows} view={view} svgRef={svgRef} onOpen={(element) => {
          if (element.link?.kind === "page") { if (pages.some((item) => item.id === element.link?.target)) setPage(element.link.target); return; }
          if (element.link?.kind === "area") { const area = areaOf(element.link.target); if (area) show(area); return; }
          if (isPublic) return;
          const opened = openOf(element, data, { id: diagram.diagram_id, page: pages.length > 1 && page !== pages[0].id ? page : undefined });
          const named = "label" in element ? element.label : "";
          if (opened?.kind === "go") navigate(opened.to);
          else if (opened?.kind === "trend") setTrend({ title: (data?.bindings ?? []).find((row) => row.element === element.id && row.label)?.label || named || t("Trend"), signals: opened.signals });
          else if (opened?.kind === "asset") setAsset({ id: opened.id, name: named ?? "", element: element.id });
        }} />}
      </ZoomStage>
      {asset && <AssetPanel key={asset.id} assetId={asset.id} name={asset.name} values={(data?.bindings ?? []).filter((row) => row.element === asset.element)}
        onTrend={(title, signals) => setTrend({ title, signals })} onClose={() => setAsset(null)} />}
      </div>
      {trend && <Suspense fallback={null}><TrendDialog title={trend.title} signals={trend.signals} period={trendPeriod} onClose={() => setTrend(null)} /></Suspense>}
    </div>
    <Legend diagram={shown} />
    {!live && data && data.bindings.some((row) => row.kind === "result") && <p className="dg-problems">{t("States published by other apps (alarms, loop health) show only live; in playback they are grey.")}</p>}
    {problems.length > 0 && <details className="dg-problems"><summary>{t("{n} values cannot be read", { n: problems.length })}</summary>
      <ul>{problems.map((row) => <li key={`${row.element}/${row.slot}`}>{row.label || row.element}: {row.error}</li>)}</ul>
    </details>}
    {isPublic && <p className="dg-problems">{t("Read-only process display shared from View.")}</p>}
    {sharing && <ShareDialog target="diagram" dashboardId={diagram.diagram_id} name={diagram.name} isAdmin={me?.is_admin} onClose={() => setSharing(false)} />}
  </>;
}

/** A diagram's public link: read-only, without sign-in; `?screen=1` opens it as a kiosk. */
export function PublicDiagramPage({ token }: { token: string }) {
  const [diagram, setDiagram] = useState<PublicDiagram | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { publicDiagramsApi.get(token).then(setDiagram).catch((err) => setError(message(err))); }, [token]);
  const symbols = useMemo(() => new Map((diagram?.symbols ?? []).map((item) => [item.id, item])), [diagram]);
  const shown = useMemo(() => (diagram ? { ...diagram, folder_id: "", tags: [] } : null), [diagram]);
  if (error) return <ErrorBox text={error} />;
  if (!shown) return <Loading />;
  return <Viewer diagram={shown} symbols={symbols} token={token} />;
}

export function DiagramPage({ diagramId, me }: { diagramId: string; me: Me }) {
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [error, setError] = useState("");
  const creating = diagramId === "new";
  const [editing, setEditing] = useState(creating || new URLSearchParams(globalThis.location.search).get("edit") === "1");
  const [symbols, library, symbolError] = useSymbols();
  useEffect(() => {
    if (creating) return;
    diagramsApi.get(diagramId).then(setDiagram).catch((err) => setError(message(err)));
  }, [diagramId, creating]);
  if (error) return <ErrorBox text={error} />;
  if (symbolError) return <ErrorBox text={symbolError} />;
  if (editing && me.can_edit) {
    const initial: DiagramDraft = diagram ?? emptyDiagram(t("New process display"));
    if (!creating && !diagram) return <Loading />;
    return <Suspense fallback={<Loading />}>
      <DiagramEditor diagramId={creating ? null : diagramId} initial={initial} baseUpdatedAt={diagram?.updated_at ?? null} symbols={symbols} library={library}
        onSaved={(saved) => { setDiagram(saved); setEditing(false); if (creating) navigate(`/diagrams/${saved.diagram_id}`); }}
        onCancel={() => { if (creating) navigate("/diagrams"); else setEditing(false); }} />
    </Suspense>;
  }
  if (!diagram) return <Loading />;
  return <Viewer diagram={diagram} symbols={symbols} me={me} onEdit={() => setEditing(true)} />;
}
