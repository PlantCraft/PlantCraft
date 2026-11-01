/**
 * What an app's published widget draws (docs/widgets.md, "Publishing widgets"): eight shapes, so
 * the same widget reads the same on the app's own Overview and on Desk's Today, and nothing of
 * the app runs inside the platform.
 *
 *   number   one figure, its unit and a line below it
 *   list     rows of a name, a line below it, a value and a status dot
 *   split    a total split by status, as one bar and its parts (each part a filter)
 *   series   a figure and its recent history, as a small area chart
 *   facts    one thing (a run, a schedule, the collector): its status and a few labelled values
 *   bars     a ranking: one bar per row, longest first, with a target line if there is one
 *   columns  a count per hour or day, each column stacked by status, with a target line
 *   tiles    a status map: one small square per thing (a loop, a signal), in groups (an area)
 *
 * Every shape draws what fits its card: `h` is the card's height in rows (1 to 3).
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { formatDate, formatNumber } from "./format.js";
import { seriesVar, statusVar } from "./brandTheme.js";
import { t } from "./i18n.js";
import { hideTip, tipProps, type WidgetTipContent } from "./WidgetTip.js";

export type WidgetItem = { label: string; detail?: string | null; value?: string | number | null; state?: string | null; href?: string | null };
export type WidgetPart = { label: string; value: number; state?: string | null; href?: string | null };
export type WidgetFact = { label: string; value: string | number | null; state?: string | null; detail?: string | null };
export type WidgetBar = { label: string; value: number | null; detail?: string | null; state?: string | null; href?: string | null };
export type WidgetStack = { label: string; state?: string | null };
export type WidgetTile = { label: string; state?: string | null; detail?: string | null; href?: string | null };
export type WidgetTileGroup = { label?: string | null; tiles: WidgetTile[]; href?: string | null };

export type WidgetData =
  | { kind: "number"; value: number | string | null; unit?: string | null; label?: string | null; state?: string | null; href?: string | null }
  | { kind: "list"; items: WidgetItem[]; href?: string | null; empty?: string | null }
  | { kind: "split"; total?: number | null; label?: string | null; parts: WidgetPart[]; href?: string | null; empty?: string | null }
  | { kind: "series"; value?: number | string | null; unit?: string | null; label?: string | null; state?: string | null;
      /** [time in ms, value]; a null value is a gap. */
      points: Array<[number, number | null]>; href?: string | null; empty?: string | null }
  | { kind: "facts"; title?: string | null; detail?: string | null; state?: string | null; status?: string | null; facts: WidgetFact[]; href?: string | null; empty?: string | null }
  | { kind: "bars"; label?: string | null; unit?: string | null; bars: WidgetBar[]; max?: number | null;
      target?: number | null; target_label?: string | null; href?: string | null; empty?: string | null }
  | { kind: "columns"; value?: number | string | null; unit?: string | null; label?: string | null; state?: string | null;
      /** One per stack, bottom first; without them each column is one plain stack. */
      stacks?: WidgetStack[] | null;
      /** [start of the hour or day in ms, a value per stack]. */
      buckets: Array<[number, Array<number | null>]>; step?: "hour" | "day" | null;
      target?: number | null; target_label?: string | null; href?: string | null; empty?: string | null }
  | { kind: "tiles"; value?: number | string | null; label?: string | null; groups: WidgetTileGroup[];
      /** The things left out when there are more than fit. */
      more?: number | null; href?: string | null; empty?: string | null };

export const WIDGET_KINDS = ["number", "list", "split", "series", "facts", "bars", "columns", "tiles"] as const;

/** A path on this host; anything else is not drawn as a link. */
export function sameHost(href: string | null | undefined): href is string {
  return typeof href === "string" && href.startsWith("/") && !href.startsWith("//");
}

function shown(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "number" ? formatNumber(value) : value;
}

type Hover = ReturnType<typeof tipProps>;

function Linked({ href, className, children, tip }: { href?: string | null; className?: string; children: ReactNode; tip?: Hover }) {
  return sameHost(href) ? <a className={className} href={href} {...tip}>{children}</a> : <div className={className} tabIndex={tip ? 0 : undefined} {...tip}>{children}</div>;
}

