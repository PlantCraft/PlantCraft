/**
 * Versions of a model and of a block, as Link's (round 9 M3, M4). Each save of a file keeps the
 * text it replaced, so version N of M is the file as it was before the save that made N + 1;
 * version M is the one in use. A model's version opens read-only (`?version=N`) and Use this
 * version saves it again as the newest; two or three versions compare: a model's run on the same
 * simulation settings (the ones in use) with their series on one chart, a block's ports and code side
 * by side.
 */
import type * as Plotly from "plotly.js";
import { CodeDiff, comparedVersions, currentTheme, lineDiff, plotTheme, seriesVar } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { GitCompare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatDuration, t } from "./i18n";
import type { CatalogBlock, Revision, Run, SeriesAnswer } from "./types";
import { runPath } from "./paths";
import { ErrorBox, Link, Loading, message, reading, RunPill } from "./ui";

/** The revision id a version number names: 0 for the version in use, null when there is none. */
export function revisionOf(revisions: Revision[], number: number): number | null {
  const count = revisions.length + 1;
  if (number === count) return 0;
  if (number < 1 || number > count) return null;
  return revisions[count - 1 - number]?.id ?? null;
}

/** `?version=N` of a model's page: the version it shows, or null for the one in use. */
export function shownVersion(search: string): number | null {
  const value = Number(new URLSearchParams(search).get("version") ?? "");
  return Number.isInteger(value) && value > 0 ? value : null;
}

/** `?runs=a,b` of a model's Compare tab: the runs a comparison started, kept on reload. */
export function comparedRuns(search: string): string[] {
  return (new URLSearchParams(search).get("runs") ?? "").split(",").filter(Boolean).slice(0, 3);
}

/** Final, lowest and highest value of a series (nulls left out). */
export function seriesFacts(values: Array<number | null>): { final: number | null; min: number | null; max: number | null } {
  const found = values.filter((value): value is number => value !== null && Number.isFinite(value));
  if (!found.length) return { final: null, min: null, max: null };
  return { final: found[found.length - 1], min: Math.min(...found), max: Math.max(...found) };
}

const ended = (run: Run) => run.status !== "queued" && run.status !== "running";

/**
 * A model's Compare tab (`/compare?versions=1,3`): Run and compare simulates each version with the
 * settings in use; the chosen variable of each run on one chart, then each run's final, lowest and
 * highest value and its run time.
 */
