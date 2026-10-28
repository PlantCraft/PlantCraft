/**
 * The PlantCraft app family: one tile, one palette, one glyph grammar.
 * Pure data (no React) so the standalone SVGs in docs/images/apps/ are
 * generated from the same source (appMarks.test.ts). See docs/brand.md,
 * "App family".
 *
 * Grammar: 32 x 32 grid, tile rx 7, white glyph, main strokes 2.2-2.4,
 * secondary strokes 1.6, nothing thinner, butt caps on the process line,
 * round joins on curves; every glyph keeps 4 px clear of the tile edge.
 */

export const APP_IDS = [
  "processcraft",
  "desk",
  "linkcraft",
  "dashcraft",
  "simcraft",
  "alarmcraft",
  "histcraft",
  "modelcraft",
  "doccraft",
] as const;

export type AppId = (typeof APP_IDS)[number];

/** An app of the family, or a company's own app (its id from app.toml, an app made from the
 * template): outside the family it shows its manifest name and a letter tile. */
export type AnyAppId = AppId | (string & {});

export function isFamilyApp(app: string): app is AppId {
  return (APP_IDS as readonly string[]).includes(app);
}

/** The name an app shows: the family's name, else the name its manifest gives (or its id). */
export function appDisplayName(app: AnyAppId, name?: string | null): string {
  return isFamilyApp(app) ? APP_NAMES[app] : name || app;
}

/**
 * The platform's brand, written once. The tab title and the tab icon of every app use it
 * (tabTitle.ts), the lockups (Brand.tsx) and the full names below (owner, 2026-10-23: the platform
 * is PlantCraft; ids, packages and URLs keep processcraft).
 */
export const BRAND_NAME = "PlantCraft";

/**
 * Display names. Only the platform keeps the Craft brand; every module is "PlantCraft <name>"
 * in documents and proposals, and just "<name>" inside the suite (owner decision, 2026-10-20).
 * Ids, repositories and URL prefixes keep their {function}craft form.
 */
export const APP_NAMES: Record<AppId, string> = {
  processcraft: BRAND_NAME,
  // Each person's day: the suite's first page (owner, 2026-10-23), served by the platform.
  desk: "Desk",
  linkcraft: "Analytics",
  dashcraft: "View",
  simcraft: "Simulator",
  alarmcraft: "Alarms",
  histcraft: "Historian",
  modelcraft: "Models",
  doccraft: "Documents",
};

/** "PlantCraft Analytics"; the platform is just "PlantCraft". */
export function appFullName(app: AppId): string {
  return app === "processcraft" ? BRAND_NAME : `${BRAND_NAME} ${APP_NAMES[app]}`;
}

/** The short name of a module's full name ("PlantCraft Historian" -> "Historian"); a manifest
 * written before the rename still says "PlantCraft Historian". */
export function appShortName(name: string): string {
  const short = name.replace(/^(?:PlantCraft|PlantCraft)\s+/, "");
  return short || name;
}

/** The name the suite shows for an app: its family's name when the id is known (so a renamed
 * module reads the same everywhere, whatever its manifest still says), else the short name. */
export function appLabel(id: string, name: string): string {
  const family = appIdFor(id);
  return family ? APP_NAMES[family] : appShortName(name);
}

/** Machine ids the backend serves today -> family id. */
export const APP_ID_BY_MACHINE_ID: Record<string, AppId> = {
  processcraft: "processcraft",
  // CPMCraft and DataCraft became LinkCraft; TrendCraft was renamed DashCraft (owner decisions, 2026-10-20); Dashboards is shown as View (2026-10-21).
  cpm: "linkcraft",
  cpmcraft: "linkcraft",
  data_quality: "linkcraft",
  datacraft: "linkcraft",
  dashboards: "dashcraft",
  view: "dashcraft",
  trendcraft: "dashcraft",
  simulator: "simcraft",
  // The Simulator was `plantcraft` until its 0.5.0: the platform took the name (2026-10-27).
  // The Twin was retired into Link (owner, 2026-10-22).
  twincraft: "linkcraft",
  twin: "linkcraft",
};