const withUnit = (value: number | string | null | undefined, unit?: string | null) => `${shown(value)}${unit ? ` ${unit}` : ""}`;
const share = (value: number, total: number) => (total > 0 ? `${formatNumber((value / total) * 100, 0)} %` : "");

function More({ href, label }: { href?: string | null; label?: string }) {
  return sameHost(href) ? <a className="pc-wg-more" href={href}>{label ?? t("See all")}</a> : null;
}

export function NumberBody({ data }: { data: Extract<WidgetData, { kind: "number" }> }) {
  return <Linked href={data.href} className="pc-wg-link">
    <strong className="pc-wg-number" style={data.state ? { color: statusVar(data.state, "text") } : undefined}>{shown(data.value)}{data.unit ? <small> {data.unit}</small> : null}</strong>
    {data.label && <span className="pc-wg-label">{data.label}</span>}
  </Linked>;
}

/**
 * How many of `rows` list rows fit in the card body around `list`, measured as drawn: the rows are
 * estimated from the card's height (`listRows`), then the last ones are dropped while the body
 * still overflows. A row is never cut, at any display size; a resize measures again.
 */
function useRowsThatFit(list: RefObject<HTMLDivElement | null>, rows: number): number {
  const [shown, setShown] = useState(rows);
  useEffect(() => setShown(rows), [rows]);
  useLayoutEffect(() => {
    const body = list.current?.closest(".pc-wg-body") ?? list.current?.parentElement;
    if (!body || shown <= 1) return;
    if (body.scrollHeight > body.clientHeight + 1) setShown(shown - 1);
  });
  useEffect(() => {
    const body = list.current?.closest(".pc-wg-body");
    if (!body || typeof ResizeObserver === "undefined") return;
    let width = body.clientWidth;
    let height = body.clientHeight;
    const observer = new ResizeObserver(() => {
      if (body.clientWidth === width && body.clientHeight === height) return;
      width = body.clientWidth;
      height = body.clientHeight;
      setShown(rows); // measure again from the estimate
    });
    observer.observe(body);
    return () => observer.disconnect();
  }, [list, rows]);
  return Math.min(shown, rows);
}

export function ListBody({ data, rows }: { data: Extract<WidgetData, { kind: "list" }>; rows: number }) {
  const list = useRef<HTMLDivElement | null>(null);
  const fit = useRowsThatFit(list, rows);
  const items = Array.isArray(data.items) ? data.items.slice(0, fit) : [];
  return <div className="pc-wg-list" ref={list}>
    {!items.length && <p className="muted small">{data.empty ?? t("Nothing to show.")}</p>}
    {items.map((row, index) => <Linked key={index} href={row.href} className="pc-wg-row"
      tip={tipProps({ title: row.label, group: row.detail, color: row.state ? statusVar(row.state) : null, rows: row.value !== null && row.value !== undefined ? [["", shown(row.value)]] : [] }, true)}>
      {row.state && <span className="pc-wg-dot" style={{ background: statusVar(row.state) }} aria-hidden="true" />}
      <span className="pc-wg-row-text"><b>{row.label}</b>{row.detail && <small>{row.detail}</small>}</span>
      {row.value !== null && row.value !== undefined && <span className="pc-wg-row-value">{shown(row.value)}</span>}
    </Linked>)}
    <More href={data.href} />
  </div>;
}

/** A total split by status: the bar, then each part as a link (at two rows and more). */
export function SplitBody({ data, h }: { data: Extract<WidgetData, { kind: "split" }>; h: number }) {
  const parts = (Array.isArray(data.parts) ? data.parts : []).filter((part) => typeof part.value === "number" && part.value >= 0).slice(0, 8);
  const sum = parts.reduce((total, part) => total + part.value, 0);
  const total = typeof data.total === "number" ? data.total : sum;
  return <div className="pc-wg-split">
    <Linked href={data.href} className="pc-wg-link pc-wg-split-head">
      <strong className="pc-wg-number">{formatNumber(total, 0)}</strong>
      {data.label && <span className="pc-wg-label">{data.label}</span>}
    </Linked>
    {sum > 0
      ? <div className="pc-wg-bar" role="img" aria-label={parts.map((part) => `${part.label} ${part.value}`).join(", ")}>
        {parts.filter((part) => part.value > 0).map((part, index) => <span key={index} style={{ flexGrow: part.value, background: statusVar(part.state ?? undefined) }}
          {...tipProps({ title: part.label, group: data.label, color: statusVar(part.state ?? undefined), rows: [[formatNumber(part.value, 0), share(part.value, sum)]] })} />)}
      </div>
      : <p className="muted small">{data.empty ?? t("Nothing to show.")}</p>}
    {h > 1 && sum > 0 && <div className="pc-wg-parts">
      {parts.filter((part) => part.value > 0).map((part, index) => <Linked key={index} href={part.href} className="pc-wg-part"
        tip={tipProps({ title: part.label, group: data.label, color: statusVar(part.state ?? undefined), rows: [[formatNumber(part.value, 0), share(part.value, sum)]] })}>
        <span className="pc-wg-dot" style={{ background: statusVar(part.state ?? undefined) }} aria-hidden="true" />
        <span>{part.label}</span><b>{formatNumber(part.value, 0)}</b>
      </Linked>)}
    </div>}
  </div>;
}