export function ModelCompare({ projectId, model, revisions, signals, canRun }: {
  projectId: string; model: string; revisions: Revision[] | null; signals: string[]; canRun: boolean;
}) {
  const numbers = comparedVersions(window.location.search);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [variable, setVariable] = useState(signals[0] ?? "");
  const [series, setSeries] = useState<Record<string, SeriesAnswer>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const asked = comparedRuns(window.location.search);
  useEffect(() => {
    if (!asked.length) return;
    Promise.all(asked.map((runId) => api.run(runId))).then(setRuns).catch((err) => setError(message(err)));
    // The runs the address names are read once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Follow the runs until each has ended.
  useEffect(() => {
    if (!runs || runs.every(ended)) return;
    const timer = window.setTimeout(() => { Promise.all(runs.map((run) => (ended(run) ? run : api.run(run.id)))).then(setRuns).catch(() => undefined); }, 1000);
    return () => window.clearTimeout(timer);
  }, [runs]);
  const done = useMemo(() => (runs ?? []).filter((run) => run.status === "done").map((run) => run.id).join(","), [runs]);
  useEffect(() => {
    if (!done || !variable) { setSeries({}); return; }
    const ids = done.split(",");
    Promise.all(ids.map((runId) => api.series(runId, [variable], 1500).then((answer) => [runId, answer] as const)))
      .then((pairs) => setSeries(Object.fromEntries(pairs))).catch((err) => setError(message(err)));
  }, [done, variable]);
  if (!revisions) return <Loading />;
  const chosen = numbers.map((number) => ({ number, revision: revisionOf(revisions, number) })).filter((item): item is { number: number; revision: number } => item.revision !== null);
  if (chosen.length < 2) return <section className="panel"><p className="muted">{t("Tick two or three versions on the Versions tab, then Compare.")}</p></section>;
  const labels = chosen.map((item) => t("Version {number}", { number: item.number }));
  const start = async () => {
    setBusy(true); setError("");
    try {
      const started = await api.compareModel(projectId, model, chosen.map((item) => item.revision), labels);
      setRuns(started);
      window.history.replaceState({}, "", `${window.location.pathname}?versions=${chosen.map((item) => item.number).join(",")}&runs=${started.map((run) => run.id).join(",")}`);
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  };
  const theme = plotTheme(currentTheme());
  const traces: Plotly.Data[] = (runs ?? []).flatMap((run, index) => (series[run.id]?.series ?? []).map((item) => ({
    type: "scatter", mode: "lines", name: run.label || labels[index], x: item.time, y: item.values, line: { color: seriesVar(index), width: 2 },
  } as Plotly.Data)));
  return <div className="mc-compare">
    <section className="panel">
      <div className="panel-header"><div>
        <h2>{t("Compare {versions}", { versions: labels.join(", ") })}</h2>
        <p>{t("Each version runs with the same simulation settings: the start, stop, step and solver of the version in use. Nothing in the model changes.")}</p>
      </div>
        {canRun && <button type="button" className="button button-primary" disabled={busy || Boolean(runs && !runs.every(ended))} onClick={() => void start()}><GitCompare size={16} />{runs ? t("Run them again") : t("Run and compare")}</button>}
      </div>
      {error && <ErrorBox text={error} />}
      {!runs ? <p className="muted">{canRun ? t("Run and compare simulates each version once.") : t("Only editors run simulations.")}</p> : <>
        <label className="mc-inline-field">{t("Variable")}
          <input list="mc-compare-signals" value={variable} onChange={(event) => setVariable(event.target.value.trim())} placeholder={t("e.g. tank.level")} />
          <datalist id="mc-compare-signals">{signals.map((name) => <option key={name} value={name} />)}</datalist>
        </label>
        {traces.length > 0 && <Plot data={traces} useResizeHandler style={{ width: "100%", height: 420 }} config={{ displaylogo: false, responsive: true }}
          layout={{ ...theme, autosize: true, height: 420, margin: { l: 56, r: 16, t: 16, b: 48 }, legend: { ...theme.legend, orientation: "h", y: -0.2 },
            xaxis: { ...theme.xaxis, title: { text: t("Time [s]") } }, yaxis: { ...theme.yaxis, title: { text: variable } } }} />}
        <table className="table mc-compare-table">
          <thead><tr><th scope="col">{t("Version")}</th><th scope="col">{t("Status")}</th><th scope="col" className="numeric">{t("Final")}</th><th scope="col" className="numeric">{t("Lowest")}</th><th scope="col" className="numeric">{t("Highest")}</th><th scope="col" className="numeric">{t("Run time")}</th></tr></thead>
          <tbody>{runs.map((run, index) => {
            const values = series[run.id]?.series[0]?.values ?? [];
            const facts = seriesFacts(values);
            return <tr key={run.id}>
              <th scope="row"><Link to={runPath(run)}>{run.label || labels[index]}</Link></th>
              <td><RunPill run={run} /></td>
              <td className="numeric pc-num">{facts.final === null ? "–" : reading(facts.final)}</td>
              <td className="numeric pc-num">{facts.min === null ? "–" : reading(facts.min)}</td>
              <td className="numeric pc-num">{facts.max === null ? "–" : reading(facts.max)}</td>
              <td className="numeric pc-num">{run.seconds === null ? "–" : formatDuration(run.seconds)}</td>
            </tr>;
          })}</tbody>
        </table>
        {Object.values(series).some((answer) => answer.missing.length) && <p className="muted small">{t("{name} is not in the results of every version.", { name: variable })}</p>}
      </>}
    </section>
  </div>;
}

type BlockAt = { number: number; block: CatalogBlock & { code: string; missing?: boolean } };

/** Each port and parameter of the versions, a row each, with what it is in every version. */
export function contractRows(versions: Array<Pick<CatalogBlock, "inputs" | "outputs" | "parameters">>): Array<{ kind: string; name: string; values: string[]; changed: boolean }> {
  const rows: Array<{ kind: string; name: string; values: string[]; changed: boolean }> = [];
  const add = (kind: string, names: string[], describe: (index: number, name: string) => string) => {
    for (const name of names) {
      const values = versions.map((_, index) => describe(index, name));
      rows.push({ kind, name, values, changed: new Set(values).size > 1 });
    }
  };
  const unique = (list: string[]) => [...new Set(list)];
  add(t("Input"), unique(versions.flatMap((item) => item.inputs.map((port) => port.port))), (index, name) => {
    const port = versions[index].inputs.find((item) => item.port === name);
    return port ? [port.type, port.unit].filter(Boolean).join(" · ") || "✓" : "–";
  });
  add(t("Output"), unique(versions.flatMap((item) => item.outputs.map((port) => port.port))), (index, name) => {
    const port = versions[index].outputs.find((item) => item.port === name);
    return port ? [port.type, port.unit].filter(Boolean).join(" · ") || "✓" : "–";
  });
  add(t("Parameter"), unique(versions.flatMap((item) => item.parameters.map((parameter) => parameter.name))), (index, name) => {
    const parameter = versions[index].parameters.find((item) => item.name === name);
    return parameter ? String(parameter.default ?? "") || "✓" : "–";
  });
  return rows;
}

/** A block's Compare tab: its inputs, outputs and parameters in a column per version, then what
 * changed in the code from the oldest to the newest of them. */
export function BlockCompare({ block, revisions }: { block: CatalogBlock & { code?: string }; revisions: Revision[] | null }) {
  const numbers = comparedVersions(window.location.search);
  const [versions, setVersions] = useState<BlockAt[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!revisions) return;
    const wanted = numbers.map((number) => ({ number, revision: revisionOf(revisions, number) })).filter((item): item is { number: number; revision: number } => item.revision !== null);
    Promise.all(wanted.map(async (item): Promise<BlockAt> => ({ number: item.number, block: item.revision ? await api.blockVersion(block.block_id, item.revision) : { ...block, code: block.code ?? "" } })))
      .then(setVersions).catch((err) => setError(message(err)));
    // `numbers` comes from the address, read with the revisions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revisions, block]);
  if (error) return <ErrorBox text={error} />;
  if (!revisions || !versions) return <Loading />;
  if (versions.length < 2) return <section className="panel"><p className="muted">{t("Tick two or three versions on the Versions tab, then Compare.")}</p></section>;
  const rows = contractRows(versions.map((item) => item.block));
  const oldest = versions[0];
  const newest = versions[versions.length - 1];
  return <div className="mc-compare">
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Inputs, outputs and parameters")}</h2><p>{t("A row in colour changed between the versions; – means the version does not have it.")}</p></div></div>
      <table className="table mc-compare-table">
        <thead><tr><th scope="col">{t("Type")}</th><th scope="col">{t("Name")}</th>{versions.map((item) => <th key={item.number} scope="col">{t("Version {number}", { number: item.number })}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={`${row.kind}-${row.name}`} className={row.changed ? "mc-compare-changed" : undefined}>
          <td>{row.kind}</td><th scope="row" className="pc-mono">{row.name}</th>{row.values.map((value, index) => <td key={index}>{value}</td>)}
        </tr>)}</tbody>
      </table>
      {versions.some((item) => item.block.missing) && <p className="muted small">{t("A version without the block: its library did not have it then.")}</p>}
    </section>
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Code: version {from} to {to}", { from: oldest.number, to: newest.number })}</h2><p>{t("The library file, as each version saved it.")}</p></div></div>
      <CodeDiff lines={lineDiff(oldest.block.code, newest.block.code)} />
    </section>
  </div>;
}
