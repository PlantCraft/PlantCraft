/**
 * Where times are shown. The suite stores and computes every time in UTC; screens show it in
 * local time: the installation's time zone by default (Setup › Installation,
 * which the platform hands to the browser in the `processcraft_time_zone` cookie), or, when the
 * person picks it in their Preferences, UTC or the time zone of their own device (owner,
 * 2026-10-24: "Local time" and UTC first, never a long list of countries to start with).
 */

/** "plant" is the installation's local time (the default). */
export type TimeZoneMode = "plant" | "utc" | "device";

/** What a form saves for "the installation's local time": resolved where it is used, so a
 * schedule follows the installation when its zone changes (D1). */
export const LOCAL_ZONE = "local";

export const TIME_ZONE_COOKIE = "processcraft_time_zone";
export const TIME_ZONE_MODE_KEY = "processcraft.timeZoneMode";

let plantOverride: string | null = null;
let modeOverride: TimeZoneMode | null = null;

function validZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

function cookieZone(): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name !== TIME_ZONE_COOKIE) continue;
    const value = decodeURIComponent(rest.join("=")).replace(/^"|"$/g, "");
    return value && validZone(value) ? value : null;
  }
  return null;
}

/** The device's own IANA time zone ("UTC" when the browser does not say). */
export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** The plant's time zone, as the platform set it (UTC when it said nothing). */
export function plantTimeZone(): string {
  return plantOverride ?? cookieZone() ?? "UTC";
}

function isMode(value: unknown): value is TimeZoneMode {
  return value === "plant" || value === "utc" || value === "device";
}

/** Whether times follow the installation, UTC or this device. */
export function timeZoneMode(): TimeZoneMode {
  if (modeOverride) return modeOverride;
  try {
    const stored = window.localStorage.getItem(TIME_ZONE_MODE_KEY);
    return isMode(stored) ? stored : "plant";
  } catch {
    return "plant";
  }
}

/** Show times in the installation's zone, UTC or this device's; the page reloads so every time follows. */
export function setTimeZoneMode(mode: TimeZoneMode, reload = true): void {
  try {
    window.localStorage.setItem(TIME_ZONE_MODE_KEY, mode);
  } catch {
    modeOverride = mode;
  }
  if (reload && typeof window !== "undefined") window.location.reload();
}

/** For tests and for an app that knows the plant's zone another way. */
export function configureTimeZone(options: { plant?: string | null; mode?: TimeZoneMode | null }): void {
  if (options.plant !== undefined) plantOverride = options.plant && validZone(options.plant) ? options.plant : null;
  if (options.mode !== undefined) modeOverride = options.mode;
  offsets.clear();
}

/** The IANA zone the screens show times in. */
export function displayTimeZone(): string {
  const mode = timeZoneMode();
  return mode === "device" ? deviceTimeZone() : mode === "utc" ? "UTC" : plantTimeZone();
}

/** The IANA zone a saved value means: "local" (or nothing) is the installation's. */
export function resolveTimeZone(value: string | null | undefined): string {
  const zone = (value ?? "").trim();
  if (!zone || zone === LOCAL_ZONE) return plantTimeZone();
  return validZone(zone) ? zone : plantTimeZone();
}

/** Whether `zone` is UTC under one of its names. */
export function isUtc(zone: string): boolean {
  return zone === "UTC" || zone === "Etc/UTC" || zone === "Etc/GMT" || zone === "GMT";
}

const offsets = new Map<string, number>();
const HOUR = 3_600_000;

/** Milliseconds `zone` is ahead of UTC at `ms` (cached per hour; zones change on the hour). */
export function zoneOffset(ms: number, zone = displayTimeZone()): number {
  if (isUtc(zone)) return 0;
  const hour = Math.floor(ms / HOUR);
  const key = `${zone}|${hour}`;
  const known = offsets.get(key);
  if (known !== undefined) return known;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(new Date(hour * HOUR));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const wall = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour") % 24, get("minute"), get("second"));
  const offset = wall - hour * HOUR;
  if (offsets.size > 5000) offsets.clear();
  offsets.set(key, offset);
  return offset;
}

/** `ms` as the wall clock in the display zone: "2026-10-23 14:05:00.000". */
export function wallClock(ms: number, zone = displayTimeZone()): string {
  return new Date(ms + zoneOffset(ms, zone)).toISOString().slice(0, 23).replace("T", " ");
}

/** A wall-clock time in the display zone ("2026-10-23T14:05", as charts and inputs give it) as epoch ms. */
export function fromWallClock(text: string, zone = displayTimeZone()): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?)?$/.exec(text.trim());
  if (!match) return Number.NaN;
  const [, y, mo, d, h = "0", mi = "0", s = "0", frac = "0"] = match;
  const naive = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), Number(frac.padEnd(3, "0")));
  // Two passes settle the offset across a daylight-saving change.
  const first = naive - zoneOffset(naive, zone);
  return naive - zoneOffset(first, zone);
}

const STAMP = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

/** A UTC time from the API (ISO with Z or an offset) as display wall clock; anything else as it is. */
export function displayStamp<T>(value: T): T | string {
  if (typeof value !== "string" || !STAMP.test(value)) return value;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? value : wallClock(ms);
}

/**
 * A UTC time from the API as a file (CSV) writes it for people: "2026-10-23 11:05:00" on the
 * display zone's wall clock, to the second; `fileTimeHeader` names that zone in the column
 * header ("time (UTC−3)"). Anything that is not a time stays as it is.
 */
export function fileTime<T>(value: T): T | string {
  if (typeof value !== "string" || !STAMP.test(value)) return value;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? value : wallClock(ms).slice(0, 19);
}

