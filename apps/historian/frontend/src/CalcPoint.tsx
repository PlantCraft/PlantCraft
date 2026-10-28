import { Dialog } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { navigate } from "./nav";
import { pointPath } from "./PointsPage";
import type { Point } from "./types";
import { ErrorBox } from "./ui";

/** Every calculated point lives in this source (created with the first one). */
export const CALC_SOURCE = "calc";

/** Points a formula can read: numbers the collector archives (catalog/store.py `_not_an_input`). */
export const formulaInputs = (points: Point[]) => points.filter((point) =>
  point.kind === "number" && (point.source_kind === "opcua" || point.source_kind === "calc") && (point.mode === "archive" || point.mode === "both"));

/** What a formula may hold, in a few lines with examples (catalog/expressions.py). */
export function FormulaHelp() {
  return <small className="formula-help">
    {t("Signals are written [source:tag]. Use numbers, + - * / ** %, comparisons (true is 1), and, or, not and abs, min, max, sqrt, exp, log, log10, round, clip, if.")}
    <span>{t("Examples:")} <code>[plant:FI-100.PV] * 3.6</code> · <code>if([plant:XV-1.PV] {">"} 0.5, [plant:FI-1.PV], 0)</code></span>
    <span>{t("A totalizer is the whole formula:")} <code>total([plant:FI-100.PV], per="h", reset="day")</code> {t("integrates a rate per s, min, h or d and restarts each hour, day or month (UTC), or never.")}</span>
    <span>{t("Inputs are signals archived here (OPC UA in mode archive or both, or other calculated signals). Any input bad makes a gap; any input uncertain makes the result uncertain.")}</span>
  </small>;
}

/** A new calculated point: its tag, formula, unit and scan; it opens once added. */
export function CalcPointDialog({ onClose }: { onClose: () => void }) {
  const [draft, setDraft] = useState({ tag: "", address: "", unit: "", description: "", scan_seconds: "" });
  const [inputs, setInputs] = useState<Point[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.points().then((points) => setInputs(formulaInputs(points))).catch(() => setInputs([])); }, []);
  const signals = useMemo(() => new Set(inputs.map((point) => point.signal)), [inputs]);
  const set = (key: keyof typeof draft) => (event: { target: { value: string } }) => setDraft({ ...draft, [key]: event.target.value });
  function insert(signal: string) {
    if (!signals.has(signal)) return;
    setDraft((now) => ({ ...now, address: `${now.address}${now.address && !now.address.endsWith(" ") ? " " : ""}[${signal}]` }));
  }
  async function add() {
    setBusy(true); setError("");
    try {
      const scan = Number(draft.scan_seconds);
      const done = await api.addPoints([{ source_id: CALC_SOURCE, tag: draft.tag.trim(), address: draft.address, unit: draft.unit, description: draft.description,
        ...(draft.scan_seconds.trim() && scan > 0 ? { scan_seconds: scan } : {}) }]);
      if (done.skipped.length) { setError(done.skipped[0].reason); return; }
      navigate(pointPath(done.added[0]));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <Dialog title={t("Add calculated signal")} onClose={onClose} onSubmit={(event) => { event.preventDefault(); void add(); }}>
      <p className="muted">{t("The collector evaluates the formula on every scan from the latest values of its inputs and archives the result like any signal.")}</p>
      {error && <ErrorBox text={error} />}
      <div className="form-grid">
        <label>{t("Tag")}<input required value={draft.tag} placeholder="FI-100.NM3H" onChange={set("tag")} /><small>{t("API signal id: calc:<tag>.")}</small></label>
        <label>{t("Unit")}<input value={draft.unit} onChange={set("unit")} /></label>
        <label className="formula">{t("Formula")}
          <textarea className="pc-mono" required rows={2} value={draft.address} placeholder="[plant:FI-100.PV] * 3.6" onChange={set("address")} />
          <FormulaHelp /></label>
        <label>{t("Insert a signal")}<input list="calc-inputs" placeholder={t("Search tag")} onChange={(event) => { insert(event.target.value); if (signals.has(event.target.value)) event.target.value = ""; }} />
          <datalist id="calc-inputs">{inputs.map((point) => <option key={point.signal} value={point.signal}>{point.description || point.name}</option>)}</datalist>
          <small>{t("{count} signals can be read by a formula.", { count: inputs.length })}</small></label>
        <label>{t("Scan period (s)")}<input type="number" step="any" min="0.1" value={draft.scan_seconds} placeholder={t("General setting")} onChange={set("scan_seconds")} /></label>
        <label className="formula">{t("Description")}<input value={draft.description} onChange={set("description")} /></label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button type="submit" className="button button-primary" disabled={busy || !draft.tag.trim() || !draft.address.trim()}>{t("Add")}</button></footer>
  </Dialog>;
}
