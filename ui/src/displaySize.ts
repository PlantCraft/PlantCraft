/**
 * Display size: five steps from "Larger text" to "More space", chosen in the user menu beside
 * the theme. Larger text helps people who read the screen from further away or see less well;
 * More space fits more of a page on a small laptop. Like the theme, one browser setting covers
 * every app of the suite (they share one host).
 *
 * The step goes on <html data-size="1..5"> (none = the default, 3). tokens.css turns it into two
 * scales, --pc-text-scale for the type tokens and --pc-space-scale for the spacing tokens, so
 * every page that uses the tokens follows. Nothing is zoomed: coordinates, viewport units,
 * pop-up positions and chart hover stay exact.
 */
export type DisplaySize = 1 | 2 | 3 | 4 | 5;
export const DISPLAY_SIZE_KEY = "plantcraft-ui:display-size";
export const DEFAULT_DISPLAY_SIZE: DisplaySize = 3;

/** Each step's scales, from the largest text (1) to the most space (5). Kept in step with tokens.css. */
export const DISPLAY_SIZES: ReadonlyArray<{ value: DisplaySize; label: string; text: number; space: number }> = [
  { value: 1, label: "Larger text", text: 1.25, space: 1.15 },
  { value: 2, label: "Large", text: 1.12, space: 1.07 },
  { value: 3, label: "Default", text: 1, space: 1 },
  { value: 4, label: "Compact", text: 0.93, space: 0.85 },
  { value: 5, label: "More space", text: 0.86, space: 0.72 },
];

function isSize(value: unknown): value is DisplaySize {
  return DISPLAY_SIZES.some((size) => String(size.value) === String(value));
}

/** The saved step; storage can be blocked (private windows), so fall back to the default. */
export function displaySize(): DisplaySize {
  try {
    const saved = window.localStorage.getItem(DISPLAY_SIZE_KEY);
    return isSize(saved) ? (Number(saved) as DisplaySize) : DEFAULT_DISPLAY_SIZE;
  } catch {
    return DEFAULT_DISPLAY_SIZE;
  }
}

/** The text scale in effect (1 = default): charts drawn outside CSS (Plotly) size their type by it. */
export function textScale(): number {
  if (typeof document === "undefined") return 1;
  const step = document.documentElement.dataset.size;
  return DISPLAY_SIZES.find((size) => String(size.value) === step)?.text ?? 1;
}

/** Put the step on <html>. Call once before the first render, so nothing jumps. */
export function applyDisplaySize(size: DisplaySize = displaySize()) {
  const root = document.documentElement;
  if (size === DEFAULT_DISPLAY_SIZE || !isSize(size)) delete root.dataset.size;
  else root.dataset.size = String(size);
}

export function setDisplaySize(size: DisplaySize) {
  try {
    if (size === DEFAULT_DISPLAY_SIZE) window.localStorage.removeItem(DISPLAY_SIZE_KEY);
    else window.localStorage.setItem(DISPLAY_SIZE_KEY, String(size));
  } catch {
    // Not saved; it still applies to this page.
  }
  applyDisplaySize(size);
  window.dispatchEvent(new CustomEvent("plantcraft-ui:display-size", { detail: size }));
}

/** Apply now and follow changes made in another tab or app. */
export function initDisplaySize() {
  applyDisplaySize();
  window.addEventListener("storage", (event) => {
    if (event.key === DISPLAY_SIZE_KEY) applyDisplaySize();
  });
}
