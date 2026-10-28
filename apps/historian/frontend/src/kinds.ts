/** How a point's kind (histcraft/kinds.py) is drawn on a trend. */
import { t } from "./i18n";
import type { PointKind } from "./types";

export const KIND_LABELS: Record<PointKind, string> = {
  number: "number",
  integer: "integer",
  boolean: "on/off",
  text: "text",
  instant: "time",
  structured: "structured",
  runs: "one series per run",
};

/** A kind's label for a table or a form ("number", "on/off", "time"...). */
export const kindLabel = (kind: string) => t(KIND_LABELS[kind as PointKind] ?? kind);

/** Values read as a trend draws them: numbers (true/false as 1/0), or labels for text, times
 * and structured values. */
export function plotted(kind: string, values: readonly unknown[]): { v: (number | string | null)[]; text: boolean } {
  const label = kind === "text" || kind === "instant" || kind === "structured";
  return {
    text: label,
    v: values.map((value) => {
      if (value === null || value === undefined) return null;
      if (typeof value === "boolean") return value ? 1 : 0;
      if (typeof value === "number" || typeof value === "string") return value;
      return JSON.stringify(value);
    }),
  };
}
