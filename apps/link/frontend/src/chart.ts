import type { Shape } from "plotly.js";
import { markStrip, wallClock } from "@plantcraft/ui";
import type { CheckResult } from "./types";

/** Plotly reads times without a zone: ISO UTC -> "YYYY-MM-DD HH:MM:SS.sss" on the wall clock
 * of the zone every page shows times in (the installation's, or the person's choice). */
export function plotTime(value: string): string {
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? value : wallClock(ms);
}

/** Marked stretches (`markStrip`) for the events of failing checks; instants are widened to stay visible. */
export function eventShapes(results: CheckResult[], colorOf: (check: string) => string, start: string, end: string): Partial<Shape>[] {
  const from = Date.parse(start);
  const to = Date.parse(end);
  const minimum = Number.isFinite(from) && Number.isFinite(to) ? Math.max(0, (to - from) * 0.004) : 0;
  return results.filter((item) => item.status === "warning" || item.status === "bad").flatMap((item) =>
    (item.events ?? []).map((event) => {
      let x0 = Date.parse(event.start_time);
      let x1 = Date.parse(event.end_time || event.start_time);
      if (x1 - x0 < minimum) { const middle = (x0 + x1) / 2; x0 = middle - minimum / 2; x1 = middle + minimum / 2; }
      return markStrip(plotTime(new Date(x0).toISOString()), plotTime(new Date(x1).toISOString()), colorOf(item.check));
    }).flat());
}

/** Where the controller output spent the window: a loop that lives near 0 or 100% is saturated,
 * one squeezed into a few percent has little room left (A9 of the 0.6 list). */
export function opBins(values: Array<number | null | undefined>, width = 5): { x: number[]; y: number[] } {
  const found = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const count = Math.ceil(100 / width);
  const y = new Array<number>(count).fill(0);
  for (const value of found) y[Math.min(count - 1, Math.max(0, Math.floor(value / width)))] += 1;
  return { x: y.map((_, index) => index * width + width / 2), y: y.map((n) => (found.length ? (100 * n) / found.length : 0)) };
}