const CHART_W = 300;
const MAX_STACKS = 6;
const CHART_H = 100;

/** The points as an SVG path (line and, closed, its area), on a CHART_W x CHART_H box; a null value breaks the line. */
export function seriesPaths(points: Array<[number, number | null]>): { line: string; area: string; min: number; max: number } | null {
  const valid = points.filter((point): point is [number, number] => Array.isArray(point) && Number.isFinite(point[0]) && typeof point[1] === "number" && Number.isFinite(point[1]));
  if (valid.length < 2) return null;
  const t0 = valid[0][0];
  const t1 = valid[valid.length - 1][0];
  let min = Math.min(...valid.map((point) => point[1]));
  let max = Math.max(...valid.map((point) => point[1]));
  // A flat line sits on the floor (a count that stayed at zero), not in the middle.
  if (max === min) max = min + 1;
  const x = (time: number) => (t1 === t0 ? 0 : ((time - t0) / (t1 - t0)) * CHART_W);
  // A little room above and below, so the line never touches the card's edge.
  const y = (value: number) => CHART_H - 4 - ((value - min) / (max - min)) * (CHART_H - 8);
  const runs: Array<Array<[number, number]>> = [];
  let current: Array<[number, number]> = [];
  for (const [time, value] of points) {
    if (typeof value !== "number" || !Number.isFinite(value) || !Number.isFinite(time)) { if (current.length) runs.push(current); current = []; continue; }
    current.push([x(time), y(value)]);
  }
  if (current.length) runs.push(current);
  const fmt = (n: number) => n.toFixed(1);
  const line = runs.map((run) => run.map(([px, py], index) => `${index ? "L" : "M"}${fmt(px)},${fmt(py)}`).join("")).join("");
  const area = runs.filter((run) => run.length > 1).map((run) => `M${fmt(run[0][0])},${CHART_H}${run.map(([px, py]) => `L${fmt(px)},${fmt(py)}`).join("")}L${fmt(run[run.length - 1][0])},${CHART_H}Z`).join("");
  return { line, area, min: Math.min(...valid.map((point) => point[1])), max: Math.max(...valid.map((point) => point[1])) };
}

/** The point of a series nearest to a share (0 to 1) of the chart's width, by time. */
export function nearestPoint(points: Array<[number, number | null]>, ratio: number): number | null {
  const valid = points.map((point, index) => [point, index] as const).filter(([point]) => Array.isArray(point) && Number.isFinite(point[0]) && typeof point[1] === "number" && Number.isFinite(point[1]));
  if (!valid.length) return null;
  const first = valid[0][0][0];
  const last = valid[valid.length - 1][0][0];
  const at = first + Math.max(0, Math.min(1, ratio)) * (last - first);
  return valid.reduce((best, item) => (Math.abs(item[0][0] - at) < Math.abs(best[0][0] - at) ? item : best))[1];
}

/** Where a point of the series sits across the chart (as `seriesPaths` draws it). */
function cursorX(points: Array<[number, number | null]>, index: number): number {
  const times = points.filter((point) => Array.isArray(point) && Number.isFinite(point[0]) && typeof point[1] === "number" && Number.isFinite(point[1])).map((point) => point[0]);
  const first = times[0];
  const last = times[times.length - 1];
  return last === first ? 0 : ((points[index][0] - first) / (last - first)) * CHART_W;
}

