/**
 * Modelica's graphical annotations drawn as SVG (Modelica Language Specification, section 18):
 * Line, Polygon, Rectangle, Ellipse, Text and Bitmap, in an icon or diagram coordinate system
 * whose y axis points up. The whole drawing sits in one group flipped once (`scale(1,-1)`);
 * texts are flipped back so they read upright.
 */
import type { ReactNode } from "react";
import type { Graphic, Layer, Placement, Point } from "./types";

/** An affine transform [a, b, c, d, e, f] as SVG's matrix(): x' = a x + c y + e, y' = b x + d y + f. */
export type Matrix = [number, number, number, number, number, number];
export const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

export function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

export function apply(m: Matrix, [x, y]: Point): Point {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

export function translate(x: number, y: number): Matrix { return [1, 0, 0, 1, x, y]; }
export function rotate(degrees: number): Matrix {
  const r = (degrees * Math.PI) / 180;
  const c = Math.cos(r), s = Math.sin(r);
  return [c, s, -s, c, 0, 0];
}
export function scale(x: number, y: number): Matrix { return [x, 0, 0, y, 0, 0]; }

/** Where a placed class's coordinate system lands: its extent mapped onto the placement's
 * extent (a reversed extent flips), rotated about the placement's origin, then moved there. */
export function placementMatrix(placement: Placement, system: [Point, Point]): Matrix {
  const [[x1, y1], [x2, y2]] = placement.extent;
  const [[ix1, iy1], [ix2, iy2]] = system;
  const sx = (x2 - x1) / (ix2 - ix1 || 1);
  const sy = (y2 - y1) / (iy2 - iy1 || 1);
  const fit: Matrix = [sx, 0, 0, sy, x1 - ix1 * sx, y1 - iy1 * sy];
  const [ox, oy] = placement.origin ?? [0, 0];
  return multiply(translate(ox, oy), multiply(rotate(placement.rotation || 0), fit));
}

export function svgMatrix(m: Matrix): string {
  return `matrix(${m.map((v) => Number(v.toFixed(6))).join(",")})`;
}

const rgb = (color: number[] | null | undefined, fallback = "none") =>
  color && color.length === 3 ? `rgb(${color[0]},${color[1]},${color[2]})` : fallback;

function fill(item: Graphic): string {
  if (!item.fillPattern || item.fillPattern === "None") return "none";
  return rgb(item.fillColor, "none");
}

function dash(pattern?: string): string | undefined {
  switch (pattern) {
    case "Dash": return "6 4";
    case "Dot": return "1.5 3";
    case "DashDot": return "6 3 1.5 3";
    case "DashDotDot": return "6 3 1.5 3 1.5 3";
    default: return undefined;
  }
}

/** Line widths are millimetres in Modelica; on screen they stay readable at every zoom. */
const width = (mm?: number) => Math.max(1, (mm ?? 0.25) * 4);

function points(list: Point[] | undefined): string {
  return (list ?? []).map(([x, y]) => `${x},${y}`).join(" ");
}

/** Text with Modelica's substitutions: %name, %class and %parameter (its value, or itself). */
export function substitute(text: string, name: string, type: string, values: Record<string, string>): string {
  return text.replace(/%(%|name\b|class\b|[A-Za-z_][A-Za-z0-9_.]*)/g, (match, key: string) => {
    if (key === "%") return "%";
    if (key === "name") return name;
    if (key === "class") return type.split(".").pop() ?? type;
    return key in values ? values[key] : match;
  });
}

function textItem(item: Graphic, key: string, context: GraphicsContext): ReactNode {
  const [[x1, y1], [x2, y2]] = item.extent ?? [[-100, -20], [100, 20]];
  const label = substitute(item.text ?? "", context.name, context.type, context.values);
  if (!label.trim()) return null;
  const height = Math.abs(y2 - y1) || 20;
  const widthBox = Math.abs(x2 - x1) || 100;
  const size = item.fontSize ? item.fontSize * 0.35 * (context.unitsPerMm ?? 1) : Math.min(height * 0.8, (widthBox / Math.max(1, label.length)) * 1.7);
  const align = item.horizontalAlignment === "Left" ? "start" : item.horizontalAlignment === "Right" ? "end" : "middle";
  const x = align === "start" ? Math.min(x1, x2) : align === "end" ? Math.max(x1, x2) : (x1 + x2) / 2;
  const y = (y1 + y2) / 2;
  return <text key={key} transform={`translate(${x},${y}) scale(1,-1)`} textAnchor={align} dominantBaseline="central"
    fontSize={Math.max(1, size)} fill={rgb(item.textColor ?? item.lineColor, "currentColor")} className="mc-text">{label}</text>;
}

function arc(item: Graphic): string | null {
  const [[x1, y1], [x2, y2]] = item.extent ?? [[-10, -10], [10, 10]];
  const start = item.startAngle ?? 0, end = item.endAngle ?? 360;
  if (Math.abs(end - start) >= 360) return null;
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2, rx = Math.abs(x2 - x1) / 2, ry = Math.abs(y2 - y1) / 2;
  const at = (angle: number) => [cx + rx * Math.cos((angle * Math.PI) / 180), cy + ry * Math.sin((angle * Math.PI) / 180)];
  const [sx, sy] = at(start), [ex, ey] = at(end);
  const large = Math.abs(end - start) > 180 ? 1 : 0;
  return `M${cx},${cy} L${sx},${sy} A${rx},${ry} 0 ${large} 1 ${ex},${ey} Z`;
}

function arrowHead(from: Point, to: Point, size: number, filled: boolean, color: string, key: string): ReactNode {
  const angle = Math.atan2(to[1] - from[1], to[0] - from[0]);
  const back = (offset: number) => [to[0] - size * Math.cos(angle + offset), to[1] - size * Math.sin(angle + offset)];
  const [ax, ay] = back(0.4), [bx, by] = back(-0.4);
  return <polygon key={key} points={`${to[0]},${to[1]} ${ax},${ay} ${bx},${by}`} fill={filled ? color : "none"} stroke={color} vectorEffect="non-scaling-stroke" />;
}

export interface GraphicsContext { name: string; type: string; values: Record<string, string>; unitsPerMm?: number }

export function GraphicItem({ item, index, context }: { item: Graphic; index: number; context: GraphicsContext }) {
  const key = `g${index}`;
  const transform = (item.origin?.[0] || item.origin?.[1] || item.rotation)
    ? `translate(${item.origin[0]},${item.origin[1]}) rotate(${item.rotation || 0})` : undefined;
  let shape: ReactNode = null;
  if (item.kind === "Line") {
    const color = rgb(item.color, "rgb(0,0,0)");
    const list = item.points ?? [];
    const size = item.arrowSize ?? 3;
    shape = <>
      <polyline points={points(list)} fill="none" stroke={color} strokeWidth={width(item.thickness)} strokeDasharray={dash(item.pattern)} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      {list.length > 1 && item.arrow?.[0] && item.arrow[0] !== "None" && arrowHead(list[1], list[0], size, item.arrow[0] === "Filled", color, "a0")}
      {list.length > 1 && item.arrow?.[1] && item.arrow[1] !== "None" && arrowHead(list[list.length - 2], list[list.length - 1], size, item.arrow[1] === "Filled", color, "a1")}
    </>;
  } else if (item.kind === "Polygon") {
    shape = <polygon points={points(item.points)} fill={fill(item)} stroke={item.pattern === "None" ? "none" : rgb(item.lineColor, "rgb(0,0,0)")}
      strokeWidth={width(item.lineThickness)} strokeDasharray={dash(item.pattern)} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />;
  } else if (item.kind === "Rectangle") {
    const [[x1, y1], [x2, y2]] = item.extent ?? [[-10, -10], [10, 10]];
    shape = <rect x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} rx={item.radius || 0}
      fill={fill(item)} stroke={item.pattern === "None" ? "none" : rgb(item.lineColor, "rgb(0,0,0)")} strokeWidth={width(item.lineThickness)}
      strokeDasharray={dash(item.pattern)} vectorEffect="non-scaling-stroke" />;
  } else if (item.kind === "Ellipse") {
    const [[x1, y1], [x2, y2]] = item.extent ?? [[-10, -10], [10, 10]];
    const path = arc(item);
    const common = { fill: fill(item), stroke: item.pattern === "None" ? "none" : rgb(item.lineColor, "rgb(0,0,0)"), strokeWidth: width(item.lineThickness), strokeDasharray: dash(item.pattern), vectorEffect: "non-scaling-stroke" as const };
    shape = path ? <path d={path} {...common} /> : <ellipse cx={(x1 + x2) / 2} cy={(y1 + y2) / 2} rx={Math.abs(x2 - x1) / 2} ry={Math.abs(y2 - y1) / 2} {...common} />;
  } else if (item.kind === "Text") {
    shape = textItem(item, key, context);
  } else if (item.kind === "Bitmap") {
    const [[x1, y1], [x2, y2]] = item.extent ?? [[-10, -10], [10, 10]];
    shape = <rect x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} className="mc-bitmap" vectorEffect="non-scaling-stroke" />;
  }
  return shape ? <g transform={transform}>{shape}</g> : null;
}