/** A time column's header in a file: "time (UTC−3)", "time (UTC)". */
export function fileTimeHeader(name = "time"): string {
  return `${name} (${offsetLabel(displayTimeZone())})`;
}

/** A moment as a file name part on the display zone's wall clock: "202610231105". */
export function fileStamp(value: string): string {
  const ms = Date.parse(value);
  return (Number.isNaN(ms) ? value : wallClock(ms)).slice(0, 16).replace(/[^0-9]/g, "");
}

function mapValues(values: unknown): unknown {
  if (!Array.isArray(values) || values.length === 0) return values;
  const first = values.find((value) => value !== null && value !== undefined);
  if (typeof first !== "string" || !STAMP.test(first)) return values;
  return values.map(displayStamp);
}

type Figure = { data?: unknown[]; layout?: Record<string, unknown> };

/**
 * A Plotly figure with its UTC times moved to the display zone. Plotly draws a time string as
 * the wall clock it reads, ignoring "Z", so every trace's `x`, the shapes and annotations and the
 * x axes' ranges are rewritten. Strings without a zone are left as the app wrote them.
 */
export function zonedFigure<F extends Figure>(figure: F): F {
  if (isUtc(displayTimeZone())) return figure;
  const data = figure.data?.map((trace) => {
    if (!trace || typeof trace !== "object") return trace;
    const row = trace as Record<string, unknown>;
    const x = mapValues(row.x), base = mapValues(row.base);
    return x === row.x && base === row.base ? trace : { ...row, x, base };
  });
  let layout = figure.layout;
  if (layout) {
    layout = { ...layout };
    for (const key of Object.keys(layout)) {
      if (!/^xaxis\d*$/.test(key)) continue;
      const axis = layout[key] as Record<string, unknown> | undefined;
      if (axis && Array.isArray(axis.range)) layout[key] = { ...axis, range: axis.range.map(displayStamp) };
    }
    if (Array.isArray(layout.shapes)) layout.shapes = layout.shapes.map((shape: Record<string, unknown>) => ({ ...shape, x0: displayStamp(shape.x0), x1: displayStamp(shape.x1) }));
    if (Array.isArray(layout.annotations)) layout.annotations = layout.annotations.map((note: Record<string, unknown>) => ({ ...note, x: displayStamp(note.x) }));
  }
  return { ...figure, data, layout };
}

const MINUS = "\u2212";

/** "UTC−3", "UTC+5:30" or "UTC": how far `zone` is from UTC at `ms` (now by default). */
export function offsetLabel(zone: string, ms = Date.now()): string {
  const minutes = Math.round(zoneOffset(ms, resolveTimeZone(zone)) / 60_000);
  if (!minutes) return "UTC";
  const hours = Math.floor(Math.abs(minutes) / 60), rest = Math.abs(minutes) % 60;
  return `UTC${minutes < 0 ? MINUS : "+"}${hours}${rest ? `:${String(rest).padStart(2, "0")}` : ""}`;
}

/** The fixed offsets, west to east of UTC: Etc/GMT+3 is UTC−3 (POSIX signs are reversed). */
export function fixedOffsetZones(): string[] {
  const west = Array.from({ length: 12 }, (_, index) => `Etc/GMT+${index + 1}`);
  const east = Array.from({ length: 14 }, (_, index) => `Etc/GMT-${index + 1}`);
  return [...west, ...east];
}

/** Whether `zone` is one of the fixed offsets (no daylight saving). */
export function isFixedOffset(zone: string): boolean {
  return /^Etc\/GMT[+-]\d{1,2}$/.test(zone);
}

// The zone ids drop the accents of the cities people know with them.
const CITY_ACCENTS: Record<string, string> = {
  "Sao Paulo": "São Paulo", Belem: "Belém", Maceio: "Maceió", Cuiaba: "Cuiabá", Araguaina: "Araguaína",
  Santarem: "Santarém", Bogota: "Bogotá", Asuncion: "Asunción", Merida: "Mérida", Reykjavik: "Reykjavík",
};

/** "São Paulo" from "America/Sao_Paulo"; "Argentina / Buenos Aires" for the nested ones. */
export function cityName(zone: string): string {
  const parts = zone.split("/");
  const name = (parts.length > 2 ? parts.slice(1).join(" / ") : parts[parts.length - 1] ?? zone).replace(/_/g, " ");
  return name.split(" / ").map((part) => CITY_ACCENTS[part] ?? part).join(" / ");
}

/** The time zones of cities the browser knows, UTC and the fixed offsets left out. */
export function cityZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  let zones: string[] = [];
  try {
    zones = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    zones = [];
  }
  if (!zones.length) zones = ["America/Sao_Paulo", "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney"];
  return zones.filter((zone) => zone.includes("/") && !zone.startsWith("Etc/"));
}

/**
 * A saved time zone as people read it: "local" is "Local time · Sao Paulo (UTC−3)", a fixed
 * offset is "UTC−3", a city is "Sao Paulo (UTC−3)".
 */
export function timeZoneLabel(value: string | null | undefined, localText = "Local time"): string {
  const zone = (value ?? "").trim();
  if (!zone || zone === LOCAL_ZONE) {
    const plant = plantTimeZone();
    return isUtc(plant) ? `${localText} (UTC)` : `${localText} \u00b7 ${cityName(plant)} (${offsetLabel(plant)})`;
  }
  if (isUtc(zone)) return "UTC";
  if (isFixedOffset(zone)) return offsetLabel(zone);
  return validZone(zone) ? `${cityName(zone)} (${offsetLabel(zone)})` : zone;
}

/** The zone a display text ends with when it is not the installation's own ("UTC", "UTC−3"). */
export function zoneSuffix(zone = displayTimeZone()): string {
  if (isUtc(zone)) return "UTC";
  return isFixedOffset(zone) ? offsetLabel(zone) : "";
}