export function SeriesBody({ data, h }: { data: Extract<WidgetData, { kind: "series" }>; h: number }) {
  const all = Array.isArray(data.points) ? data.points : [];
  const paths = seriesPaths(all);
  const [hover, setHover] = useState<number | null>(null);
  const tone = data.state ? statusVar(data.state) : "var(--pc-primary)";
  if (!paths && (data.value === null || data.value === undefined)) {
    return <div className="pc-wg-series">
      {data.label && <span className="pc-wg-label">{data.label}</span>}
      <p className="muted small">{data.empty ?? t("No history yet.")}</p>
      <More href={data.href} label={t("Open")} />
    </div>;
  }
  return <div className={`pc-wg-series pc-wg-series-h${h}`}>
    <Linked href={data.href} className="pc-wg-link pc-wg-series-head">
      <strong className="pc-wg-number" style={data.state ? { color: statusVar(data.state, "text") } : undefined}>{shown(data.value)}{data.unit ? <small> {data.unit}</small> : null}</strong>
      {data.label && <span className="pc-wg-label">{data.label}</span>}
    </Linked>
    {paths
      ? <svg className="pc-wg-chart" viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" role="img" aria-label={t("From {min} to {max}", { min: formatNumber(paths.min), max: formatNumber(paths.max) })}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const index = nearestPoint(all, box.width ? (event.clientX - box.left) / box.width : 0);
          setHover(index);
          if (index === null) { hideTip(); return; }
          const [at, value] = all[index];
          tipProps({ title: withUnit(value, data.unit), group: data.label, color: tone, rows: [["", formatDate(at)]] }).onMouseMove(event);
        }}
        onMouseLeave={() => { setHover(null); hideTip(); }}>
        <path d={paths.area} fill={tone} opacity={0.14} />
        <path d={paths.line} fill="none" stroke={tone} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {hover !== null && <line className="pc-wg-cursor" x1={cursorX(all, hover)} x2={cursorX(all, hover)} y1={0} y2={CHART_H} vectorEffect="non-scaling-stroke" />}
      </svg>
      : <p className="muted small">{data.empty ?? t("No history yet.")}</p>}
  </div>;
}

/** The facts' columns on a card `w` columns wide: two from 5 columns, four from 10. */
export function factColumns(w: number): number {
  return w >= 10 ? 4 : w >= 5 ? 2 : 1;
}

/** How many facts fit a card `h` rows high, `w` columns wide. */
export function factCount(w: number, h: number): number {
  if (h <= 1) return 0;
  return (h === 2 ? 2 : 4) * factColumns(w);
}

export function FactsBody({ data, w, h }: { data: Extract<WidgetData, { kind: "facts" }>; w: number; h: number }) {
  const facts = (Array.isArray(data.facts) ? data.facts : []).slice(0, factCount(w, h));
  if (!data.title && !facts.length) return <p className="muted small">{data.empty ?? t("Nothing to show.")}</p>;
  return <div className="pc-wg-facts">
    <Linked href={data.href} className="pc-wg-link pc-wg-facts-head">
      {data.state && <span className="pc-wg-dot" style={{ background: statusVar(data.state) }} aria-hidden="true" />}
      <span className="pc-wg-row-text"><b>{data.title ?? "—"}</b>{(data.status || data.detail) && <small>{[data.status, data.detail].filter(Boolean).join(" · ")}</small>}</span>
    </Linked>
    {facts.length > 0 && <dl className="pc-wg-fact-grid" style={{ gridTemplateColumns: `repeat(${factColumns(w)}, minmax(0, 1fr))` }}>
      {facts.map((fact, index) => <div key={index} className="pc-wg-fact" {...tipProps({ title: fact.label, group: data.title, rows: fact.detail ? [["", shown(fact.value)], ["", fact.detail]] : [["", shown(fact.value)]] }, !fact.detail)}>
        <dt>{fact.label}</dt>
        <dd style={fact.state ? { color: statusVar(fact.state, "text") } : undefined}>{shown(fact.value)}</dd>
      </div>)}
    </dl>}
  </div>;
}

/** How many bars fit a card `h` rows high (a bar is a name, its value and a thin bar; a line
 * below the name, drawn from three rows, takes room for one bar). */
export function barCount(h: number, details = false): number {
  return h <= 1 ? 1 : h === 2 ? 3 : details ? 4 : 5;
}

