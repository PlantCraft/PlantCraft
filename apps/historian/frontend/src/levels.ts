/** Settings in three levels, the most specific wins (app standard, D8): general, source, point. */
import { formatBytes, formatValue } from "./format";
import { formatNumber, t } from "./i18n";
import type { Forecast, Origin } from "./types";

export const ORIGIN_LABELS: Record<Origin, string> = {
  point: "set on this signal",
  source: "from the source",
  general: "from general settings",
  profile: "from the profile",
};

/** The compression profiles a point picks (D1); "custom" is a point's own deviation. */
export const PROFILE_LABELS: Record<string, string> = {
  "": "Standard (0.1 % exception, 0.2 % compression of the span)",
  fine: "Fine (0.05 % and 0.1 %)",
  none: "No compression (every change)",
  custom: "Custom",
};

/** The profile a point shows: its own deviation or exception make it custom. */
export function profileOf(point: { profile: string; own: Record<string, number | null> }): string {
  if (point.profile) return point.profile;
  return point.own.deviation !== null || point.own.exception !== null ? "custom" : "";
}

/** Where a number point's range comes from (D2): the server's, a person's, or suggested from its first day. */
export type RangeOrigin = "source" | "edited" | "suggested" | "";
const RANGE_NOTES: Record<RangeOrigin, string> = {
  source: "From the server (OPC UA EURange, PI Zero and Span).",
  edited: "Set by a person.",
  suggested: "Suggested from the first day of values: confirm it or change it.",
  "": "No range yet: one is suggested after a day of values. Until then the compression is a share of the value.",
};
export function rangeNote(origin: RangeOrigin | undefined): string {
  return t(RANGE_NOTES[origin ?? ""] ?? RANGE_NOTES[""]);
}

/** "400 days, from general settings": a value in effect and where it comes from. */
export function effective(value: number, unit: string, origin: Origin): string {
  // A retention of 0 days keeps the values forever.
  if (value === 0 && unit === t("days")) return t("{value}, {origin}", { value: t("forever"), origin: t(ORIGIN_LABELS[origin] ?? origin) });
  return t("{value}, {origin}", { value: unit ? `${formatNumber(value, 4)} ${unit}` : formatNumber(value, 4), origin: t(ORIGIN_LABELS[origin] ?? origin) });
}

/** How a point is compressed: "± 0.2 bar", "± 0.1 % of the value" (no known range) or "every change",
 * with its exception first when it has one ("exception ± 0.1 bar, ± 0.2 bar"). */
export function compression(point: { kind: string; deviation: number; deviation_percent?: number | null; exception?: number; exception_percent?: number | null; unit: string }): string {
  if (point.kind !== "number") return t("every change");
  const share = (value: number | null | undefined, fixed: number | undefined) => (value ? t("± {percent} % of the value", { percent: formatNumber(value, 4) }) : fixed ? `± ${formatValue(fixed, point.unit)}` : "");
  const main = share(point.deviation_percent, point.deviation) || t("every change");
  const exception = share(point.exception_percent, point.exception);
  return exception ? t("exception {exception}, {compression}", { exception, compression: main }) : main;
}

/** A form field of an optional override: empty inherits (null); anything else is a number. */
export function override(text: string | undefined): number | null {
  if (text === undefined || text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** "13 GB a year; the disk is full in 4 years": the archive's growth and the free disk (D4). */
export function forecastLine(forecast: Forecast): { text: string; warn: boolean } {
  const growth = t("The archive grows {size} a year", { size: formatBytes(forecast.bytes_per_year) });
  if (forecast.free_bytes === null) return { text: t("{growth}; the free disk is not known.", { growth }), warn: false };
  const days = forecast.days_to_full;
  if (days === null) return { text: t("{growth}; with the retentions set it stops before the {free} free are used.", { growth, free: formatBytes(forecast.free_bytes) }), warn: false };
  const when = days >= 730 ? t("{count} years", { count: formatNumber(days / 365, 1) }) : t("{count} days", { count: formatNumber(Math.floor(days), 0) });
  return { text: t("{growth}; the disk ({free} free) is full in {when}.", { growth, free: formatBytes(forecast.free_bytes), when }), warn: days < forecast.alert_days };
}

/** "user:ana, group:operations" as the list the API takes (a bare name is a user). */
export function ownerList(text: string): string[] {
  return text.split(/[,;\s]+/).map((item) => item.trim().toLowerCase()).filter(Boolean).map((item) => (item.includes(":") ? item : `user:${item}`));
}
