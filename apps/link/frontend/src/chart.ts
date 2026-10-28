import type { Shape } from "plotly.js";
import { wallClock } from "@plantcraft/ui";
import type { CheckResult } from "./types";

/** Plotly reads times without a zone: ISO UTC -> "YYYY-MM-DD HH:MM:SS.sss" on the wall clock
 * of the zone every page shows times in (the installation's, or the person's choice). */
export function plotTime(value: string): string {
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? value : wallClock(ms);
}

/** Shaded spans for the events of failing checks; instants are widened to stay visible. */
export function eventShapes(results: CheckResult[], colorOf: (check: string) => string, start: string, end: string): Partial<Shape>[] {
  const from = Date.parse(start);
  const to = Date.parse(end);
  const minimum = Number.isFinite(from) && Number.isFinite(to) ? Math.max(0, (to - from) * 0.004) : 0;
  return results.filter((item) => item.status === "warning" || item.status === "bad").flatMap((item) =>
    (item.events ?? []).map((event) => {
      let x0 = Date.parse(event.start_time);
      let x1 = Date.parse(event.end_time || event.start_time);
      if (x1 - x0 < minimum) { const middle = (x0 + x1) / 2; x0 = middle - minimum / 2; x1 = middle + minimum / 2; }
      return {
        type: "rect" as const, xref: "x" as const, yref: "paper" as const, x0: plotTime(new Date(x0).toISOString()), x1: plotTime(new Date(x1).toISOString()),
        y0: 0, y1: 1, fillcolor: colorOf(item.check), opacity: 0.22, line: { width: 0 }, layer: "below" as const,
      };
    }));
}