/** Each bar's length as a share of the longest bar, the `max` or the target, whichever is largest. */
export function barScale(bars: WidgetBar[], max?: number | null, target?: number | null): number {
  const values = bars.map((bar) => (typeof bar.value === "number" && Number.isFinite(bar.value) ? bar.value : 0));
  const top = Math.max(0, ...values, typeof max === "number" && Number.isFinite(max) ? max : 0, typeof target === "number" && Number.isFinite(target) ? target : 0);
  return top > 0 ? top : 1;
}

export function BarsBody({ data, h }: { data: Extract<WidgetData, { kind: "bars" }>; h: number }) {
  const bars = (Array.isArray(data.bars) ? data.bars : []).slice(0, barCount(h, (Array.isArray(data.bars) ? data.bars : []).some((bar) => Boolean(bar?.detail))));
  const scale = barScale(bars, data.max, data.target);
  const target = typeof data.target === "number" && Number.isFinite(data.target) ? (data.target / scale) * 100 : null;
  return <div className="pc-wg-bars">
    {data.label && <span className="pc-wg-label">{data.label}</span>}
    {!bars.length && <p className="muted small">{data.empty ?? t("Nothing to show.")}</p>}
    {bars.map((bar, index) => {
      const share = typeof bar.value === "number" && Number.isFinite(bar.value) ? Math.max(0, Math.min(100, (bar.value / scale) * 100)) : 0;
      const rows: Array<[string, string]> = [[data.label ?? "", withUnit(bar.value, data.unit)]];
      if (typeof data.target === "number" && data.target_label) rows.push([data.target_label, withUnit(data.target, data.unit)]);
      return <Linked key={index} href={bar.href} className="pc-wg-barrow"
        tip={tipProps({ title: bar.label, group: bar.detail, color: bar.state ? statusVar(bar.state) : null, rows })}>
        <span className="pc-wg-barrow-text"><b>{bar.label}</b>{bar.detail && h > 2 && <small>{bar.detail}</small>}</span>
        <span className="pc-wg-row-value">{shown(bar.value)}{data.unit ? <small> {data.unit}</small> : null}</span>
        <span className="pc-wg-track" aria-hidden="true">
          <span style={{ width: `${share}%`, background: bar.state ? statusVar(bar.state) : "var(--pc-primary)" }} />
          {target !== null && <i className="pc-wg-target" style={{ left: `${Math.min(100, target)}%` }} />}
        </span>
      </Linked>;
    })}
    {target !== null && data.target_label && <small className="pc-wg-target-note"><i aria-hidden="true" />{data.target_label}</small>}
    <More href={data.href} />
  </div>;
}

/** The stacked columns on a CHART_W x CHART_H box: a rectangle per stack part and the target's height. */
export function columnRects(buckets: Array<[number, Array<number | null>]>, stacks: number, target?: number | null): { rects: Array<{ x: number; y: number; w: number; h: number; stack: number; bucket: number }>; top: number; targetY: number | null } | null {
  const valid = (Array.isArray(buckets) ? buckets : []).filter((bucket) => Array.isArray(bucket) && Array.isArray(bucket[1]));
  if (!valid.length) return null;
  const sums = valid.map(([, values]) => values.slice(0, stacks).reduce<number>((total, value) => total + (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0), 0));
  const goal = typeof target === "number" && Number.isFinite(target) && target > 0 ? target : null;
  const top = Math.max(...sums, goal ?? 0) || 1;
  const slot = CHART_W / valid.length;
  const gap = Math.min(4, slot * 0.25);
  const rects: Array<{ x: number; y: number; w: number; h: number; stack: number; bucket: number }> = [];
  valid.forEach(([, values], bucket) => {
    let base = CHART_H;
    values.slice(0, stacks).forEach((value, stack) => {
      if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return;
      const height = (value / top) * (CHART_H - 4);
      base -= height;
      rects.push({ x: bucket * slot + gap / 2, y: base, w: Math.max(0.5, slot - gap), h: height, stack, bucket });
    });
  });
  return { rects, top, targetY: goal === null ? null : CHART_H - (goal / top) * (CHART_H - 4) };
}

