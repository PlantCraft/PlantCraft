/**
 * The trend of a runs point (H2): one whole series per execution of the app that writes it
 * (Link's series outputs). Pick a run, or draw the newest few together: runs over the same
 * window overlay, runs over consecutive windows read as one continuous series.
 */
import { timeFigure, type TimeLine, useBrandTheme } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatMs } from "./format";
import { t } from "./i18n";
import type { Point, RunInfo, RunsSeries } from "./types";
import { ErrorBox, Loading } from "./ui";

// What the picker offers besides one run: the newest run, or the newest few drawn together.
export const RUN_GROUPS = [1, 5, 10] as const;

/** The picker's value as a read: "latest", "last:5" or a run's ISO time. */
export function runPick(value: string): { run?: string; runs?: number } {
  if (value.startsWith("last:")) return { runs: Number(value.slice(5)) };
  return value === "latest" ? { runs: 1 } : { run: value };
}

/** The runs read as lines, each named by when it ran. */
export function runLines(found: RunsSeries, unit: string): TimeLine[] {
  return found.runs.map((run, index) => ({
    name: t("Run of {when}", { when: formatMs(Date.parse(run.run_at)) }),
    t: run.t, v: run.v, unit,
    ...(index ? { dash: "dot" as const } : {}),
  }));
}

export function RunsTrend({ point, signal, tag }: { point: Point; signal: string; tag: string }) {
  const theme = useBrandTheme();
  const [list, setList] = useState<RunInfo[] | null>(null);
  const [pick, setPick] = useState("latest");
  const [found, setFound] = useState<RunsSeries | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => api.runList(signal).then((answer) => setList(answer.runs)).catch((err: Error) => setError(err.message));
    void load();
    const timer = window.setInterval(load, 60_000);
    return () => window.clearInterval(timer);
  }, [signal]);
  useEffect(() => {
    api.runs(signal, runPick(pick)).then((answer) => { setFound(answer); setError(""); }).catch((err: Error) => setError(err.message));
  }, [signal, pick, list?.[0]?.run_at]);

  const figure = useMemo(() => (found?.runs.length ? timeFigure({ lines: runLines(found, point.unit), height: 340, filename: tag }, theme) : null), [found, point.unit, tag, theme]);
  const keep = point.keep_runs ? t("The newest {count} runs are kept.", { count: point.keep_runs }) : "";
  return <div className="panel">
    <div className="panel-header"><div><h2>{t("Runs")}</h2><p>{t("One series per run of {app}.", { app: point.managed_by || point.source_id })} {keep}</p></div>
      <label className="inline-select">{t("Show")}<select value={pick} onChange={(event) => setPick(event.target.value)}>
        {RUN_GROUPS.map((count) => <option key={count} value={count === 1 ? "latest" : `last:${count}`}>{count === 1 ? t("Latest run") : t("The last {count} runs together", { count })}</option>)}
        {(list ?? []).map((run) => <option key={run.run_at} value={run.run_at}>{t("Run of {when} ({count} values)", { when: formatMs(Date.parse(run.run_at)), count: run.n })}</option>)}
      </select></label>
    </div>
    {error && <ErrorBox text={error} />}
    {!found && !error ? <Loading /> : figure
      ? <Plot data={figure.data} layout={figure.layout} config={figure.config} style={{ width: "100%" }} useResizeHandler />
      : <p className="muted empty">{t("No runs yet.")}</p>}
  </div>;
}
