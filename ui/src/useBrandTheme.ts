import { useEffect, useState } from "react";
import { currentTheme, type BrandTheme } from "./brandTheme.js";

/**
 * The theme in effect, kept current: the user menu's choice (`setTheme`), another tab's, a
 * change of <html data-theme> and the system's preference all re-render. Charts drawn with
 * `plotTheme()` or `BRAND_COLORS` use it so they never keep the old theme's colours.
 */
export function useBrandTheme(): BrandTheme {
  const [theme, setThemeState] = useState<BrandTheme>(currentTheme);
  useEffect(() => {
    const update = () => setThemeState(currentTheme());
    window.addEventListener("plantcraft-ui:theme", update);
    window.addEventListener("storage", update);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener?.("change", update);
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      window.removeEventListener("plantcraft-ui:theme", update);
      window.removeEventListener("storage", update);
      media?.removeEventListener?.("change", update);
      observer?.disconnect();
    };
  }, []);
  return theme;
}
