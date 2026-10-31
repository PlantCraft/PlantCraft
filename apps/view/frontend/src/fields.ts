/** How a card shows its values (round 7, after Grafana): its options with their defaults, the
 * options of one signal (the card's, then the overrides that match it), threshold steps,
 * value mappings and colours. The server (fields.py) computes states the same way. */
import { BRAND_COLORS, currentTheme, type BrandTheme } from "@plantcraft/ui";
import type { Card, CardOptions, FieldConfig, Level, Mapping, Override, State, Step, Thresholds } from "./types";

export const DEFAULT_OPTIONS: CardOptions = {
  graph: "none", color_by: "value", show_name: true, orientation: "auto",
  bar_style: "bars", value_labels: "auto", sort: "none",
  legend: "list", legend_place: "bottom", legend_values: [], tooltip: "all", stack: "none", connect_gaps: false,
  y_scale: "linear", y_label: "", soft_min: null, soft_max: null,
  gauge_style: "dial", threshold_markers: true, threshold_labels: false,
  columns: ["last", "mean", "min", "max"], cell: "color_text", row_color: false,
  point_size: 5,
};

/** A card's options, every one filled in. */
export function optionsOf(card: Pick<Card, "options">): CardOptions {
  return { ...DEFAULT_OPTIONS, ...(card.options ?? {}) };
}

/** The colour names of the palette editors pick from (and "#rrggbb"). */
export const PALETTE = ["blue", "green", "yellow", "orange", "red", "purple", "teal", "grey"] as const;
export const LEVELS: Level[] = ["ok", "warning", "alarm", "none"];

