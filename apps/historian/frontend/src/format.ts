import { locale } from "./i18n";
import { formatDate } from "@plantcraft/ui";

/** Milliseconds since the epoch as a date and time where times are shown (plant or device). */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : formatDate(value, { dateStyle: "medium", timeStyle: "medium" });
}

/** How long ago, in words a person reads at a glance. */
export function ago(value: number | null | undefined, now = Date.now()): string {
  if (value === null || value === undefined) return "—";
  const seconds = Math.max(0, Math.round((now - value) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toLocaleString(locale, { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(locale);
}

export function formatValue(value: unknown, unit = ""): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  // A structured value (JSON object or array), shortened for a table cell.
  if (typeof value !== "number") { const text = JSON.stringify(value); return text.length > 80 ? `${text.slice(0, 79)}…` : text; }
  const digits = Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 4;
  return `${value.toLocaleString(locale, { maximumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
}
