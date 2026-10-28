/** The suite's building blocks (@plantcraft/ui), and this app's own. */
import { ErrorBox, Health, Heading, Loading, Pill, statusVar } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api, checkCatalog } from "./api";
import { formatAgo, formatNumber, t } from "./i18n";
import { Link } from "./nav";
import { suiteLabel } from "./status";
import type { CheckSpec, Measure } from "./types";

export { ErrorBox, Health, Heading, Loading, Pill };

export { Link } from "./nav";

/** Quality 0-100 (100 is clean data) as a bar coloured by the signal's verdict. */
export function Quality({ value, status, bare = false }: { value?: number | null; status?: string | null; bare?: boolean }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const tone = status ?? (value >= 80 ? "good" : value >= 50 ? "suspect" : "bad");
  return <span className="health" title={t("Quality {value} of 100", { value: Math.round(value) })}><span className="health-bar"><span style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: statusVar(tone) }} /></span>{!bare && <b className="pc-num">{Math.round(value)}</b>}</span>;
}

/** The Data quality checks, for names and toggles. */
export function useCatalog(): CheckSpec[] {
  const [items, setItems] = useState<CheckSpec[]>([]);
  useEffect(() => { checkCatalog().then(setItems).catch(() => setItems([])); }, []);
  return items;
}

/** A check's name from the catalog, falling back to its id. */
export function checkName(catalog: CheckSpec[], checkId: string | null | undefined): string {
  if (!checkId) return "";
  return catalog.find((item) => item.id === checkId)?.name ?? checkId;
}

/** The path of a signal's page. */
export const signalPath = (signalId: string) => `/signals/${encodeURIComponent(signalId)}`;

/** A result's headline value as people read it: "30 %", "1.25 bar". A health and a score are
 * both on 0-100 and read the same way, in % (journey review 2026-10-23: "0 / 100" beside "0 %"). */
export function formatMeasure(measure: Measure): string {
  if (measure.value === null || measure.value === undefined) return "—";
  if (measure.format === "percent" || measure.format === "score") return `${formatNumber(measure.value, 0)} %`;
  return `${formatNumber(measure.value, 3)}${measure.unit ? ` ${measure.unit}` : ""}`;
}

/**
 * The first card of every result page, the same for a signal, a loop or any subject an algorithm
 * judges: what the result says ("Health 30 % · Alarm"), in its own words too, which algorithm said
 * it and when.
 */
export function ResultHeadline({ measure, status, native, algorithm, at }: { measure: Measure; status: string; native?: { label: string; status: string }; algorithm?: { id: string; name: string } | null; at?: string | null }) {
  return <div className="panel kpi-card result-headline pc-span-2" style={{ borderTopColor: statusVar(status) }} data-testid="result-headline">
    <span className="pc-overline">{t("Result")}</span>
    <div className="result-headline-main"><b className="pc-num">{measure.label} {formatMeasure(measure)}</b><Pill status={status} label={suiteLabel(status)} /></div>
    <small>{[
      native && native.label !== suiteLabel(status) ? native.label : null,
      algorithm?.name ? t("by the {algorithm} algorithm", { algorithm: algorithm.name }) : null,
      at ? t("checked {ago}", { ago: formatAgo(at) }) : null,
    ].filter(Boolean).join(" · ")}{algorithm?.id && <> · <Link to={`/algorithms/${encodeURIComponent(algorithm.id)}`}>{t("Open the algorithm")}</Link></>}</small>
  </div>;
}
