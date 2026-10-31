/**
 * One run of an execution (owner D22/D23, 2026-10-26): the diagram of the version that ran with
 * each block's verdict and what each wire carried, its outputs and the signals it read. The last
 * runs of a subject keep each wire's samples (round 10), so clicking a block draws its charts;
 * an older run keeps the last values only, and "Show every sample" runs the same window again,
 * nothing saved, and the wires then carry their whole series.
 */
import { DEFAULT_TIMING, type Algorithm, type AlgorithmOutput, type AlgorithmTest, type SubjectRun } from "./types";
import type { DiagramTrace, TraceValue } from "@plantcraft/ui/blockEditor";
import { DataTable, type DataColumn } from "@plantcraft/ui";
import { FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";
import { AlgorithmDiagram } from "./AlgorithmDiagramLazy";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { resultLabel } from "./status";
import { formatMeasure, Link, Pill } from "./ui";

const outputColumns: DataColumn<AlgorithmOutput>[] = [
  { key: "name", label: t("Output"), render: (item) => <b>{item.name || item.key}</b> },
  { key: "status", label: t("Status"), render: (item) => <Pill status={item.status} label={resultLabel(item.status)} /> },
  { key: "value", label: t("Value"), numeric: true, render: (item) => <span className="pc-num">{item.value === null || item.value === undefined ? "—" : formatMeasure({ label: "", value: item.value, format: "number" })}</span> },
  { key: "message", label: t("What it found"), className: "hide-narrow", render: (item) => <small>{item.message || item.text}</small> },
];

/** A run that kept only the last value of each series: that value, as a number (one point
 * draws no chart). */
export function lastValues(trace: DiagramTrace): DiagramTrace {
  return Object.fromEntries(Object.entries(trace).map(([node, ports]) => [node, Object.fromEntries(Object.entries(ports).map(([port, value]): [string, TraceValue] => {
    if (value.type === "series" && value.v.length < 2 && typeof value.last === "number") return [port, { type: "number", value: value.last }];
    return [port, value];
  }))]));
}

export default function RunView({ run, algorithmId, subject }: { run: SubjectRun; algorithmId: string; subject: string }) {
  const [algorithm, setAlgorithm] = useState<Algorithm | null>(null);
  const [missing, setMissing] = useState("");
  const [full, setFull] = useState<AlgorithmTest | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setAlgorithm(null); setMissing(""); setFull(null);
    if (!algorithmId) return;
    // The diagram of the version that ran; the current one when the run did not say.
    const load = run.version ? api.algorithmVersion(algorithmId, run.version) : api.algorithm(algorithmId);
    load.then(setAlgorithm).catch((err: Error) => setMissing(err.message));
  }, [algorithmId, run.version, run.id, run.at]);
  async function everySample() {
    if (!algorithm || !run.window) return;
    setRunning(true); setError("");
    try {
      setFull(run.on === "asset"
        ? await api.testOnAsset(algorithm.diagram, subject, algorithm.timing ?? DEFAULT_TIMING, run.window.end)
        : await api.testAlgorithm(algorithm.diagram, subject, run.window));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }
  const signals = Object.entries(run.signals ?? {});
  const trace = full?.trace ?? (run.sampled ? run.wires : lastValues(run.wires));
  return <div className="run-view">
    <section className="panel run-head" aria-label={t("This run")}>
      <dl className="run-facts">
        <div><dt>{t("When")}</dt><dd>{formatDate(run.at)}</dd></div>
        <div><dt>{t("Version")}</dt><dd>{run.version ? <Link to={`/algorithms/${encodeURIComponent(algorithmId)}?version=${run.version}`}>{t("version {n}", { n: run.version })}</Link> : "—"}</dd></div>
        <div><dt>{t("Data read")}</dt><dd>{run.window ? `${formatDate(run.window.start)} – ${formatDate(run.window.end)}` : "—"}</dd></div>
      </dl>
    </section>
    <section className="panel" aria-label={t("Diagram")}>
      <div className="panel-header">
        <div><h2>{t("Diagram")}</h2><p>{full ? t("Every sample of this window, run again just now; nothing was saved.")
          : run.sampled ? t("What each block said and what each wire carried. Click a block to see its charts.")
          : t("What each block said and the last value on each wire: this run is too old to keep its samples. Show every sample runs its window again.")}</p></div>
        {run.window && algorithm && <div className="row-actions">
          <button type="button" className="button button-secondary" disabled={running || !!full} onClick={() => void everySample()}><FlaskConical size={16} />{running ? t("Running…") : t("Show every sample")}</button>
        </div>}
      </div>
      {error && <p className="alg-test-error" role="alert">{error}</p>}
      {missing ? <p className="muted">{missing}</p>
        : !algorithm ? <p className="muted">{t("Drawing the algorithm…")}</p>
        : <AlgorithmDiagram algorithmId={algorithmId} algorithm={algorithm} trace={trace} blocks={run.blocks} />}
    </section>
    {(run.outputs ?? []).length > 0 && <section className="panel" aria-label={t("Outputs of this run")}>
      <div className="panel-header"><div><h2>{t("Outputs")}</h2><p>{t("What each output of this run said.")}</p></div></div>
      <DataTable rows={run.outputs} columns={outputColumns} rowKey={(item) => item.node_id || item.key} label={t("Outputs of this run")} empty={t("No outputs.")} />
    </section>}
    {signals.length > 0 && <section className="panel" aria-label={t("Signals read")}>
      <div className="panel-header"><div><h2>{t("Signals read")}</h2><p>{t("The signal each input block read in this run.")}</p></div></div>
      <div className="blk-table-wrap"><table className="table">
        <thead><tr><th>{t("Input")}</th><th>{t("Signal")}</th></tr></thead>
        <tbody>{signals.map(([node, signal]) => <tr key={node}><td className="pc-mono">{node}</td><td className="pc-mono">{signal}</td></tr>)}</tbody>
      </table></div>
    </section>}
  </div>;
}
