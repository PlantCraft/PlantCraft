/**
 * Light, dark or the system's theme, chosen in the user menu. All apps of the
 * suite are served from one host, so one browser setting covers every app.
 * tokens.css reads <html data-theme="light|dark">; no attribute = the system's.
 */
import { initDisplaySize } from "./displaySize.js";

export type ThemeChoice = "light" | "dark" | "system";
export const THEME_KEY = "plantcraft-ui:theme";
const CHOICES: ThemeChoice[] = ["light", "dark", "system"];

/** The saved choice; storage can be blocked (private windows), so fall back to the system. */
export function themeChoice(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    return CHOICES.includes(saved as ThemeChoice) ? (saved as ThemeChoice) : "system";
  } catch {
    return "system";
  }
}

/** Put the choice on <html>. Call once before the first render, so nothing flashes. */
export function applyTheme(choice: ThemeChoice = themeChoice()) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
}

export function setTheme(choice: ThemeChoice) {
  try {
    window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Not saved; it still applies to this page.
  }
  applyTheme(choice);
  window.dispatchEvent(new CustomEvent("plantcraft-ui:theme", { detail: choice }));
}

/** Apply now and follow changes made in another tab or app; the display size comes with it. */
export function initTheme() {
  applyTheme();
  initDisplaySize();
  window.addEventListener("storage", (event) => {
    if (event.key === THEME_KEY) applyTheme();
  });
}