function bucketLabel(at: number, step: "hour" | "day" | null | undefined): string {
  if (!Number.isFinite(at)) return "";
  return formatDate(at, step === "day" ? { day: "numeric", month: "short" } : { hour: "2-digit", minute: "2-digit" });
}

/** A column's time in its note: the hour it covers ("27 Oct, 14:00 – 15:00") or its day. */
function bucketTitle(at: number, step: "hour" | "day" | null | undefined): string {
  if (!Number.isFinite(at)) return "";
  if (step === "day") return formatDate(at, { weekday: "short", day: "numeric", month: "short" });
  if (step === "hour") return `${formatDate(at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} – ${formatDate(at + 3_600_000, { hour: "2-digit", minute: "2-digit" })}`;
  return formatDate(at);
}

export function ColumnsBody({ data, h }: { data: Extract<WidgetData, { kind: "columns" }>; h: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const stacks: WidgetStack[] = Array.isArray(data.stacks) && data.stacks.length ? data.stacks.slice(0, MAX_STACKS) : [{ label: data.label ?? "" }];
  const buckets = Array.isArray(data.buckets) ? data.buckets : [];
  const chart = columnRects(buckets, stacks.length, data.target);
  const fill = (stack: number) => (stacks[stack]?.state ? statusVar(stacks[stack].state ?? undefined) : stacks.length > 1 ? seriesVar(stack) : "var(--pc-primary)");
  const head = <Linked href={data.href} className="pc-wg-link pc-wg-series-head">
    <strong className="pc-wg-number" style={data.state ? { color: statusVar(data.state, "text") } : undefined}>{shown(data.value)}{data.unit ? <small> {data.unit}</small> : null}</strong>
    {data.label && <span className="pc-wg-label">{data.label}</span>}
  </Linked>;
  if (!chart || (!chart.rects.length && data.target == null)) {
    return <div className="pc-wg-series">{data.value !== undefined && data.value !== null ? head : data.label && <span className="pc-wg-label">{data.label}</span>}<p className="muted small">{data.empty ?? t("Nothing to show.")}</p></div>;
  }
  const first = buckets[0]?.[0];
  const last = buckets[buckets.length - 1]?.[0];
  const slot = CHART_W / Math.max(1, buckets.length);
  // A column's note: its hour or day, each stack's count (bottom first) and the target.
  const said = (bucket: number): WidgetTipContent => {
    const [at, values] = buckets[bucket];
    const parts = stacks.map((stack, index) => [Array.isArray(data.stacks) && data.stacks.length ? stack.label : "", values[index]] as const).filter(([, value]) => typeof value === "number");
    const rows: Array<[string, string]> = parts.map(([label, value]) => [label, withUnit(value, data.unit)]);
    if (parts.length > 1) rows.push([t("Total"), withUnit(parts.reduce((total, [, value]) => total + (value ?? 0), 0), data.unit)]);
    if (!rows.length) rows.push(["", withUnit(0, data.unit)]);
    if (data.target != null && data.target_label) rows.push([data.target_label, withUnit(data.target, data.unit)]);
    return { title: bucketTitle(at, data.step), rows };
  };
  return <div className={`pc-wg-series pc-wg-columns pc-wg-series-h${h}`}>
    {head}
    <svg className="pc-wg-chart" viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" role="img"
      aria-label={t("{count} columns, highest {top}", { count: buckets.length, top: formatNumber(chart.top) })} onMouseLeave={() => { setHover(null); hideTip(); }}>
      {chart.rects.map((rect, index) => <rect key={index} x={rect.x} y={rect.y} width={rect.w} height={rect.h} fill={fill(rect.stack)} opacity={hover === null || hover === rect.bucket ? 1 : 0.55} />)}
      {buckets.map((_, bucket) => <rect key={`hit-${bucket}`} className="pc-wg-hit" x={bucket * slot} y={0} width={slot} height={CHART_H} fill="transparent"
        onMouseEnter={(event) => { setHover(bucket); tipProps(said(bucket)).onMouseEnter(event); }}
        onMouseMove={(event) => tipProps(said(bucket)).onMouseMove(event)} />)}
      {chart.targetY !== null && <line x1={0} x2={CHART_W} y1={chart.targetY} y2={chart.targetY} stroke="var(--pc-text-3)" strokeWidth={1.5} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
    </svg>
    {h > 1 && <div className="pc-wg-columns-foot">
      <span>{bucketLabel(first, data.step)}</span>
      {(stacks.length > 1 || data.target_label) && <span className="pc-wg-columns-keys">
        {stacks.length > 1 && stacks.map((stack, index) => <span key={index}><i style={{ background: fill(index) }} aria-hidden="true" />{stack.label}</span>)}
        {data.target_label && data.target != null && <span><i className="pc-wg-key-target" aria-hidden="true" />{data.target_label}</span>}
      </span>}
      <span>{bucketLabel(last, data.step)}</span>
    </div>}
  </div>;
}

/** A square's side in pixels: smaller as there are more of them, so a plant's loops fit one card. */
export function tileSide(count: number, h: number, groups = 1): number {
  const room = h <= 1 ? 0.4 : h === 2 ? 1 : 1.8;
  // A group's name takes about a row of squares.
  const per = (count + Math.max(0, groups - 1) * 16) / room;
  return per > 600 ? 7 : per > 300 ? 9 : per > 120 ? 12 : 16;
}

/** A square's detail in the note, one line per part ("Collecting · Feed flow" is two). */
function tileRows(detail: string): Array<[string, string]> {
  return detail.split(" · ").filter(Boolean).map((part) => ["", part]);
}

export function TilesBody({ data, h }: { data: Extract<WidgetData, { kind: "tiles" }>; h: number }) {
  const groups = (Array.isArray(data.groups) ? data.groups : []).filter((group) => group && Array.isArray(group.tiles) && group.tiles.length);
  const count = groups.reduce((total, group) => total + group.tiles.length, 0);
  const side = tileSide(count, h, groups.length);
  const states = new Map<string, number>();
  groups.forEach((group) => group.tiles.forEach((tile) => states.set(tile.state ?? "unknown", (states.get(tile.state ?? "unknown") ?? 0) + 1)));
  return <div className="pc-wg-tiles" style={{ ["--pc-wg-tile" as string]: `${side}px` }}>
    {(data.value !== undefined && data.value !== null || data.label) && <Linked href={data.href} className="pc-wg-link pc-wg-split-head">
      {data.value !== undefined && data.value !== null && <strong className="pc-wg-number">{shown(data.value)}</strong>}
      {data.label && <span className="pc-wg-label">{data.label}</span>}
    </Linked>}
    {!count && <p className="muted small">{data.empty ?? t("Nothing to show.")}</p>}
    {count > 0 && <div className="pc-wg-tile-groups">
      {groups.map((group, index) => <div key={index} className="pc-wg-tile-group">
        {group.label && <Linked href={group.href} className="pc-wg-tile-name">{group.label}</Linked>}
        <div className="pc-wg-tile-set">
          {group.tiles.map((tile, at) => {
            const name = [tile.label, tile.detail].filter(Boolean).join(" · ");
            const style = { background: statusVar(tile.state ?? undefined) };
            const tip = tipProps({ title: tile.label, group: group.label, color: statusVar(tile.state ?? undefined), rows: tile.detail ? tileRows(tile.detail) : [] });
            return sameHost(tile.href)
              ? <a key={at} href={tile.href} className="pc-wg-square" style={style} aria-label={name} {...tip} />
              : <span key={at} className="pc-wg-square" style={style} aria-label={name} role="img" tabIndex={0} {...tip} />;
          })}
        </div>
      </div>)}
      {typeof data.more === "number" && data.more > 0 && <small className="muted">{t("and {count} more", { count: data.more })}</small>}
    </div>}
  </div>;
}

/** One published widget's data, drawn in the shape it names; an unknown shape says so. */
export function WidgetBody({ data, w, h, rows }: { data: WidgetData; w: number; h: number; rows: number }) {
  switch (data?.kind) {
    case "number": return <NumberBody data={data} />;
    case "list": return <ListBody data={data} rows={rows} />;
    case "split": return <SplitBody data={data} h={h} />;
    case "series": return <SeriesBody data={data} h={h} />;
    case "facts": return <FactsBody data={data} w={w} h={h} />;
    case "bars": return <BarsBody data={data} h={h} />;
    case "columns": return <ColumnsBody data={data} h={h} />;
    case "tiles": return <TilesBody data={data} h={h} />;
    default: return <p className="muted small">{t("This widget needs a newer PlantCraft.")}</p>;
  }
}