export function LayerGraphics({ layer, context }: { layer: Layer; context: GraphicsContext }) {
  return <>{layer.graphics.map((item, index) => <GraphicItem key={index} item={item} index={index} context={context} />)}</>;
}

/** One class's icon on its own (the library browser, the project tree): fitted in a square. */
export function IconPreview({ layer, name = "", type = "", size = 56, values = {} }: { layer: Layer | null | undefined; name?: string; type?: string; size?: number; values?: Record<string, string> }) {
  if (!layer || !layer.graphics.length) return <svg width={size} height={size} viewBox="0 0 10 10" className="mc-icon mc-icon-empty" aria-hidden="true"><rect x="1" y="1" width="8" height="8" rx="1" /></svg>;
  const [[x1, y1], [x2, y2]] = layer.extent;
  const pad = Math.abs(x2 - x1) * 0.12;
  const left = Math.min(x1, x2) - pad, top = -Math.max(y1, y2) - pad;
  const w = Math.abs(x2 - x1) + 2 * pad, h = Math.abs(y2 - y1) + 2 * pad;
  return <svg width={size} height={size} viewBox={`${left} ${top} ${w} ${h}`} className="mc-icon" aria-hidden="true">
    <g transform="scale(1,-1)"><LayerGraphics layer={layer} context={{ name, type, values }} /></g>
  </svg>;
}
