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
 * (tabTitle.ts), the lockups (Brand.tsx) and the full names below (the platform
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
  // Each person's day: the suite's first page, served by the platform.
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
  // The Twin was retired into Link.
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
 * are dark). Toned toward the Steel Blue brand (2026-10-30): same hues, less
 * saturation. Dark values are the lightest that keep 4.5:1, so tiles hold on black.
 * Mirrored as --pc-app-<id> in tokens.css; change both together.
 */
export const APP_COLORS: Record<AppId, { name: string; light: string; dark: string }> = {
  processcraft: { name: "Steel Blue", light: "#2e5a88", dark: "#3d78b6" },
  desk: { name: "Logbook Plum", light: "#5b3a7e", dark: "#8b62b7" },
  linkcraft: { name: "Loop Teal", light: "#1b5753", dark: "#28807a" },
  dashcraft: { name: "Chart Indigo", light: "#333d85", dark: "#636ec3" },
  simcraft: { name: "Equipment Olive", light: "#536020", dark: "#6a7b29" },
  alarmcraft: { name: "Annunciator Wine", light: "#882f4c", dark: "#c14c72" },
  histcraft: { name: "Archive Bronze", light: "#755625", dark: "#946d2f" },
  modelcraft: { name: "Copper", light: "#8a4a2b", dark: "#b15f37" },
  doccraft: { name: "Manual Slate", light: "#415a6f", dark: "#577894" },
};

type Attrs = Record<string, string | number>;
/** One SVG element of a glyph. `ink` fills/strokes in the glyph colour. */
export type GlyphPart = { tag: "path" | "circle" | "rect" | "ellipse"; attrs: Attrs; fill?: boolean };

const s = (d: string, width = 2.2, extra: Attrs = {}): GlyphPart => ({ tag: "path", attrs: { d, "stroke-width": width, ...extra } });
const R: Attrs = { "stroke-linejoin": "round", "stroke-linecap": "round" };
const f = (d: string): GlyphPart => ({ tag: "path", attrs: { d }, fill: true });

/** The glyphs, drawn on the 32 grid in the ISA-5.1 line-art spirit of the PlantCraft mark. */
export const APP_GLYPHS: Record<AppId, GlyphPart[]> = {
  // "PC" drawn as a control valve on a process line: the P's bowl is the valve triangle, the line
  // runs into the P and out of the open C.
  processcraft: [
    s("M4.5 14h4M24.5 14h3", 2.2, R),
    s("M8.5 26V7l7.5 7-7.5 7", 2.2, R),
    s("M24.5 8.3A7 7 0 0 0 16 14a7 7 0 0 0 8.5 5.7", 2.2, R),
  ],
  // An operator console with the day's checklist on screen.
  desk: [
    s("M6.5 5.5h19a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-19A1.5 1.5 0 0 1 5 19V7a1.5 1.5 0 0 1 1.5-1.5z", 2.2, R),
    s("M16 20.5v4.5M11 26.5h10", 2.2, R),
    s("M9 11l1.5 1.5 3-3M16 11h7M9.5 15.5h3M16 15.5h7", 1.6, R),
  ],
  // Two blocks connected: a method feeding its result.
  linkcraft: [
    s("M5 4.5h7.5a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 11V6A1.5 1.5 0 0 1 5 4.5z", 2.2, R),
    s("M19.5 19.5H27a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5h-7.5A1.5 1.5 0 0 1 18 26v-5a1.5 1.5 0 0 1 1.5-1.5z", 2.2, R),
    s("M14 8.5h9.25V15", 2.2, R),
    f("M20.55 14.4h5.4l-2.7 3.4z"),
  ],
  // A trend on its axes under a dashed limit line: a dashboard card.
  dashcraft: [
    s("M5 5v22h23", 2.2, { "stroke-linecap": "square" }),
    s("M9 22l5-6.5 4 3.5 8-7.5", 2.4, { "stroke-linejoin": "round", "stroke-linecap": "round" }),
    s("M9.5 8.5h17", 1.6, { "stroke-dasharray": "2.6 2" }),
  ],
  // A column with feed and product lines (the plant simulator; not an app of the family).
  simcraft: [
    { tag: "rect", attrs: { x: 11, y: 4, width: 10, height: 24, rx: 5, "stroke-width": 2.2 } },
    s("M14 12h4M14 16h4M14 20h4", 1.6),
    s("M4 16h7M21 9h7M21 23h7", 2.2),
  ],
  // A bell in the same line as the rest of the family.
  alarmcraft: [
    s("M10 21.5V15a6 6 0 0 1 12 0v6.5l2 2.5H8z", 2.2, R),
    s("M14 27.5h4M16 6v3", 2.2, R),
  ],
  // A historian: the stacked data cylinder.
  histcraft: [
    { tag: "ellipse", attrs: { cx: 16, cy: 10, rx: 8, ry: 3, "stroke-width": 2.2 } },
    s("M8 10v12c0 1.7 3.6 3 8 3s8-1.3 8-3V10M8 16c0 1.7 3.6 3 8 3s8-1.3 8-3", 2.2, R),
  ],
  // A distillation column with its trays, feed, top and bottom lines.
  modelcraft: [
    s("M12 8a4 4 0 0 1 8 0v16a4 4 0 0 1-8 0z", 2.2, R),
    s("M4.5 16H12M20 8.5h6M20 23.5h6", 2.2, R),
    s("M12 12h5M15 16h5M12 20h5", 1.6, R),
  ],
  // A page with a folded corner and lines of text.
  doccraft: [
    s("M9 4.5h9.5l5 5v18H9z", 2.2, R),
    s("M18.5 4.5v5h5", 2.2, R),
    s("M12.5 14h7M12.5 18h7M12.5 22h4.5", 1.6, R),
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