/** Family id of a machine id (or a family id), or null if unknown. */
export function appIdFor(id: string | null | undefined): AppId | null {
  if (!id) return null;
  if ((APP_IDS as readonly string[]).includes(id)) return id as AppId;
  return APP_ID_BY_MACHINE_ID[id] ?? null;
}

/**
 * Tile colours. Deep, white-glyph-safe (contrast >= 4.5:1 in both themes) and
 * kept off the loop-health hues (status fills are mid-tone and bright; tiles
 * are dark). Dark values are a step lighter so the tile holds on #151c24.
 * Mirrored as --pc-app-<id> in tokens.css; change both together.
 */
export const APP_COLORS: Record<AppId, { name: string; light: string; dark: string }> = {
  processcraft: { name: "PlantCraft Blue", light: "#0a66d0", dark: "#1f74d8" },
  desk: { name: "Logbook Plum", light: "#6a3d9a", dark: "#7b4cad" },
  linkcraft: { name: "Loop Teal", light: "#00726b", dark: "#08857d" },
  dashcraft: { name: "Chart Indigo", light: "#3442a6", dark: "#3f52b8" },
  simcraft: { name: "Equipment Olive", light: "#56661a", dark: "#647722" },
  alarmcraft: { name: "Annunciator Wine", light: "#9c2b4f", dark: "#b0395f" },
  histcraft: { name: "Archive Bronze", light: "#80591a", dark: "#926722" },
  modelcraft: { name: "Copper", light: "#9c4419", dark: "#ae5023" },
  doccraft: { name: "Manual Slate", light: "#3d5a73", dark: "#4a6a86" },
};

type Attrs = Record<string, string | number>;
/** One SVG element of a glyph. `ink` fills/strokes in the glyph colour. */
export type GlyphPart = { tag: "path" | "circle" | "rect" | "ellipse"; attrs: Attrs; fill?: boolean };

const s = (d: string, width = 2.2, extra: Attrs = {}): GlyphPart => ({ tag: "path", attrs: { d, "stroke-width": width, ...extra } });
const f = (d: string): GlyphPart => ({ tag: "path", attrs: { d }, fill: true });

