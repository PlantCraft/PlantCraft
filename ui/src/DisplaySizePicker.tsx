/**
 * The display size picker of the user menu: five small screens in a row, each drawn with the
 * text and spacing it gives, from "Larger text" on the left to "More space" on the right.
 */
import { useEffect, useState } from "react";
import { DISPLAY_SIZES, displaySize, setDisplaySize, type DisplaySize } from "./displaySize.js";
import { t } from "./i18n.js";

/** A screen drawn at one step: the bigger the text, the fewer and thicker the lines. */
function ScreenGlyph({ step }: { step: DisplaySize }) {
  // 1 (Larger text) .. 5 (More space): line thickness and gap shrink, the count grows.
  const line = [3.4, 2.8, 2.2, 1.8, 1.4][step - 1];
  const gap = [2.6, 2.3, 2, 1.7, 1.4][step - 1];
  const rows: number[] = [];
  for (let y = 6.5; y + line <= 22; y += line + gap) rows.push(y);
  const widths = [17, 12, 15, 10, 16, 13, 11, 14];
  const rail = [7, 6.5, 6, 5.5, 5][step - 1];
  return (
    <svg className="pcs-size-glyph" viewBox="0 0 40 32" width="40" height="32" aria-hidden="true" focusable="false">
      <rect className="pcs-size-frame" x="1" y="1.5" width="38" height="24" rx="3" />
      <rect className="pcs-size-rail" x="3" y="3.5" width={rail} height="20" rx="1.5" />
      <rect className="pcs-size-title" x={rail + 5.5} y="4" width={[11, 10, 9, 8, 7][step - 1]} height={line * 0.9} rx={line / 3} />
      {rows.slice(1).map((y, index) => (
        <rect key={y} className="pcs-size-line" x={rail + 5.5} y={y} width={Math.min(widths[index % widths.length] * (1 - (5 - step) * 0.04), 36 - rail - 5.5)} height={line * 0.7} rx={line / 3} />
      ))}
      <path className="pcs-size-stand" d="M15 29.5h10M20 25.5v4" />
    </svg>
  );
}

export function DisplaySizePicker() {
  const [size, setSize] = useState<DisplaySize>(displaySize);
  // Another tab or app of the suite can change it while the menu is open.
  useEffect(() => {
    const update = () => setSize(displaySize());
    window.addEventListener("plantcraft-ui:display-size", update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener("plantcraft-ui:display-size", update);
      window.removeEventListener("storage", update);
    };
  }, []);
  function pick(value: DisplaySize) {
    setDisplaySize(value);
    setSize(value);
  }
  return (
    <div className="pcs-size">
      <div className="pcs-size-steps" role="radiogroup" aria-label={t("Display size")}>
        {DISPLAY_SIZES.map((item) => (
          <button key={item.value} role="radio" aria-checked={size === item.value} aria-label={t(item.label)} title={t(item.label)} className={size === item.value ? "pcs-on" : ""} onClick={() => pick(item.value)}>
            <ScreenGlyph step={item.value} />
          </button>
        ))}
      </div>
      <div className="pcs-size-ends" aria-hidden="true">
        <span>{t("Larger text")}</span>
        <span>{t("More space")}</span>
      </div>
    </div>
  );
}
