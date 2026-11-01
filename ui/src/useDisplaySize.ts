import { useEffect, useState } from "react";
import { currentDisplaySize, type DisplaySize } from "./displaySize.js";

/**
 * The display size in effect, kept current: the user menu's choice, another tab's, a change of
 * <html data-size>. Code that sizes things in pixels (the card grid's rows, a chart's height)
 * multiplies by `displayScales(size)` so a page drawn once fits at all five sizes.
 */
export function useDisplaySize(): DisplaySize {
  const [size, setSize] = useState<DisplaySize>(currentDisplaySize);
  useEffect(() => {
    const update = () => setSize(currentDisplaySize());
    window.addEventListener("plantcraft-ui:display-size", update);
    window.addEventListener("storage", update);
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-size"] });
    return () => {
      window.removeEventListener("plantcraft-ui:display-size", update);
      window.removeEventListener("storage", update);
      observer?.disconnect();
    };
  }, []);
  return size;
}
