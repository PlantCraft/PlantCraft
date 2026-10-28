/**
 * The diagram editor: a model's components (their icons where their Placement puts them) and
 * connections, drawn from omc's instance of the class. Every change is a text edit the server
 * makes in the class (add, move, rotate, delete, connect, disconnect), so the text stays the
 * one source of truth; the diagram is drawn again from it after each change.
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent } from "react";
import { apply, IDENTITY, LayerGraphics, multiply, placementMatrix, svgMatrix, type Matrix } from "./Graphics";
import { CLASS_DRAG } from "./Library";
import { t } from "./i18n";
import type { ComponentInfo, Diagram, Placement, Point } from "./types";

const DEFAULT_SYSTEM: [Point, Point] = [[-100, -100], [100, 100]];
const GRID = 2;
const snap = (value: number) => Math.round(value / GRID) * GRID;

export type DiagramChange =
  | { op: "add"; type: string; extent: [Point, Point] }
  | { op: "move"; name: string; extent: [Point, Point]; origin: Point; rotation: number }
  | { op: "delete"; name: string }
  | { op: "connect"; left: string; right: string; points: Point[] }
  | { op: "disconnect"; left: string; right: string };

export type Selection = { kind: "component"; name: string } | { kind: "connection"; left: string; right: string } | null;

function system(layer: { extent: [Point, Point] } | undefined): [Point, Point] {
  const extent = layer?.extent;
  return extent && extent[0][0] !== extent[1][0] && extent[0][1] !== extent[1][1] ? extent : DEFAULT_SYSTEM;
}

export function componentMatrix(component: ComponentInfo): Matrix {
  return placementMatrix(component.placement, system(component.icon));
}

/** Where each connector's centre is in the diagram: `component.connector`, or a top-level connector. */
export function connectorPoints(diagram: Diagram): Map<string, Point> {
  const found = new Map<string, Point>();
  for (const component of diagram.components) {
    const matrix = componentMatrix(component);
    const [[x1, y1], [x2, y2]] = system(component.icon);
    if (component.connector) found.set(component.name, apply(matrix, [(x1 + x2) / 2, (y1 + y2) / 2]));
    for (const connector of component.connectors) {
      const [[a1, b1], [a2, b2]] = system(connector.icon);
      const inner = multiply(matrix, placementMatrix(connector.placement, system(connector.icon)));
      found.set(`${component.name}.${connector.name}`, apply(inner, [(a1 + a2) / 2, (b1 + b2) / 2]));
    }
  }
  return found;
}

/** The corners of a placement in the diagram, as a box [left, bottom, right, top]. */
export function bounds(component: ComponentInfo): [number, number, number, number] {
  const matrix = componentMatrix(component);
  const [[x1, y1], [x2, y2]] = system(component.icon);
  const corners = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]].map((p) => apply(matrix, p as Point));
  const xs = corners.map((p) => p[0]), ys = corners.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** The same placement moved by (dx, dy): its origin when it has one, its extent otherwise. */
export function moved(placement: Placement, dx: number, dy: number): { extent: [Point, Point]; origin: Point; rotation: number } {
  const [ox, oy] = placement.origin ?? [0, 0];
  const [[x1, y1], [x2, y2]] = placement.extent;
  if (ox || oy) return { extent: placement.extent, origin: [ox + dx, oy + dy], rotation: placement.rotation || 0 };
  return { extent: [[x1 + dx, y1 + dy], [x2 + dx, y2 + dy]], origin: [0, 0], rotation: placement.rotation || 0 };
}

/** A quarter turn counter-clockwise about the component's own centre (as OMEdit does it). */
export function rotated(placement: Placement): { extent: [Point, Point]; origin: Point; rotation: number } {
  const [ox, oy] = placement.origin ?? [0, 0];
  const [[x1, y1], [x2, y2]] = placement.extent;
  const rotation = ((placement.rotation || 0) + 90) % 360;
  if (ox || oy) return { extent: placement.extent, origin: [ox, oy], rotation };
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
  return { extent: [[x1 - cx, y1 - cy], [x2 - cx, y2 - cy]], origin: [cx, cy], rotation };
}

type Drag =
  | { kind: "move"; name: string; from: Point; dx: number; dy: number }
  | { kind: "wire"; from: string; start: Point; at: Point }
  | { kind: "pan"; client: Point; box: [number, number, number, number] };

export interface DiagramViewProps {
  diagram: Diagram;
  editable: boolean;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  onChange: (change: DiagramChange) => void;
}

