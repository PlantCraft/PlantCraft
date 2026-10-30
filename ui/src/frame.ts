/**
 * The suite's persistent frame (round 8): inside an installation PlantCraft
 * draws the sidebar once and every app runs inside it as content only, in a same-origin iframe,
 * so switching apps never reloads the sidebar and every app shows the platform's current one.
 * Each app keeps its own server, package and version; run alone it draws its own sidebar.
 *
 * The proxy sends a page the person opens (`Sec-Fetch-Dest: document`) under an app's prefix to
 * PlantCraft, which draws the frame; the frame loads the same address in an iframe marked
 * `data-pc-frame`, which the proxy sends to the app. The two talk with `postMessage` on the same
 * origin only, in the messages below. An app that never says it is ready (an older ui) is opened
 * on its own page with `pc-frame=off`, which the proxy leaves to the app.
 */

/** The attribute the frame puts on its iframes; an app inside one draws only its content. */
export const FRAME_ATTR = "data-pc-frame";
/** The query that opens an app on its own page, outside the frame. */
export const FRAME_OFF = "pc-frame=off";
/** How long the frame waits for a new app to say it is ready before opening it on its own page. */
export const FRAME_READY_MS = 4_000;

export type FrameNavChild = { to: string; href: string; label: string; active: boolean };
export type FrameNavItem = { to: string; href: string; label: string; icon: string; section?: string; active: boolean; children?: FrameNavChild[] };

/** What the app inside tells the frame, every time it changes. */
export type FrameState = {
  app: string;
  appName?: string;
  subtitle?: string;
  /** The app's base path ("/link/"): its pages are below it. */
  base: string;
  /** The app path of its first page. */
  home: string;
  /** The current app path and the full address (path, query and hash, under the base). */
  path: string;
  url: string;
  nav: FrameNavItem[];
  /** The page's own title (its first h1), for the tab. */
  heading: string;
  version?: string | null;
  /** The app has a guided tour / offers the assistant. */
  tour: boolean;
  assistant: boolean;
  /** The app's assistant panel is open. */
  assistantOpen: boolean;
};

/** App -> frame. */
export type ToFrame =
  | { type: "pc-frame:ready" }
  | { type: "pc-frame:state"; state: FrameState }
  /** A shortcut pressed inside the app that the frame answers ("[" folds, "k" searches). */
  | { type: "pc-frame:key"; key: "[" | "k" }
  /** The app opened Messages (a conversation, "" its start, "notifications"). */
  | { type: "pc-frame:messages"; conversation: string }
  /** A link outside the app: the frame opens it (another app, a PlantCraft page). */
  | { type: "pc-frame:open"; url: string };

/** Frame -> app. */
export type ToApp =
  | { type: "pc-frame:go"; to: string }
  /** `still`: another panel of the frame was open, so the assistant takes its place without sliding in. */
  | { type: "pc-frame:assistant"; still?: boolean }
  | { type: "pc-frame:tour" }
  /** `still`: a panel of the frame takes the place of the app's (no fold-back). */
  | { type: "pc-frame:close-panels"; still?: boolean };

const TYPES_TO_FRAME = new Set(["pc-frame:ready", "pc-frame:state", "pc-frame:key", "pc-frame:messages", "pc-frame:open"]);
const TYPES_TO_APP = new Set(["pc-frame:go", "pc-frame:assistant", "pc-frame:tour", "pc-frame:close-panels"]);

let framedCache: boolean | null = null;

/** Whether this page runs as an app inside the platform's frame. */
export function isFramed(): boolean {
  if (framedCache !== null) return framedCache;
  framedCache = false;
  if (typeof window === "undefined" || window.parent === window) return framedCache;
  try {
    framedCache = Boolean(window.frameElement?.hasAttribute(FRAME_ATTR)) && window.parent.location.origin === window.location.origin;
  } catch {
    framedCache = false; // another origin: never
  }
  return framedCache;
}

/** Tests only: read the frame again. */
export function forgetFramed(value: boolean | null = null) { framedCache = value; }

/** From the app inside: tell the frame. */
export function toFrame(message: ToFrame) {
  if (!isFramed()) return;
  window.parent.postMessage(message, window.location.origin);
}

/** From the frame: tell an app inside. */
export function toApp(target: Window | null | undefined, message: ToApp) {
  target?.postMessage(message, window.location.origin);
}

function typed(event: MessageEvent, types: Set<string>): boolean {
  if (event.origin !== window.location.origin) return false;
  const data = event.data as { type?: unknown } | null;
  return Boolean(data && typeof data === "object" && typeof data.type === "string" && types.has(data.type));
}

/** A message for the frame, from the same origin and of a known type; null otherwise. */
export function readToFrame(event: MessageEvent): ToFrame | null {
  return typed(event, TYPES_TO_FRAME) ? (event.data as ToFrame) : null;
}

/** A message for the app, from its own frame (the parent window) and of a known type; null otherwise. */
export function readToApp(event: MessageEvent): ToApp | null {
  if (event.source !== window.parent) return null;
  return typed(event, TYPES_TO_APP) ? (event.data as ToApp) : null;
}

/** The app's prefix of an address ("/link/loops/3" -> "/link/"), from the suite's apps. */
export function appPrefix(path: string, bases: string[]): string | null {
  const sorted = [...bases].filter((base) => base && base !== "/").sort((a, b) => b.length - a.length);
  for (const base of sorted) {
    const bare = base.replace(/\/$/, "");
    if (path === bare || path.startsWith(`${bare}/`)) return base.endsWith("/") ? base : `${base}/`;
  }
  return null;
}

/** The address with `pc-frame=off`: the app on its own page. */
export function frameOff(url: string): string {
  const [rest, hash = ""] = url.split("#", 2);
  return `${rest}${rest.includes("?") ? "&" : "?"}${FRAME_OFF}${hash ? `#${hash}` : ""}`;
}

const SVG_TAGS = new Set(["svg", "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "g"]);
const SVG_ATTRS = new Set(["xmlns", "width", "height", "viewBox", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "points", "class", "aria-hidden", "transform", "opacity", "fill-rule", "clip-rule"]);

/**
 * A sidebar icon the app sent, as SVG markup the frame may draw: only shapes and their geometry
 * (no scripts, links, styles, events or foreign content); anything else gives an empty icon.
 */
export function sanitizeIcon(markup: string): string {
  if (!markup || typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(markup, "image/svg+xml");
  const root = doc.documentElement;
  if (!root || root.nodeName !== "svg" || doc.getElementsByTagName("parsererror").length) return "";
  const clean = (element: Element): boolean => {
    if (!SVG_TAGS.has(element.nodeName)) return false;
    for (const attr of [...element.attributes]) {
      const value = attr.value;
      if (!SVG_ATTRS.has(attr.name) || /url\s*\(|javascript:/i.test(value)) element.removeAttribute(attr.name);
    }
    for (const child of [...element.children]) if (!clean(child)) child.remove();
    return true;
  };
  clean(root);
  return new XMLSerializer().serializeToString(root);
}
