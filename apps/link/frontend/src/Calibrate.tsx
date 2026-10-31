/**
 * Calibrate, in the inspector of a Deviation (T²) or an Empirical model (PCA) block: the
 * algorithm runs on one asset over a period of normal operation, as its cycle would have, and the
 * residuals' mean and covariance (or the signals' principal components) become the block's
 * calibration parameter. Nothing is saved until the algorithm is.
 */
import type { Diagram, DiagramNode } from "@plantcraft/ui/blockEditor";
import { AlertTriangle, Gauge, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { assetChoices } from "./AssetSettings";
import { formatDate, formatNumber, t } from "./i18n";
import type { AssetChoice, AssetTiming, Calibration, CalibrationAnswer } from "./types";
import { isoOf, localOf } from "@plantcraft/ui";

export const DEVIATION_BLOCK = "model.deviation";
/** The blocks Calibrate fills: a Deviation (T²) and an Empirical model (PCA, M4). */
export const CALIBRATED_BLOCKS = new Set([DEVIATION_BLOCK, "model.empirical"]);
const HOUR = 3_600_000;

/** A moment as a datetime-local input writes it (display time zone, to the minute). */
function localInput(moment: number): string {
  return localOf(new Date(moment).toISOString());
}

/** The diagram with ``calibration`` as the parameter of node ``nodeId``. */
export function withCalibration(diagram: Diagram, nodeId: string, calibration: Calibration): Diagram {
  return { ...diagram, nodes: diagram.nodes.map((node) => (node.id === nodeId ? { ...node, parameters: { ...node.parameters, calibration } } : node)) };
}

/** What the block's calibration says, in one line (or that there is none). */
export function calibrationLine(calibration: Calibration | null | undefined, assetName?: string): string {
  if (!calibration) return t("Not calibrated yet: it judges nothing until it is.");
  const where = assetName || calibration.asset;
  const when = calibration.start && calibration.end ? t("{start} to {end}", { start: formatDate(calibration.start), end: formatDate(calibration.end) }) : "";
  return [t("Calibrated on {count} samples", { count: calibration.samples }), where, when].filter(Boolean).join(" · ");
}

export function CalibrateTool({ node, diagram, timing, assets, readOnly, disabled, onCalibrated }: {
  node: DiagramNode; diagram: Diagram; timing: AssetTiming; assets: string[]; readOnly: boolean; disabled: string;
  onCalibrated: (next: Diagram) => void;
}) {
  const calibration = (node.parameters?.calibration ?? null) as Calibration | null;
  const [choices, setChoices] = useState<AssetChoice[]>([]);
  const [assetId, setAssetId] = useState(calibration?.asset ?? assets[0] ?? "");
  const [start, setStart] = useState(() => localInput(Date.now() - 6 * HOUR));
  const [end, setEnd] = useState(() => localInput(Date.now()));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState<CalibrationAnswer | null>(null);
  useEffect(() => { assetChoices().then(setChoices).catch(() => setChoices([])); }, []);
  useEffect(() => { setAssetId((now) => now || assets[0] || ""); }, [assets]);
  const named = assets.map((item) => choices.find((choice) => choice.id === item) ?? { id: item, name: item, path: "", kind: "", roles: [] });
  const options = named.length ? named : choices;
  const nameOf = (id?: string) => choices.find((item) => item.id === id)?.name ?? id;

  async function run() {
    setRunning(true); setError(""); setAnswer(null);
    try {
      const found = await api.calibrate(diagram, node.id, assetId, timing, isoOf(start), isoOf(end));
      setAnswer(found);
      onCalibrated(withCalibration(diagram, node.id, found.calibration));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }

  const shown = answer?.calibration ?? calibration;
  return <div className="calibrate">
    <strong><Gauge size={14} /> {t("Calibration")}</strong>
    <p className="muted small">{calibrationLine(shown, nameOf(shown?.asset))}</p>
    {shown && <ul className="calibrate-outputs">
      {shown.outputs.map((name, index) => <li key={name}><span>{name}</span><small>{t("mean {mean}, spread {std}", { mean: formatNumber(shown.mean[index], 3), std: formatNumber((shown.std ?? [])[index] ?? Math.sqrt(shown.cov?.[index]?.[index] ?? 0), 3) })}</small></li>)}
    </ul>}
    {shown?.kind === "pca" && <p className="muted small">{t("{k} principal components explain {share}% of the signals' variance.", { k: shown.eigenvalues?.length ?? 0, share: formatNumber(100 * (shown.explained ?? 0), 1) })}</p>}
    {(shown?.warnings ?? []).map((item) => <p key={item} className="calibrate-warning"><AlertTriangle size={12} /> {item}</p>)}
    {answer && <p className="muted small">{answer.skipped
      ? t("{used} of {runs} runs used; {skipped} left out: {reason}", { used: answer.used, runs: answer.runs, skipped: answer.skipped, reason: answer.skipped_reason })
      : t("All {runs} runs used. Save the algorithm to keep it.", { runs: answer.runs })}</p>}
    {!readOnly && <>
      <label>{t("Asset")}<select value={assetId} disabled={!options.length} onChange={(event) => setAssetId(event.target.value)}>
        {!assetId && <option value="">{t("Choose an asset…")}</option>}
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <span className="calibrate-period">
        <label>{t("From")}<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label>{t("To")}<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      </span>
      <small className="muted">{t("Pick a period of normal operation: the model's residuals there are what normal looks like.")}</small>
      <button type="button" className="button button-secondary" disabled={!!disabled || running || !assetId || !start || !end} title={disabled || undefined} onClick={() => void run()}>
        {running ? <LoaderCircle size={15} className="spin" /> : <Gauge size={15} />}{t("Calibrate")}
      </button>
    </>}
    {error && <p className="calibrate-warning" role="alert"><AlertTriangle size={12} /> {error}</p>}
  </div>;
}