/** A colour for drawing (Plotly, SVG, styles): a palette name or a level in the theme's hex, or "#rrggbb" as is. */
export function colorOf(name: string | null | undefined, theme: BrandTheme = currentTheme(), fallback?: string): string {
  const c = BRAND_COLORS[theme];
  if (name && /^#[0-9a-fA-F]{6}$/.test(name)) return name;
  const named: Record<string, string> = {
    blue: c.series[0], orange: c.series[1], teal: c.series[2], purple: c.series[3], yellow: c.series[4],
    green: c.series[7], red: c.problem, grey: c.inactive,
    ok: c.good, warning: c.attention, alarm: c.problem,
  };
  return (name && named[name]) || fallback || c.series[0];
}

/** A step's colour: its own, else its level's (a colour-only step without one: the first series). */
export function stepColor(step: Step, theme?: BrandTheme): string {
  return colorOf(step.color || (step.level && step.level !== "none" ? step.level : "blue"), theme);
}

/** A row as overrides match it. */
export interface RowKey { role?: string | null; signal?: string | null; label?: string }

function glob(pattern: string, text: string): boolean {
  const escaped = pattern.toLowerCase().replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`).test(text.toLowerCase());
}

export function matches(override: Override, row: RowKey): boolean {
  const wanted = override.match.value.trim().toLowerCase();
  if (!wanted) return false;
  if (override.match.by === "role") return (row.role ?? "").toLowerCase() === wanted;
  return glob(wanted, String((override.match.by === "signal" ? row.signal : row.label) ?? ""));
}

function defined(config: FieldConfig): FieldConfig {
  return Object.fromEntries(Object.entries(config ?? {}).filter(([, value]) => value !== null && value !== undefined)) as FieldConfig;
}

/** The options of one signal: the card's, then each override that matches it, in order. */
export function effective(card: Pick<Card, "field" | "overrides">, row: RowKey): FieldConfig {
  let found = defined(card.field ?? {});
  for (const override of card.overrides ?? []) if (matches(override, row)) found = { ...found, ...defined(override.field) };
  return found;
}

/** The step a value is in (none: no value, no steps, or a percentage without a range). */
export function stepOf(thresholds: Thresholds | null | undefined, value: number | null | undefined, low?: number | null, high?: number | null): Step | null {
  if (value === null || value === undefined || !Number.isFinite(value) || !thresholds?.steps?.length) return null;
  let at = value;
  if (thresholds.mode === "percentage") {
    if (low === null || low === undefined || high === null || high === undefined || !(high > low)) return null;
    at = ((value - low) / (high - low)) * 100;
  }
  const steps = sortedSteps(thresholds.steps);
  let found = steps[0];
  for (const step of steps.slice(1)) if (typeof step.value === "number" && at >= step.value) found = step;
  return found;
}

/** Steps as the server keeps them: the base first, the rest by value. */
export function sortedSteps(steps: Step[]): Step[] {
  const base = steps.filter((step) => typeof step.value !== "number");
  const rest = steps.filter((step) => typeof step.value === "number").sort((a, b) => (a.value as number) - (b.value as number));
  return [...(base.length ? base.slice(0, 1) : [{ level: "ok" as Level }]), ...rest];
}

export function mappingFor(mappings: Mapping[] | null | undefined, value: number | string | null | undefined): Mapping | null {
  for (const mapping of mappings ?? []) {
    if (mapping.type === "text") {
      if (typeof value === "string" && value.trim().toLowerCase() === (mapping.value ?? "").trim().toLowerCase()) return mapping;
      continue;
    }
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (mapping.type === "range") {
      const low = mapping.low ?? -Infinity;
      const high = mapping.high ?? Infinity;
      if (value >= low && value <= high) return mapping;
    } else if (mapping.value !== undefined && mapping.value.trim() !== "" && Number(mapping.value) === value) return mapping;
  }
  return null;
}

/** The colour a value is drawn in, by the field's colour mode: its threshold's or mapping's colour,
 * the fixed colour, or the palette colour of its position. */
export function valueColor(config: FieldConfig, value: number | string | null | undefined, index = 0, range?: { low?: number | null; high?: number | null }, theme?: BrandTheme): string {
  const mapped = mappingFor(config.mappings, value);
  if (mapped?.color) return colorOf(mapped.color, theme);
  if (mapped?.level) return colorOf(mapped.level, theme);
  const mode = config.color_mode ?? (config.thresholds?.steps?.length ? "thresholds" : config.color ? "fixed" : "palette");
  if (mode === "fixed") return colorOf(config.color ?? "blue", theme);
  if (mode === "thresholds") {
    const step = stepOf(config.thresholds, typeof value === "number" ? value : null, config.min ?? range?.low, config.max ?? range?.high);
    if (step) return stepColor(step, theme);
  }
  return colorOf(config.color, theme, BRAND_COLORS[theme ?? currentTheme()].series[index % 8]);
}

/** The words a value is shown as: its mapping's text, else the formatted number. */
export function mappedText(config: FieldConfig, value: number | string | null | undefined): string | null {
  const mapped = mappingFor(config.mappings, value);
  return mapped?.text ? mapped.text : null;
}

/** The state the server would compute (the client draws while editing, before a read). */
export function stateOf(config: FieldConfig, value: number | string | null | undefined, range?: { low?: number | null; high?: number | null }): State {
  const mapped = mappingFor(config.mappings, value);
  if (mapped?.level) return mapped.level;
  const step = stepOf(config.thresholds, typeof value === "number" ? value : null, config.min ?? range?.low, config.max ?? range?.high);
  return !step || !step.level || step.level === "none" ? "none" : step.level;
}

/** Threshold values in the units of the signal (percentages turned into values between min and max). */
export function stepValues(config: FieldConfig, range?: { low?: number | null; high?: number | null }): Array<{ value: number; step: Step }> {
  const thresholds = config.thresholds;
  if (!thresholds?.steps?.length) return [];
  const low = config.min ?? range?.low;
  const high = config.max ?? range?.high;
  return sortedSteps(thresholds.steps).filter((step) => typeof step.value === "number").flatMap((step) => {
    if (thresholds.mode !== "percentage") return [{ value: step.value as number, step }];
    if (low === null || low === undefined || high === null || high === undefined || !(high > low)) return [];
    return [{ value: low + ((step.value as number) / 100) * (high - low), step }];
  });
}

/** Levels in words, for editors and legends. */
export function levelLabel(level: Level | "" | undefined): string {
  return level === "alarm" ? "Critical" : level === "warning" ? "Warning" : level === "ok" ? "Normal" : "Colour only";
}

function channels(hex: string): [number, number, number] | null {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  return match ? [parseInt(match[1], 16), parseInt(match[2], 16), parseInt(match[3], 16)] : null;
}
function luminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
/** WCAG contrast of two "#rrggbb" colours (1 to 21). */
export function contrast(a: string, b: string): number {
  const [x, y] = [channels(a), channels(b)];
  if (!x || !y) return 21;
  const [high, low] = [luminance(x), luminance(y)].sort((p, q) => q - p);
  return (high + 0.05) / (low + 0.05);
}
function mix(a: [number, number, number], b: [number, number, number], share: number): string {
  return `#${a.map((c, i) => Math.round(c + (b[i] - c) * share).toString(16).padStart(2, "0")).join("")}`;
}

/** A colour as text on the card: its own hue, moved towards the theme's text colour until it reads
 * (3:1 for big numbers, 4.5:1 for table text). A green "ok" on white is too pale as a number. */
export function legible(color: string | undefined, minimum = 3, theme: BrandTheme = currentTheme()): string | undefined {
  const own = color ? channels(color) : null;
  if (!color || !own) return color;
  const { surface, text } = BRAND_COLORS[theme];
  const towards = channels(text)!;
  for (let share = 0; share <= 1; share += 0.1) {
    const found = mix(own, towards, share);
    if (contrast(found, surface) >= minimum) return found;
  }
  return text;
}

/** The text colour on a filled background: white or the dark text, whichever reads better. */
export function textOn(fill: string | undefined): string | undefined {
  if (!fill || !channels(fill)) return undefined;
  return contrast("#ffffff", fill) >= contrast("#1d1d1f", fill) ? "#ffffff" : "#1d1d1f";
}
