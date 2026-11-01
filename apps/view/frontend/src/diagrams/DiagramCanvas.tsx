/** Draws a diagram on one SVG, the same for the live page, playback and the editor: symbols from
 * the library (their drawings come cleaned by the server), lines between their ports, values and
 * texts, each coloured by what its bindings show. The editor passes `selected`, `showPorts` and
 * the pointer handlers; the page passes `onOpen` for a click. */
import { AnalogBar } from "../analog";
import { memo, useId, useMemo, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { t } from "../i18n";
import {
  formatValue, labelSpot, levelBox, lineDrawing, linePath, mediumColor, outlineOf, placeDir, placePoint, symbolBox,
  type DiagramDraft, type Dir, type Element, type LineElement, type Point, type Shown, type Slot, type SymbolDef, type SymbolElement, type TextElement, type ValueElement,
} from "./model";

export type Shows = Map<string, Partial<Record<Slot, Shown>>>;
export interface PortHit { element: string; port: string; point: Point }

export interface CanvasProps {
  diagram: DiagramDraft;
  symbols: Map<string, SymbolDef>;
  shows?: Shows;
  selected?: Set<string>;
  showPorts?: boolean;
  /** A click on an element in view mode. */
  onOpen?: (element: Element) => void;
  onElementDown?: (event: ReactPointerEvent, element: Element) => void;
  onPortDown?: (event: ReactPointerEvent, hit: PortHit) => void;
  onCanvasDown?: (event: ReactPointerEvent) => void;
  /** Drawn over the diagram (the editor's guides, a line being drawn, the selection box). */
  overlay?: ReactNode;
  svgRef?: React.Ref<SVGSVGElement>;
  className?: string;
  /** The part of the canvas shown (the viewer's zoom); left out, the whole canvas. */
  view?: ViewBox | null;
}

/** A rectangle of the canvas, in its own units. */
export type ViewBox = { x: number; y: number; w: number; h: number };

function tooltip(parts: Array<Shown | undefined>, fallback: string): string {
  const lines = parts.filter((part): part is Shown => Boolean(part)).map((part) => {
    if (part.error) return `${part.label}: ${part.error}`;
    const value = `${part.label}: ${formatValue(part.value)}${part.unit ? ` ${part.unit}` : ""}`;
    const stale = part.stale ? ` (${t("no new value since {at}", { at: part.at ? new Date(part.at).toLocaleString() : "?" })})` : "";
    return `${value}${stale}${part.summary ? ` · ${part.summary}` : ""}`;
  });
  return [fallback, ...lines].filter(Boolean).join("\n");
}

/** Off-page connectors are the diagram's way to the next one: drawn as a button (a pill with its
 * label and a chevron the way the line goes on), not as a bare arrow outline. */
export function isNavigation(element: SymbolElement): boolean {
  return element.symbol.startsWith("connector.offpage");
}

const CHEVRON: Record<Dir, string> = { e: "M-3 -5 L3 0 L-3 5", w: "M3 -5 L-3 0 L3 5", n: "M-5 3 L0 -3 L5 3", s: "M-5 -3 L0 3 L5 -3" };

function NavigationButton({ element, label }: { element: SymbolElement; label: string }) {
  const box = symbolBox(element);
  const toward = placeDir(element, "e");
  const pad = Math.min(box.h / 2, 14), icon = 12;
  const left = toward === "w";
  // The chevron sits at the end the line goes on to (the left for a connector turned round).
  const ix = !label ? box.x + box.w / 2 : left ? box.x + pad + icon / 2 : box.x + box.w - pad - icon / 2;
  const from = left ? box.x + pad + icon + 4 : box.x + pad, to = left ? box.x + box.w - pad : box.x + box.w - pad - icon - 4;
  const cy = box.y + box.h / 2;
  // A long label takes a smaller type rather than running out of the button (about 0.56 em a letter).
  const size = Math.max(9, Math.min(13, box.h * 0.4, (to - from) / Math.max(1, label.length * 0.56)));
  return <>
    <rect className="dg-nav" x={box.x} y={box.y} width={box.w} height={box.h} rx={Math.min(box.h / 2, 18)} />
    {label && <text className="dg-nav-label" x={(from + to) / 2} y={cy} textAnchor="middle" dominantBaseline="central" style={{ fontSize: size }}>{label}</text>}
    <path className="dg-nav-icon" d={CHEVRON[toward]} transform={`translate(${ix} ${cy})`} />
  </>;
}

/** A vessel's contents: the level goes over its straight part (`pc-level`) and the liquid fills
 * the vessel's own outline below it, heads and cone included, with the surface drawn as a line
 * ("a rectangle that does not follow the tank"). A drawing without an outline
 * keeps the rectangle. */
function Liquid({ level, fraction, outline, size: [width, bottom], clip }: { level: { x: number; y: number; w: number; h: number }; fraction: number; outline: string | null; size: [number, number]; clip: string }) {
  const share = Math.max(0, Math.min(1, fraction));
  const surface = level.y + level.h * (1 - share);
  if (!outline) return <rect x={level.x} y={surface} width={level.w} height={level.h * share} />;
  return <>
    <clipPath id={clip} dangerouslySetInnerHTML={{ __html: outline }} />
    <g clipPath={`url(#${clip})`}>
      <rect x={0} y={surface} width={width} height={Math.max(0, bottom - surface)} />
      <line className="dg-level-surface" x1={0} x2={width} y1={surface} y2={surface} />
    </g>
  </>;
}

type Baseline = "auto" | "central" | "hanging";

const SymbolView = memo(function SymbolView({ element, def, show, selected, onDown, onOpen }: {
  element: SymbolElement; def?: SymbolDef; show?: Partial<Record<Slot, Shown>>; selected: boolean;
  onDown?: (event: ReactPointerEvent, element: Element) => void; onOpen?: (element: Element) => void;
}) {
  const nav = isNavigation(element);
  // The box the drawing really covers: the labels and the selection go by it, never by a box drawn out of shape.
  const box = symbolBox(element, nav ? null : def);
  const state = show?.state?.state ?? (element.state ? "unknown" : "none");
  const on = show?.running?.on;
  const fraction = show?.level?.fraction;
  const level = def ? levelBox(def.svg) : null;
  const outline = level ? outlineOf(def!.svg) : null;
  const clip = `dg-liquid-${useId().replace(/:/g, "")}`;
  const flip = element.flip ? `translate(${element.w} 0) scale(-1 1)` : "";
  const turn = element.rotate ? `rotate(${element.rotate} ${element.w / 2} ${element.h / 2})` : "";
  const failed = [show?.state, show?.level, show?.running].some((part) => part?.error || part?.stale);
  const label = element.label_position === "none" ? "" : element.label;
  // One scale both ways (a pump stays round); only a shape made to stretch fills any box.
  const fit = def?.stretch ? "none" : "xMidYMid meet";
  const gap = 8;
  const labelAt: Record<string, [number, number, "start" | "middle" | "end", Baseline]> = {
    below: [box.x + box.w / 2, box.y + box.h + gap, "middle", "hanging"],
    above: [box.x + box.w / 2, box.y - gap, "middle", "auto"],
    left: [box.x - gap, box.y + box.h / 2, "end", "central"],
    right: [box.x + box.w + gap, box.y + box.h / 2, "start", "central"],
    inside: [box.x + box.w / 2, box.y + box.h / 2, "middle", "central"],
  };
  const [lx, ly, anchor, baseline] = labelAt[element.label_position] ?? labelAt.below;
  const clickable = Boolean(onOpen && (element.link || element.asset_id));
  return <g className={`dg-el dg-sym${nav ? " dg-sym-nav" : ""}${selected ? " dg-selected" : ""}${clickable ? " dg-clickable" : ""}${failed ? " dg-failed" : ""}`} data-state={state} data-on={on === true ? "true" : on === false ? "false" : undefined}
    data-element={element.id} onPointerDown={onDown ? (event) => onDown(event, element) : undefined} onClick={clickable ? () => onOpen?.(element) : undefined}>
    <title>{tooltip([show?.state, show?.level, show?.running], element.label || def?.title || element.symbol)}</title>
    {nav ? <NavigationButton element={element} label={label} /> : <>
      <g transform={`translate(${element.x} ${element.y}) ${turn} ${flip}`}>
        {/* A unit block is its own rectangle, so its corners stay round however it is stretched. */}
        {def?.id === "shape.panel" ?<rect className="dg-drawing pc-state dg-panel" width={element.w} height={element.h} rx={8} />
        : def ? <>
          <svg width={element.w} height={element.h} viewBox={`0 0 ${def.w} ${def.h}`} preserveAspectRatio={fit} overflow="visible" className="dg-drawing" dangerouslySetInnerHTML={{ __html: def.svg }} />
          {level && fraction != null && <svg width={element.w} height={element.h} viewBox={`0 0 ${def.w} ${def.h}`} preserveAspectRatio={fit} overflow="visible" className="dg-level">
            <Liquid level={level} fraction={fraction} outline={outline} size={[def.w, def.h]} clip={clip} />
          </svg>}
        </> : <>
          <rect className="dg-missing" width={element.w} height={element.h} rx={4} />
          <text className="dg-missing-text" x={element.w / 2} y={element.h / 2 + 4} textAnchor="middle">{element.symbol}</text>
        </>}
      </g>
      {label && <text className={`dg-label${element.label_position === "inside" ? " dg-label-inside" : ""}`} x={lx} y={ly} textAnchor={anchor} dominantBaseline={baseline}>{label}</text>}
    </>}
    {!nav && show?.state?.priority && (state === "alarm" || state === "warning") && <AlarmMark priority={show.state.priority} x={box.x + box.w} y={box.y} />}
    {selected && <rect className="dg-selection" x={box.x - 4} y={box.y - 4} width={box.w + 8} height={box.h + 8} rx={4} />}
  </g>;
});

/** ISA-101: an alarm is shown by shape and number as well as colour, so it reads without colour
 * (colour blindness, a grey print): critical a square, high a triangle, medium a diamond, low a
 * circle, each with its priority number. */
const ALARM_MARK = { critical: "1", high: "2", medium: "3", low: "4" } as const;
export function AlarmMark({ priority, x, y }: { priority: keyof typeof ALARM_MARK; x: number; y: number }) {
  const r = 9;
  const shape = priority === "critical" ? <rect x={-r} y={-r} width={2 * r} height={2 * r} rx={1.5} />
    : priority === "high" ? <path d={`M0 ${-r - 2}L${r + 2} ${r}H${-r - 2}Z`} />
    : priority === "medium" ? <path d={`M0 ${-r - 2}L${r + 2} 0L0 ${r + 2}L${-r - 2} 0Z`} />
    : <circle r={r} />;
  return <g className={`dg-alarm-mark dg-alarm-${priority}`} transform={`translate(${x} ${y})`} aria-label={t("Priority {mark} alarm", { mark: ALARM_MARK[priority] })}>
    {shape}
    <text y={priority === "high" ? 4 : 1} textAnchor="middle" dominantBaseline="central">{ALARM_MARK[priority]}</text>
  </g>;
}

/** The analog indicator's scale: its own, else the signal's range, else the limits and the
 * value with a margin. */
export function indicatorScale(element: ValueElement, show?: Shown): [number, number] {
  const limits = element.limits ?? {};
  const known = [limits.low_alarm, limits.low_warning, limits.high_warning, limits.high_alarm, element.indicator?.normal_low, element.indicator?.normal_high, typeof show?.value === "number" ? show.value : null]
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  let low = element.indicator?.min ?? show?.low ?? (known.length ? Math.min(...known) : 0);
  let high = element.indicator?.max ?? show?.high ?? (known.length ? Math.max(...known) : 100);
  if (!(high > low)) { low -= 1; high += 1; }
  const pad = (high - low) * 0.1;
  if (element.indicator?.min == null && show?.low == null) low -= pad;
  if (element.indicator?.max == null && show?.high == null) high += pad;
  return [low, high];
}

function ValueView({ element, show, sp, selected, onDown, onOpen }: { element: ValueElement; show?: Shown; sp?: Shown; selected: boolean; onDown?: (event: ReactPointerEvent, element: Element) => void; onOpen?: (element: Element) => void }) {
  const state = show?.state ?? "unknown";
  const text = show?.error ? "?" : formatValue(show?.value ?? null, element.decimals);
  const label = element.show_label && (element.label || show?.label) ? `${element.label || show?.label} ` : "";
  const unit = element.show_unit && show?.unit ? ` ${show.unit}` : "";
  const width = Math.max(40, (label.length + text.length + unit.length) * element.size * 0.6 + 12);
  const height = element.size + 10;
  let indicator = null;
  if (element.indicator) {
    const [min, max] = indicatorScale(element, show);
    const limits = element.limits ?? {};
    const value = !show?.error && typeof show?.value === "number" ? show.value : null;
    const setpoint = sp && !sp.error && typeof sp.value === "number" ? sp.value : null;
    indicator = <AnalogBar spec={{ value, min, max, limits: { ll: limits.low_alarm, l: limits.low_warning, h: limits.high_warning, hh: limits.high_alarm }, normal: { low: element.indicator.normal_low ?? limits.low_warning ?? null, high: element.indicator.normal_high ?? limits.high_warning ?? null }, sp: setpoint, state: value === null ? "unknown" : state }}
      x={element.x} y={element.y + height + 2} width={element.indicator.width} height={26} decimals={element.decimals} />;
  }
  return <g className={`dg-el dg-value${selected ? " dg-selected" : ""}${onOpen ? " dg-clickable" : ""}`} data-state={state} data-element={element.id}
    onPointerDown={onDown ? (event) => onDown(event, element) : undefined} onClick={onOpen ? () => onOpen(element) : undefined}>
    <title>{tooltip([show, sp], "")}</title>
    <rect className="dg-value-box" x={element.x} y={element.y} width={width} height={height} rx={3} />
    <text x={element.x + 6} y={element.y + element.size + 2} fontSize={element.size}>
      {label && <tspan className="dg-value-label">{label}</tspan>}
      <tspan className="dg-value-number">{text}</tspan>
      {unit && <tspan className="dg-value-unit">{unit}</tspan>}
    </text>
    {indicator}
    {selected && <rect className="dg-selection" x={element.x - 3} y={element.y - 3} width={Math.max(width, element.indicator ? element.indicator.width : 0) + 6} height={height + (element.indicator ? 30 : 0) + 6} rx={4} />}
  </g>;
}

function LineView({ element, path, show, selected, onDown }: { element: LineElement; path: Point[]; show?: Shown; selected: boolean; onDown?: (event: ReactPointerEvent, element: Element) => void }) {
  if (path.length < 2) return null;
  const line = (points: Point[]) => points.map((point, index) => `${index ? "L" : "M"}${point[0]} ${point[1]}`).join(" ");
  const d = line(path);
  const drawing = lineDrawing(path, element.kind, element.arrow);
  const color = element.kind === "process" ? mediumColor(element.medium || "process") : undefined;
  const spot = element.label ? labelSpot(path) : null;
  return <g className={`dg-el dg-line dg-line-${element.kind}${selected ? " dg-selected" : ""}`} data-element={element.id} data-on={show?.on === true ? "true" : show?.on === false ? "false" : undefined}
    style={color ? { color } : undefined} onPointerDown={onDown ? (event) => onDown(event, element) : undefined}>
    <title>{tooltip([show], element.label || element.medium)}</title>
    <path className="dg-line-hit" d={d} />
    <path className="dg-line-path" d={line(drawing.stroke)} />
    {show?.on && <path className="dg-line-flow" d={d} />}
    {drawing.heads.map((head, index) => <path key={index} className="dg-arrowhead" d={`${line(head)} Z`} />)}
    {drawing.flows.map((flow, index) => <path key={`f${index}`} className="dg-flow-arrow" d="M-4 -4 L3 0 L-4 4 Z" transform={`translate(${flow.at[0]} ${flow.at[1]}) rotate(${flow.angle})`} />)}
    {spot && <text className="dg-label dg-line-label" x={spot.at[0]} y={spot.at[1]} textAnchor={spot.anchor} dominantBaseline={spot.anchor === "start" ? "central" : "auto"}>{element.label}</text>}
  </g>;
}

function TextView({ element, selected, onDown }: { element: TextElement; selected: boolean; onDown?: (event: ReactPointerEvent, element: Element) => void }) {
  return <g className={`dg-el dg-text${selected ? " dg-selected" : ""}`} data-element={element.id} onPointerDown={onDown ? (event) => onDown(event, element) : undefined}>
    <text x={element.x} y={element.y} fontSize={element.size} textAnchor={element.align} fontWeight={element.bold ? 600 : 400}>
      {element.text.split("\n").map((line, index) => <tspan key={index} x={element.x} dy={index ? element.size * 1.25 : 0}>{line}</tspan>)}
    </text>
  </g>;
}

function Ports({ element, def, onPortDown }: { element: SymbolElement; def: SymbolDef; onPortDown?: (event: ReactPointerEvent, hit: PortHit) => void }) {
  return <g className="dg-ports" data-port-of={element.id}>
    {def.ports.map((port) => {
      const point = placePoint(element, def, port.x, port.y);
      return <circle key={port.id} className={`dg-port dg-port-${port.kind ?? "process"}`} data-port={port.id} cx={point[0]} cy={point[1]} r={5}
        onPointerDown={onPortDown ? (event) => { event.stopPropagation(); onPortDown(event, { element: element.id, port: port.id, point }); } : undefined}>
        <title>{port.id}</title>
      </circle>;
    })}
  </g>;
}

export function DiagramCanvas({ diagram, symbols, shows, selected, showPorts, onOpen, onElementDown, onPortDown, onCanvasDown, overlay, svgRef, className, view }: CanvasProps) {
  const byId = useMemo(() => new Map(diagram.elements.map((element) => [element.id, element])), [diagram.elements]);
  const lines = diagram.elements.filter((element): element is LineElement => element.type === "line");
  const others = diagram.elements.filter((element) => element.type !== "line");
  const none = new Set<string>();
  const picked = selected ?? none;
  return <svg ref={svgRef} className={`dg-canvas ${className ?? ""}`} viewBox={view ? `${view.x} ${view.y} ${view.w} ${view.h}` : `0 0 ${diagram.width} ${diagram.height}`} preserveAspectRatio="xMidYMid meet"
    role="img" aria-label={diagram.name} onPointerDown={onCanvasDown}>
    <defs>
      {diagram.grid > 0 && <pattern id="dg-grid" width={diagram.grid} height={diagram.grid} patternUnits="userSpaceOnUse"><circle cx={0.5} cy={0.5} r={0.6} className="dg-grid-dot" /></pattern>}
    </defs>
    <rect className="dg-background" width={diagram.width} height={diagram.height} />
    {showPorts && diagram.grid > 0 && <rect width={diagram.width} height={diagram.height} fill="url(#dg-grid)" pointerEvents="none" />}
    {lines.map((line) => <LineView key={line.id} element={line} path={linePath(line, byId, symbols, diagram.grid)} show={shows?.get(line.id)?.flow} selected={picked.has(line.id)} onDown={onElementDown} />)}
    {others.map((element) => {
      if (element.type === "symbol") return <SymbolView key={element.id} element={element} def={symbols.get(element.symbol)} show={shows?.get(element.id)} selected={picked.has(element.id)} onDown={onElementDown} onOpen={onOpen} />;
      if (element.type === "value") return <ValueView key={element.id} element={element} show={shows?.get(element.id)?.value} sp={shows?.get(element.id)?.setpoint} selected={picked.has(element.id)} onDown={onElementDown} onOpen={onOpen} />;
      if (element.type === "text") return <TextView key={element.id} element={element} selected={picked.has(element.id)} onDown={onElementDown} />;
      return null;
    })}
    {showPorts && others.map((element) => element.type === "symbol" && symbols.get(element.symbol) ? <Ports key={`p-${element.id}`} element={element} def={symbols.get(element.symbol)!} onPortDown={onPortDown} /> : null)}
    {overlay}
  </svg>;
}
