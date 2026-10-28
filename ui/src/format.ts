/** Numbers, dates and durations as every app of the suite writes them. */
import { t, uiLocale } from "./i18n.js";
import { displayTimeZone, zoneSuffix } from "./timeZone.js";

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString(uiLocale(), { maximumFractionDigits: digits });
}

/** A measured value as an engineer reads it: 4 significant digits, then the unit ("12.35 bar"). */
export function formatReading(value: number | null | undefined, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  return `${Number(value.toPrecision(4))}${unit ? ` ${unit}` : ""}`;
}

function parseUtc(value: string): number {
  return new Date(value.includes("T") || value.endsWith("Z") ? value : `${value.replace(" ", "T")}Z`).getTime();
}

/**
 * A UTC time from the API as "20 Oct 2026, 14:05" in local time: the plant's time zone, or the
 * device's when the person chose it (see timeZone.ts). "UTC" (or "UTC−3" for a fixed offset) is written when that is the zone.
 * `options` narrows it ({ dateStyle: "medium" } for the day only, { timeStyle: "medium" }…).
 */
export function formatDate(value: string | number | Date | null | undefined, options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" }): string {
  if (value === null || value === undefined || value === "") return "—";
  const stamp = typeof value === "string" ? parseUtc(value) : new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value);
  const zone = displayTimeZone();
  const text = new Date(stamp).toLocaleString(uiLocale(), { ...options, timeZone: zone });
  const hasTime = Boolean(options.timeStyle || options.hour || options.minute);
  const suffix = hasTime ? zoneSuffix(zone) : "";
  return suffix ? `${text} ${suffix}` : text;
}

/** "15 min ago" for a past time (absolute date beyond a week). */
export function formatAgo(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return "—";
  const stamp = parseUtc(value);
  if (Number.isNaN(stamp)) return value;
  const minutes = Math.round((now - stamp) / 60_000);
  if (minutes < 1) return t("just now");
  if (minutes < 60) return t("{n} min ago", { n: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 48) return t("{n} h ago", { n: hours });
  const days = Math.round(hours / 24);
  if (days <= 7) return t("{n} days ago", { n: days });
  return formatDate(value);
}

/** A 0-1 share as a percentage. */
export function formatShare(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${formatNumber(100 * value, digits)}%`;
}

/** Seconds as "0.7 s", "3 min", "1.2 h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 90) return t("{n} s", { n: formatNumber(seconds, 1) });
  if (seconds < 5400) return t("{n} min", { n: formatNumber(seconds / 60, 1) });
  return t("{n} h", { n: formatNumber(seconds / 3600, 1) });
}
