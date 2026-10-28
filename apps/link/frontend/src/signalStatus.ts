import { t } from "./i18n";
import type { StatusTone } from "@plantcraft/ui";
import { RESULT } from "./status";

/** Signal verdicts of the Signal quality algorithm (worst first), their words and colour family.
 * `off`: the signal is switched off; `unchecked`: no verdict yet (the API sends null). */
export const SIGNAL_STATUS: Record<string, { label: string; tone: StatusTone; help: string }> = {
  bad: { label: "Bad", tone: "problem", help: "Not usable for analysis." },
  suspect: { label: "Suspect", tone: "attention", help: "Usable, with care: a check found a problem." },
  good: { label: "Good", tone: "good", help: "Every check passed." },
  unknown: { label: "Unknown", tone: "inactive", help: "Not enough data to judge." },
  unchecked: { label: "Not checked", tone: "inactive", help: "The Signal quality algorithm has not checked this signal yet." },
  off: { label: "Off", tone: "inactive", help: "Switched off: the algorithm skips this signal." },
};
export const SIGNAL_ORDER = ["bad", "suspect", "good", "unknown", "unchecked", "off"];
export const COUNTED = ["bad", "suspect", "good", "unknown"];

/** Order of check results, worst first. */
export const RESULT_ORDER = ["bad", "warning", "ok", "insufficient_data", "not_applicable"];

/** Run states of the algorithm. */
const RUN: Record<string, string> = { ok: "Finished", error: "Failed", running: "Running", interrupted: "Interrupted" };

/** The status id a signal row shows: null (never checked) reads as "unchecked". */
export const signalStatus = (status: string | null | undefined) => status ?? "unchecked";
export const signalLabel = (status: string | null | undefined) => t(SIGNAL_STATUS[signalStatus(status)]?.label ?? String(status));
export const checkResultLabel = (status: string) => t(RESULT[status]?.label ?? status);
export const runLabel = (status: string) => t(RUN[status] ?? status);

/** A signal's tag without its source (the Source column names it): `plantcraft:CPM.X.PV` -> `CPM.X.PV`. */
export function tagOf(row: { id: string; source: string }) {
  return row.source && row.id.startsWith(`${row.source}:`) ? row.id.slice(row.source.length + 1) : row.id;
}

/** The line under a signal's tag: what it measures, then the assets that use it. */
export function signalCaption(row: { name: string; description: string; assets: string[] }) {
  const what = row.description || row.name;
  const assets = row.assets.filter((asset) => !what.includes(asset));
  return [what, assets.join(", ")].filter(Boolean).join(" · ");
}
