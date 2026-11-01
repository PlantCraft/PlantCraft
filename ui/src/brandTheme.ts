/**
 * The suite's colours for code that cannot read CSS variables (Plotly, canvas), the status
 * tones and the Plotly base layout: one copy for every app. Mirrors tokens.css; change both
 * together. See PlantCraft docs/brand.md.
 */
import { APP_COLORS as APP_TILE_COLORS, type AppId as AppFamilyId } from "./appMarks.js";

/* ------------------------------------------------------------------ colours */

/** Light and dark values of the tokens that JavaScript needs. Mirrors tokens.css. */
export const BRAND_COLORS = {
  light: {
    primary: "#2e5a88",
    surface: "#ffffff",
    text: "#111113",
    text2: "#2c2c2e",
    text3: "#55555a",
    grid: "#e8e8ed",
    axis: "#dedee3",
    good: "#34c759",
    attention: "#ff9f0a",
    serious: "#f2690d",
    problem: "#ff3b30",
    inactive: "#8e8e93",
    unusable: "#af52de",
    info: "#32ade6",
    series: ["#0f55a3", "#c25e00", "#007f7a", "#523c9e", "#a8851c", "#7d3319", "#b03a7b", "#357a26"],
  },
  dark: {
    primary: "#3d78b6",
    surface: "#0b0b0c",
    text: "#fafafa",
    text2: "#e5e5ea",
    text3: "#b0b0b5",
    grid: "#2a2a2d",
    axis: "#3a3a3d",
    good: "#30d158",
    attention: "#ff9f0a",
    serious: "#ff7a2e",
    problem: "#ff453a",
    inactive: "#8e8e93",
    unusable: "#bf5af2",
    info: "#64d2ff",
    series: ["#6aa8f2", "#ff9b40", "#33d1c9", "#ad9cf5", "#e6c04a", "#e0805a", "#f07ab6", "#74c95c"],
  },
} as const;

export type BrandTheme = keyof typeof BRAND_COLORS;

/** The theme in effect: <html data-theme> wins, then the OS preference. */
export function currentTheme(): BrandTheme {
  if (typeof document === "undefined") return "light";
  const forced = document.documentElement.dataset.theme;
  if (forced === "light" || forced === "dark") return forced;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Status tones: the token family (tokens.css `--pc-<tone>-*`) each state uses. */
export type StatusTone = "good" | "attention" | "serious" | "problem" | "inactive" | "unusable" | "info";

/** Tone of every status id the suite's APIs return. An app adds its own with addStatusTones(). */
export const STATUS_TONES: Record<string, StatusTone> = {
  ok: "good", normal: "good", pass: "good", completed: "good", good: "good", connected: "good",
  medium: "attention", warning: "attention", attention: "attention", suspect: "attention", deviating: "attention",
  high: "serious",
  critical: "problem", bad: "problem", alarm: "problem", failed: "problem", problem: "problem", error: "problem", disconnected: "problem",
  inactive: "inactive", cancelled: "inactive", not_applicable: "inactive", off: "inactive", unchecked: "inactive", interrupted: "inactive", disabled: "inactive", unknown: "inactive",
  no_data: "unusable", insufficient_data: "unusable", incomplete: "unusable", unusable: "unusable",
  pending: "info", queued: "info", running: "info", waiting: "info",
};

/** An app's own status ids (or a different tone for a shared one), set once at start. */
export function addStatusTones(tones: Record<string, StatusTone>) {
  Object.assign(STATUS_TONES, tones);
}

/**
 * CSS colour of a status for DOM styles: follows the theme by itself.
 * `fill` for dots and bars, `text` for words, `soft` for pill backgrounds.
 * Unknown statuses read as inactive.
 */
export function statusVar(status: string | undefined, part: "fill" | "text" | "soft" | "border" = "fill"): string {
  return `var(--pc-${(status && STATUS_TONES[status]) || "inactive"}-${part})`;
}

/**
 * Loop-health colours keyed by every status id the API returns, as hex for
 * Plotly and canvas. Status colours are reserved for state: never use them
 * for an ordinary series.
 */
export function statusColors(theme: BrandTheme = currentTheme()): Record<string, string> {
  const c = BRAND_COLORS[theme];
  return Object.fromEntries(Object.entries(STATUS_TONES).map(([status, tone]) => [status, c[tone]]));
}

/** Ordinary series colours as CSS variables (DOM swatches next to charts). */
export function seriesVar(index: number): string {
  return `var(--pc-series-${(index % 8) + 1})`;
}

/** Sequential scale for health 0-100 %: problem -> attention -> good. */
export function healthScale(theme: BrandTheme = currentTheme()): Array<[number, string]> {
  const c = BRAND_COLORS[theme];
  return [[0, c.problem], [0.5, c.attention], [1, c.good]];
}

/** Single-hue scale for magnitude heatmaps (surface -> PlantCraft Blue). */
export function magnitudeScale(theme: BrandTheme = currentTheme()): Array<[number, string]> {
  return theme === "dark" ? [[0, "#10243f"], [1, "#86b6f3"]] : [[0, "#eef5fe"], [1, "#0a4285"]];
}

/** Older to newer points (a scatter coloured by time): faint to strong PlantCraft Blue, readable on
 * the card of either theme (Plotly's "Blues" ends near black on a black card). */
export function timeScale(theme: BrandTheme = currentTheme()): Array<[number, string]> {
  return theme === "dark" ? [[0, "#2c4c72"], [1, "#a9d0ff"]] : [[0, "#b7cde8"], [1, "#0f55a3"]];
}

/**
 * Base Plotly layout in the brand: Inter, the colourway, a quiet horizontal grid and no
 * vertical one; the plot sits on the card's own white or black, never a tinted fill. Spread it first, then the chart's own settings:
 * `layout={{ ...plotTheme(), height: 300, xaxis: { ...plotTheme().xaxis, tickformat } }}`.
 */
export function plotTheme(theme: BrandTheme = currentTheme()) {
  const c = BRAND_COLORS[theme];
  const axis = {
    gridcolor: c.grid,
    linecolor: c.axis,
    zerolinecolor: c.axis,
    zeroline: false,
    tickfont: { family: "Inter, system-ui, sans-serif", size: 10.5, color: c.text3 },
    automargin: true,
  };
  return {
    colorway: [...c.series],
    font: { family: "Inter, system-ui, sans-serif", size: 11, color: c.text2 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    // The tooltip on the theme's surface with its text colour: unset, Plotly paints a unified
    // tooltip (hovermode "x unified") from the transparent paper, white, and the dark theme's
    // light text was unreadable on it (View round 7).
    hoverlabel: { bgcolor: c.surface, bordercolor: c.axis, font: { family: "JetBrains Mono, ui-monospace, monospace", size: 11, color: c.text } },
    legend: { font: { size: 11, color: c.text2 } },
    xaxis: { ...axis, showgrid: false },
    yaxis: { ...axis },
    modebar: { color: c.text3, activecolor: c.primary, bgcolor: "rgba(0,0,0,0)" },
  };
}

/* --------------------------------------------------------------- app family */

/** Tile colour of an app as hex (Plotly, canvas). DOM code uses `var(--pc-app-<id>)`. */
export function appColor(app: AppFamilyId, theme: BrandTheme = currentTheme()): string {
  return APP_TILE_COLORS[app][theme];
}