/** The glyphs, drawn on the 32 grid in the ISA-5.1 line-art spirit of the PlantCraft mark. */
export const APP_GLYPHS: Record<AppId, GlyphPart[]> = {
  // Control valve on a process line, driven by an instrument bubble; the valve carries the mark,
  // the stem is short so it never reads as a figure at 16 px (owner, 2026-10-23).
  processcraft: [
    s("M4 21h4M24 21h4", 2.4),
    s("M16 21V13.6"),
    { tag: "circle", attrs: { cx: 16, cy: 9.2, r: 4.4, "stroke-width": 2.2 } },
    f("M8 15.4v11.2l8-5.6zM24 15.4v11.2L16 21z"),
  ],
  // A desk calendar page with a check: the day's work, ticked off.
  desk: [
    { tag: "rect", attrs: { x: 5, y: 7, width: 22, height: 20, rx: 3, "stroke-width": 2.2 } },
    s("M5 13h22", 1.6),
    s("M11 4.5v5M21 4.5v5", 2.2),
    s("M11 19.8l3.4 3.4 6.6-7", 2.4, { "stroke-linejoin": "round", "stroke-linecap": "round" }),
  ],
  // One method block inside its feedback loop: the loop and its diagnosis (2026-10-23; two
  // blocks in a row read as glasses at 16 px).
  linkcraft: [
    { tag: "rect", attrs: { x: 10, y: 6, width: 12, height: 11, rx: 2, "stroke-width": 2.2 } },
    s("M4 11.5h2.6M22 11.5h6", 2.2),
    f("M10 11.5l-3.4-2.9v5.8z"),
    s("M25 11.5V24H7v-8", 1.8, { "stroke-linejoin": "round" }),
  ],
  // A trend on its axes under a dashed limit line: a dashboard card.
  dashcraft: [
    s("M5 5v22h23", 2.2, { "stroke-linecap": "square" }),
    s("M9 22l5-6.5 4 3.5 8-7.5", 2.4, { "stroke-linejoin": "round", "stroke-linecap": "round" }),
    s("M9.5 8.5h17", 1.6, { "stroke-dasharray": "2.6 2" }),
  ],
  // A column with feed and product lines.
  simcraft: [
    { tag: "rect", attrs: { x: 11, y: 4, width: 10, height: 24, rx: 5, "stroke-width": 2.2 } },
    s("M14 12h4M14 16h4M14 20h4", 1.6),
    s("M4 16h7M21 9h7M21 23h7", 2.2),
  ],
  // An annunciator horn over a limit line.
  alarmcraft: [
    f("M16 4.6a1.6 1.6 0 0 1 1.6 1.6v.5a6.6 6.6 0 0 1 5 6.4v5.2l2.4 3H7l2.4-3v-5.2a6.6 6.6 0 0 1 5-6.4v-.5A1.6 1.6 0 0 1 16 4.6z"),
    f("M13.2 22.7h5.6a2.8 2.8 0 0 1-5.6 0z"),
    s("M4 27h3.5M10.5 27h4M17.5 27h4M24.5 27h3.5", 1.8),
  ],
  // A historian: stacked data cylinder on a time axis.
  histcraft: [
    { tag: "ellipse", attrs: { cx: 16, cy: 7.5, rx: 8, ry: 3, "stroke-width": 2.2 } },
    s("M8 7.5v12c0 1.7 3.6 3 8 3s8-1.3 8-3v-12M8 13.5c0 1.7 3.6 3 8 3s8-1.3 8-3", 2.2),
    s("M4 27.5h24M8 25.5v2M16 25.5v2M24 25.5v2", 1.6),
  ],
  // A transfer block with input and output, a step response inside.
  modelcraft: [
    { tag: "rect", attrs: { x: 9.5, y: 9.5, width: 13, height: 13, rx: 2, "stroke-width": 2.2 } },
    s("M12.5 19.5c1.6 0 1.8-6 4.4-6h2.6", 1.8, { "stroke-linecap": "round", "stroke-linejoin": "round" }),
    s("M4 16h5.5M22.5 16h2", 2.2),
    f("M28 16l-3.6-3v6z"),
  ],
  // A manual: a page with a folded corner, lines of text and a magnifier over them.
  doccraft: [
    s("M9 4.5h9.5l5.5 5.5v17.5H9z", 2.2, { "stroke-linejoin": "round" }),
    s("M18.5 4.5V10H24", 1.8, { "stroke-linejoin": "round" }),
    s("M12.5 14h8M12.5 18h5M12.5 22h4", 1.8, { "stroke-linecap": "round" }),
    { tag: "circle", attrs: { cx: 21, cy: 21, r: 3.2, "stroke-width": 2 } },
    s("M23.4 23.4l3.6 3.6", 2.2, { "stroke-linecap": "round" }),
  ],
};

/** Inner SVG markup of one glyph in a given ink (for the standalone files). */
export function glyphMarkup(app: AppId, ink: string): string {
  return APP_GLYPHS[app]
    .map(({ tag, attrs, fill }) => {
      const paint = fill ? `fill="${ink}"` : `fill="none" stroke="${ink}"`;
      const rest = Object.entries(attrs).map(([key, value]) => `${key}="${value}"`).join(" ");
      return `<${tag} ${rest} ${paint}/>`;
    })
    .join("");
}

/** A complete standalone mark SVG (tile + white glyph). */
export function markSvg(app: AppId, theme: "light" | "dark" = "light", size = 32): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="${size}" height="${size}" role="img" aria-label="${appFullName(app)}"><title>${appFullName(app)}</title><rect width="32" height="32" rx="7" fill="${APP_COLORS[app][theme]}"/>${glyphMarkup(app, "#fff")}</svg>`;
}