export function DiagramView({ diagram, editable, selection, onSelect, onChange }: DiagramViewProps) {
  const svg = useRef<SVGSVGElement>(null);
  const world = useRef<SVGGElement>(null);
  const extent = system(diagram.diagram);
  const initial = useMemo<[number, number, number, number]>(() => {
    let [left, bottom, right, top] = [Math.min(extent[0][0], extent[1][0]), Math.min(extent[0][1], extent[1][1]), Math.max(extent[0][0], extent[1][0]), Math.max(extent[0][1], extent[1][1])];
    for (const component of diagram.components) {
      const [l, b, r, tp] = bounds(component);
      left = Math.min(left, l); bottom = Math.min(bottom, b); right = Math.max(right, r); top = Math.max(top, tp);
    }
    const pad = (right - left) * 0.06;
    return [left - pad, -top - pad, right - left + 2 * pad, top - bottom + 2 * pad];
    // Fitted once per class: a redraw after an edit keeps the person's zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diagram.name]);
  const [box, setBox] = useState(initial);
  useEffect(() => setBox(initial), [initial]);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [dropping, setDropping] = useState(false);
  const points = useMemo(() => connectorPoints(diagram), [diagram]);

  const toDiagram = (clientX: number, clientY: number): Point => {
    const matrix = world.current?.getScreenCTM?.();
    if (!matrix) return [0, 0];
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return [point.x, point.y];
  };

  useEffect(() => {
    if (!editable) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, .cm-editor"))) return;
      if ((event.key === "Delete" || event.key === "Backspace") && selection) {
        event.preventDefault();
        if (selection.kind === "component") onChange({ op: "delete", name: selection.name });
        else onChange({ op: "disconnect", left: selection.left, right: selection.right });
      }
      if ((event.key === "r" || event.key === "R") && selection?.kind === "component" && !event.ctrlKey && !event.metaKey) {
        const component = diagram.components.find((item) => item.name === selection.name);
        if (component && !component.inherited) onChange({ op: "move", name: component.name, ...rotated(component.placement) });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable, selection, onChange, diagram]);

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    const rect = svg.current?.getBoundingClientRect();
    if (!rect || !rect.width) return;
    const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const [x, y, w, h] = box;
    const fx = (event.clientX - rect.left) / rect.width, fy = (event.clientY - rect.top) / rect.height;
    const nw = Math.min(Math.max(w * factor, 10), 5000), nh = (h * nw) / w;
    setBox([x + (w - nw) * fx, y + (h - nh) * fy, nw, nh]);
  };

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    const target = event.target as Element;
    const connector = target.closest("[data-connector]")?.getAttribute("data-connector");
    const component = target.closest("[data-component]")?.getAttribute("data-component");
    const connection = target.closest("[data-connection]")?.getAttribute("data-connection");
    svg.current?.setPointerCapture?.(event.pointerId);
    if (connector && editable && points.has(connector)) {
      const start = points.get(connector)!;
      setDrag({ kind: "wire", from: connector, start, at: start });
    } else if (component) {
      onSelect({ kind: "component", name: component });
      const item = diagram.components.find((c) => c.name === component);
      if (editable && item && !item.inherited) setDrag({ kind: "move", name: component, from: toDiagram(event.clientX, event.clientY), dx: 0, dy: 0 });
    } else if (connection) {
      const [left, right] = connection.split("|");
      onSelect({ kind: "connection", left, right });
    } else {
      onSelect(null);
      setDrag({ kind: "pan", client: [event.clientX, event.clientY], box });
    }
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    if (drag.kind === "pan") {
      const rect = svg.current?.getBoundingClientRect();
      if (!rect?.width) return;
      const scale = drag.box[2] / rect.width;
      setBox([drag.box[0] - (event.clientX - drag.client[0]) * scale, drag.box[1] - (event.clientY - drag.client[1]) * scale, drag.box[2], drag.box[3]]);
    } else if (drag.kind === "move") {
      const [x, y] = toDiagram(event.clientX, event.clientY);
      setDrag({ ...drag, dx: snap(x - drag.from[0]), dy: snap(y - drag.from[1]) });
    } else {
      setDrag({ ...drag, at: toDiagram(event.clientX, event.clientY) });
    }
  };

  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    const current = drag;
    setDrag(null);
    if (!current) return;
    if (current.kind === "move" && (current.dx || current.dy)) {
      const component = diagram.components.find((c) => c.name === current.name);
      if (component) onChange({ op: "move", name: component.name, ...moved(component.placement, current.dx, current.dy) });
    } else if (current.kind === "wire") {
      const under = document.elementFromPoint?.(event.clientX, event.clientY);
      const to = under?.closest("[data-connector]")?.getAttribute("data-connector");
      if (to && to !== current.from && points.has(to)) {
        const start = current.start, end = points.get(to)!;
        const middle = snap((start[0] + end[0]) / 2);
        const route: Point[] = start[1] === end[1] ? [start, end] : [start, [middle, start[1]], [middle, end[1]], end];
        onChange({ op: "connect", left: current.from, right: to, points: route });
      }
    }
  };

  const offset = (name: string): Matrix => (drag?.kind === "move" && drag.name === name ? [1, 0, 0, 1, drag.dx, drag.dy] : IDENTITY);
  const [vx, vy, vw, vh] = box;
  const grid = [];
  const [[gx1, gy1], [gx2, gy2]] = extent;
  for (let x = Math.ceil(Math.min(gx1, gx2) / 10) * 10; x <= Math.max(gx1, gx2); x += 10) grid.push(<line key={`x${x}`} x1={x} x2={x} y1={gy1} y2={gy2} />);
  for (let y = Math.ceil(Math.min(gy1, gy2) / 10) * 10; y <= Math.max(gy1, gy2); y += 10) grid.push(<line key={`y${y}`} y1={y} y2={y} x1={gx1} x2={gx2} />);

  return <svg ref={svg} className={`mc-diagram${dropping ? " mc-dropping" : ""}${drag?.kind === "pan" ? " mc-panning" : ""}`} viewBox={`${vx} ${vy} ${vw} ${vh}`}
    role="img" aria-label={t("Diagram of {name}", { name: diagram.name })}
    onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
    onDragOver={(event) => { if (editable && event.dataTransfer.types.includes(CLASS_DRAG)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setDropping(true); } }}
    onDragLeave={() => setDropping(false)}
    onDrop={(event) => {
      setDropping(false);
      const type = event.dataTransfer.getData(CLASS_DRAG);
      // A class cannot hold itself.
      if (!editable || !type || type === diagram.name) return;
      event.preventDefault();
      const [x, y] = toDiagram(event.clientX, event.clientY);
      const cx = snap(x), cy = snap(y);
      onChange({ op: "add", type, extent: [[cx - 10, cy - 10], [cx + 10, cy + 10]] });
    }}>
    <g ref={world} transform="scale(1,-1)">
      <rect className="mc-sheet" x={Math.min(gx1, gx2)} y={Math.min(gy1, gy2)} width={Math.abs(gx2 - gx1)} height={Math.abs(gy2 - gy1)} />
      <g className="mc-grid">{grid}</g>
      <g className="mc-layer"><LayerGraphics layer={diagram.diagram} context={{ name: diagram.name, type: diagram.name, values: {} }} /></g>
      {diagram.connections.map((connection) => {
        const key = `${connection.from}|${connection.to}`;
        const chosen = selection?.kind === "connection" && selection.left === connection.from && selection.right === connection.to;
        const route = connection.points.length >= 2 ? connection.points : [points.get(connection.from), points.get(connection.to)].filter(Boolean) as Point[];
        const color = connection.color ? `rgb(${connection.color.join(",")})` : "rgb(0,0,127)";
        const line = route.map(([x, y]) => `${x},${y}`).join(" ");
        return <g key={key} data-connection={key} className={`mc-connection${chosen ? " mc-selected" : ""}`}>
          <polyline points={line} className="mc-hit" />
          <polyline points={line} fill="none" stroke={color} strokeWidth={Math.max(1, (connection.thickness || 0.25) * 4)} vectorEffect="non-scaling-stroke" />
        </g>;
      })}
      {diagram.components.map((component) => {
        const matrix = multiply(offset(component.name), componentMatrix(component));
        const [[x1, y1], [x2, y2]] = system(component.icon);
        const chosen = selection?.kind === "component" && selection.name === component.name;
        const empty = !component.icon?.graphics?.length;
        return <g key={component.name} data-component={component.name} className={`mc-component${chosen ? " mc-selected" : ""}${component.inherited ? " mc-inherited" : ""}`}>
          <g transform={svgMatrix(matrix)}>
            <rect className="mc-hit" x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} />
            {empty ? <rect className="mc-placeholder" x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} />
              : <LayerGraphics layer={component.icon} context={{ name: component.name, type: component.type, values: component.values }} />}
            {component.connector && <rect data-connector={component.name} className="mc-port" x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} />}
            {component.connectors.map((connector) => {
              const [[a1, b1], [a2, b2]] = system(connector.icon);
              return <g key={connector.name} transform={svgMatrix(placementMatrix(connector.placement, system(connector.icon)))}>
                <LayerGraphics layer={connector.icon} context={{ name: connector.name, type: connector.type, values: {} }} />
                <rect data-connector={`${component.name}.${connector.name}`} className="mc-port" x={Math.min(a1, a2)} y={Math.min(b1, b2)} width={Math.abs(a2 - a1)} height={Math.abs(b2 - b1)}>
                  <title>{`${component.name}.${connector.name} (${connector.type})`}</title>
                </rect>
              </g>;
            })}
          </g>
          {empty && (() => { const [l, b, r, tp] = bounds(component); return <text className="mc-text mc-placeholder-name" transform={`translate(${(l + r) / 2},${(b + tp) / 2}) scale(1,-1)`} textAnchor="middle" dominantBaseline="central" fontSize={Math.max(3, (r - l) / 5)}>{component.name}</text>; })()}
          {chosen && (() => { const [l, b, r, tp] = bounds(component); return <rect className="mc-selection" x={l + (drag?.kind === "move" ? drag.dx : 0) - 2} y={b + (drag?.kind === "move" ? drag.dy : 0) - 2} width={r - l + 4} height={tp - b + 4} />; })()}
        </g>;
      })}
      {drag?.kind === "wire" && <line className="mc-wire" x1={drag.start[0]} y1={drag.start[1]} x2={drag.at[0]} y2={drag.at[1]} />}
    </g>
  </svg>;
}
