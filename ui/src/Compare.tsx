/**
 * Comparing versions of an object (round 9: Link's blocks and algorithms, Models' blocks and
 * models): under the versions list, tick two or three and Compare; `?versions=1,3` names them;
 * a code difference reads as `git diff` does. What a comparison runs is the app's.
 */
import { GitCompare } from "lucide-react";
import { useState } from "react";
import type { DiffLine } from "./diff.js";
import { t } from "./i18n.js";

/** At most three versions side by side: more lines on one chart stop being readable. */
export const COMPARE_MAX = 3;

/** The versions `?versions=` names, smallest first, at most COMPARE_MAX. */
export function comparedVersions(search: string): number[] {
  const raw = new URLSearchParams(search).get("versions") ?? "";
  const numbers = raw.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0);
  return [...new Set(numbers)].sort((a, b) => a - b).slice(0, COMPARE_MAX);
}

/** Under the versions list: tick two or three, then Compare hands them over (smallest first). */
export function ComparePicker({ numbers, onCompare, text }: { numbers: number[]; onCompare: (ticked: number[]) => void; text?: string }) {
  const [ticked, setTicked] = useState<number[]>([]);
  if (numbers.length < 2) return null;
  const toggle = (number: number) => setTicked((now) => (now.includes(number) ? now.filter((item) => item !== number) : now.length >= COMPARE_MAX ? now : [...now, number]));
  return <section className="panel pc-compare-picker" aria-label={t("Compare versions")}>
    <div className="panel-header"><div><h2>{t("Compare versions")}</h2><p>{text ?? t("Tick two or three versions to see them side by side.")}</p></div></div>
    <div className="pc-compare-ticks" role="group" aria-label={t("Versions to compare")}>
      {[...numbers].sort((a, b) => b - a).map((number) => <label key={number} className={`pc-compare-tick${ticked.includes(number) ? " active" : ""}`}>
        <input type="checkbox" checked={ticked.includes(number)} disabled={!ticked.includes(number) && ticked.length >= COMPARE_MAX} onChange={() => toggle(number)} />
        {t("Version {number}", { number })}
      </label>)}
    </div>
    <div className="row-actions">
      <button type="button" className="button button-primary" disabled={ticked.length < 2} onClick={() => onCompare([...ticked].sort((a, b) => a - b))}>
        <GitCompare size={16} />{ticked.length < 2 ? t("Compare") : t("Compare {n} versions", { n: ticked.length })}
      </button>
    </div>
  </section>;
}

/** The lines of code two versions differ in (`lineDiff`), or a line saying they are the same. */
export function CodeDiff({ lines, label }: { lines: DiffLine[]; label?: string }) {
  if (!lines.some((line) => line.kind !== "same")) return <p className="muted small">{t("The code is the same in both versions.")}</p>;
  return <pre className="pc-diff" aria-label={label ?? t("Differences in the code")}>{lines.map((line, index) => <span key={index} className={`pc-diff-${line.kind}`}>{line.kind === "added" ? "+ " : line.kind === "removed" ? "− " : "  "}{line.text}{"\n"}</span>)}</pre>;
}
