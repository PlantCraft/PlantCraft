/**
 * Executions by schedule (owner, 2026-10-24: Executions and Results were the same thing by two
 * paths). The page opens on the schedules; a schedule shows its subjects with the latest result
 * of each; a subject (an execution: the schedule's runs on it) shows its outputs over time from the
 * Historian (with a mark where a new version of the algorithm started), its last run on the
 * diagram, and its runs, each opening in the execution. The live queue is
 * the page's second tab. Status is a discreet word beside each subject, never an order: lists go
 * by name, and what deserves attention is the Alarms app's job.
 */
import { chosenFolder, DataTable, FolderColumn, inFolder, PageTabs, PeriodPicker, periodRange, rememberFolder, statusVar, timeFigure, useAssistantPage, useBrandTheme, useFolders, type DataColumn, type TimeLine, type TimePeriod } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { href, navigate } from "./nav";
import { Plot } from "@plantcraft/ui/plot";
import type { ExecutionGroup, GroupPast, GroupSubject, Me, OwnSeries, SubjectHistory, SubjectOutput } from "./types";
import { ErrorBox, formatMeasure, Heading, Link, Loading } from "./ui";

/** The pages ask again this often: executions end while one reads. */
const POLL_MS = 30_000;
/** How long Link keeps a run (``JobStore.prune_jobs``). */
const RUNS_KEPT_DAYS = 90;
// The diagram (React Flow) loads only when a run is opened.
const RunView = lazy(() => import("./RunView"));

export const EXECUTIONS_TABS = (active: "schedules" | "queue") => <PageTabs label={t("Results")} href={href} navigate={navigate} tabs={[
  { to: "/executions", label: t("By monitor"), active: active === "schedules" },
  { to: "/executions/queue", label: t("Queue"), active: active === "queue" },
]} />;

/** A status as one quiet word with a dot of its colour (High, Critical, OK...). */
export function StatusWord({ state, label }: { state: string; label: string }) {
  if (!label) return null;
  return <span className="status-word"><i style={{ background: statusVar(state) }} aria-hidden="true" />{label}</span>;
}

/** "3 OK · 1 warning · 2 critical": how a schedule's subjects ended, in one line. */
export function countsText(counts: ExecutionGroup["counts"]): string {
  const parts = [
    counts.ok ? t("{n} OK", { n: counts.ok }) : "",
    counts.warning ? t("{n} warning", { n: counts.warning }) : "",
    counts.alarm ? t("{n} critical", { n: counts.alarm }) : "",
    counts.unknown ? t("{n} without a result", { n: counts.unknown }) : "",
  ].filter(Boolean);
  return parts.join(" · ") || t("Nothing ran yet");
}

/** How often a schedule runs, as people say it. */
export function cadenceText(group: ExecutionGroup): string {
  if (group.kind === "manual") return t("When a person asks");
  if (group.cadence === "calendar" && group.when) return group.when;
  if (group.cadence === "interval" && group.interval_minutes) {
    const minutes = group.interval_minutes;
    return minutes % 60 === 0 ? t("Every {n} h", { n: minutes / 60 }) : t("Every {n} min", { n: minutes });
  }
  if (group.cadence === "daily") return t("Daily");
  if (group.cadence === "weekly") return t("Weekly");
  return group.cadence ? t(group.cadence) : "";
}

function usePolled<T>(load: () => Promise<T>, key: string): [T | null, string] {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const read = () => load().then((answer) => { if (live) { setValue(answer); setError(""); } }).catch((err: Error) => live && setError(err.message));
    void read();
    const timer = window.setInterval(read, POLL_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [key]);
  return [value, error];
}

export function ExecutionGroupsPage({ me }: { me: Me }) {
  const [answer, error] = usePolled(() => api.executionGroups(), "groups");
  // An execution sits in its schedule's folder (round 9, D14); folders are made on Schedules.
  const [folders, reloadFolders] = useFolders("schedule");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  const all = answer ? [...answer.groups, ...(answer.manual.subjects ? [answer.manual] : [])] : [];
  const rows = all.filter((row) => inFolder(folders, row.id, folder));
  useAssistantPage({ place: t("Analytics › Results"), page: "linkcraft:executions", platformUrl: me.processcraft_url,
    view: { rows: rows.slice(0, 30).map((row) => `${row.id}: ${row.name.slice(0, 80)} (${row.algorithm?.name ?? ""}; ${row.subjects} subjects; alarm ${row.counts.alarm}, warning ${row.counts.warning}; last ${row.last_run_at ?? "never"})`) } });
  const columns: DataColumn<ExecutionGroup>[] = [
    { key: "name", label: t("Monitor"), sort: (row) => row.name.toLowerCase(), render: (row) => <><Link to={row.path}><b>{row.name}</b></Link><small>{cadenceText(row)}{row.enabled ? "" : ` · ${t("Paused")}`}</small></> },
    { key: "algorithm", label: t("Algorithm"), sort: (row) => row.algorithm?.name ?? "", render: (row) => row.algorithm ? <>{row.algorithm.name}{row.algorithm.version ? <small>{t("Version {n}", { n: row.algorithm.version })}</small> : null}</> : <small>{t("Several")}</small> },
    { key: "subjects", label: t("Targets"), numeric: true, sort: (row) => row.subjects, render: (row) => <span className="pc-num">{row.subjects}</span> },
    { key: "last", label: t("Last run"), sort: (row) => row.last_run_at ?? "", render: (row) => <>{row.last_run_at ? formatAgo(row.last_run_at) : "—"}<small>{countsText(row.counts)}</small></> },
    { key: "next", label: t("Next"), className: "hide-narrow", sort: (row) => row.next_run_at ?? "", render: (row) => row.next_run_at ? formatDate(row.next_run_at) : "—" },
  ];
  return <>
    <Heading eyebrow={t("What Analytics ran and concluded")} title={t("Results")}
      detail={t("Each monitor with what it runs and how its last run ended. Open one to see its assets, and an asset to see its result over time.")} />
    {EXECUTIONS_TABS("schedules")}
    {error && <ErrorBox text={error} />}
    <div className="pc-folder-layout">
    <FolderColumn kind="schedule" list={folders} chosen={folder} onChoose={(value) => { setFolder(value); rememberFolder("/executions", value); }} total={all.length} canEdit={false} onChanged={reloadFolders} />
    <section className="panel methods-main" aria-label={t("Monitors")}>
      {!answer ? (error ? null : <Loading />) : <DataTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.id}
        onRowClick={(row) => navigate(row.path)}
        searchText={(row) => `${row.name} ${row.algorithm?.name ?? ""}`}
        searchPlaceholder={t("Search monitor or algorithm")}
        label={t("Monitors")}
        empty={folder ? t("No monitor in this folder.") : t("No monitor yet: a monitor runs an algorithm on assets.")}
      />}
    </section>
    </div>
  </>;
}

export function GroupSummary({ group }: { group: ExecutionGroup }) {
  return <section className="panel group-summary" aria-label={t("Summary")}>
    <dl className="facts">
      <div><dt>{t("Runs")}</dt><dd>{group.algorithm ? <>{group.algorithm.id ? <Link to={`/algorithms/${encodeURIComponent(group.algorithm.id)}`}>{group.algorithm.name}</Link> : group.algorithm.name}{group.algorithm.version ? ` · v${group.algorithm.version}` : ""}</> : t("Several algorithms")}</dd></div>
      <div><dt>{t("When")}</dt><dd>{cadenceText(group) || "—"}{group.enabled ? "" : ` · ${t("Paused")}`}</dd></div>
      <div><dt>{t("Last run")}</dt><dd>{group.last_run_at ? `${formatDate(group.last_run_at)} (${formatAgo(group.last_run_at)})` : "—"}</dd></div>
      <div><dt>{t("Next")}</dt><dd>{group.next_run_at ? formatDate(group.next_run_at) : "—"}</dd></div>
      <div><dt>{t("How it ended")}</dt><dd>{countsText(group.counts)}</dd></div>
    </dl>
  </section>;
}

export function ExecutionGroupPage({ groupId, me }: { groupId: string; me: Me }) {
  const [answer, error] = usePolled(() => api.executionGroup(groupId), groupId);
  useAssistantPage({ title: answer?.group.name, place: t("Analytics › Results › {name}", { name: answer?.group.name ?? groupId }), page: "linkcraft:execution-group", platformUrl: me.processcraft_url,
    facts: answer ? { schedule: groupId, algorithm: answer.group.algorithm?.name ?? "", version: answer.group.algorithm?.version ?? "", last_run: answer.group.last_run_at ?? "", ...answer.group.counts } : {},
    view: { rows: (answer?.subjects ?? []).slice(0, 30).map((row) => `${row.id}: ${row.status_label}${row.finding ? ` (${row.finding.slice(0, 80)})` : ""}`) } });
  const columns: DataColumn<GroupSubject>[] = [
    { key: "name", label: t("Target"), sort: (row) => row.name.toLowerCase(), render: (row) => <><Link to={row.path}><b>{row.name}</b></Link>{row.name !== row.id && <small className="pc-mono">{row.id}</small>}</> },
    { key: "result", label: t("Latest result"), sort: (row) => row.measure?.value ?? -1, render: (row) => <>{row.measure ? <span className="pc-num">{row.measure.label} {formatMeasure(row.measure)}</span> : "—"} <StatusWord state={row.state} label={row.status_label} /></> },
    { key: "finding", label: t("Why"), className: "hide-narrow", render: (row) => <small className="clamp" title={row.finding}>{row.finding}</small> },
    { key: "at", label: t("When"), sort: (row) => row.at ?? "", render: (row) => (row.at ? formatAgo(row.at) : "—") },
  ];
  if (error && !answer) return <ErrorBox text={error} />;
  if (!answer) return <Loading />;
  const { group } = answer;
  return <>
    <Heading eyebrow={<Link to="/executions">{t("Results")}</Link>} title={group.name}
      actions={group.schedule_path ? <Link to={group.schedule_path} className="button button-secondary">{t("Edit the monitor")}</Link> : undefined} />
    <GroupSummary group={group} />
    <section className="panel" aria-label={t("Targets")}>
      <DataTable
        rows={answer.subjects}
        columns={columns}
        rowKey={(row) => row.id}
        onRowClick={(row) => navigate(row.path)}
        searchText={(row) => `${row.id} ${row.name} ${row.finding}`}
        searchPlaceholder={t("Search asset")}
        label={t("Targets")}
        empty={t("This monitor has no targets.")}
      />
    </section>
  </>;
}

/** Vertical marks where a new version of the algorithm started writing the same series. */
export function versionMarks(series: OwnSeries | undefined): { t: string; label: string }[] {
  if (!series) return [];
  return series.t.map((stamp, index) => ({ t: stamp, label: String(series.v[index] ?? "") })).filter((item) => item.label);
}

function OutputChart({ line, marks, start }: { line: TimeLine; marks: { t: string; label: string }[]; start: string }) {
  const theme = useBrandTheme();
  const figure = useMemo(() => {
    const found = timeFigure({ lines: [line], height: 220, legend: false, start, end: new Date().toISOString() }, theme);
    // One point per execution: dots too, so a few executions show before they make a line.
    return { ...found, data: found.data.map((trace) => ({ ...trace, mode: "lines+markers" as const, marker: { size: 5 } })) };
  }, [line, theme, start]);
  const shapes = marks.map((mark) => ({ type: "line", xref: "x", yref: "paper", x0: mark.t, x1: mark.t, y0: 0, y1: 1, line: { width: 1, dash: "dot", color: "rgba(127,127,127,.7)" } }));
  const notes = marks.map((mark) => ({ x: mark.t, y: 1, xref: "x", yref: "paper", text: mark.label, showarrow: false, yanchor: "bottom", font: { size: 11 } }));
  const layout = { ...figure.layout, shapes: [...(figure.layout.shapes ?? []), ...shapes], annotations: notes } as typeof figure.layout;
  return <Plot data={figure.data} layout={layout} config={figure.config} style={{ width: "100%" }} useResizeHandler />;
}

const outputColumns: DataColumn<SubjectOutput>[] = [
  { key: "name", label: t("Output"), sort: (item) => (item.name ?? "").toLowerCase(), render: (item) => <b>{item.name || item.key}</b> },
  { key: "status", label: t("Status"), sort: (item) => item.status_label ?? "", render: (item) => <StatusWord state={item.state ?? "unknown"} label={item.status_label ?? ""} /> },
  { key: "value", label: t("Value"), numeric: true, sort: (item) => item.value ?? -1, render: (item) => <span className="pc-num">{item.value === null || item.value === undefined ? "—" : formatMeasure({ label: "", value: item.value, format: "number" })}</span> },
  { key: "message", label: t("What it found"), className: "hide-narrow", render: (item) => <small>{item.message}</small> },
];

/** The tabs of a subject in a schedule (owner, round 10, 2026-10-26): its outputs over time,
 * and its runs, each one opening on the diagram (the last one as any other). */
export const SUBJECT_TABS = ["overview", "runs"] as const;
export type SubjectTab = (typeof SUBJECT_TABS)[number];

/** `?tab=&run=` of a subject's page, as it reads them. `last` asks for the last run (the old
 * Last run tab, `?tab=last-run`, opens it too). */
export function subjectQuery(search: string): { tab: SubjectTab; run: string; last: boolean } {
  const query = new URLSearchParams(search);
  const run = query.get("run") ?? "";
  const asked = query.get("tab") ?? "";
  const last = asked === "last-run" || run === "last";
  if (last) return { tab: "runs", run: "", last };
  return { tab: (SUBJECT_TABS as readonly string[]).includes(asked) ? (asked as SubjectTab) : run ? "runs" : "overview", run, last };
}

/** The periods the Over time chart offers: the last hour, day, week or month. */
export const OUTPUT_WINDOWS = ["1h", "24h", "7d", "30d"] as const;

/** The output the Over time chart draws: the one chosen while it still exists, else the first. */
export function chartedOutput(series: Array<{ id: string }>, chosen: string): string {
  return series.some((item) => item.id === chosen) ? chosen : series[0]?.id ?? "";
}

/** The page the subject's own link opens, as its button says it. */
export function subjectPlace(path: string): string {
  if (path.startsWith("/loops/")) return t("Loop page");
  if (path.startsWith("/signals/")) return t("Signal page");
  return t("Asset page");
}

function useSearch(): string {
  const [search, setSearch] = useState(() => window.location.search);
  useEffect(() => {
    const update = () => setSearch(window.location.search);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return search;
}

export function SubjectHistoryPage({ groupId, subject, me }: { groupId: string; subject: string; me: Me }) {
  const { tab, run: askedRun, last } = subjectQuery(useSearch());
  const [answer, error] = usePolled(() => api.subjectHistory(groupId, subject, askedRun || undefined), `${groupId}/${subject}/${askedRun}`);
  useAssistantPage({ title: answer?.subject.name ?? subject, place: t("Analytics › Results › {name}", { name: answer?.subject.name ?? subject }), page: "linkcraft:subject-history", platformUrl: me.processcraft_url,
    facts: answer ? { schedule: groupId, subject, tab, algorithm: answer.algorithm?.name ?? "", version: answer.algorithm?.version ?? "", status: answer.subject.status_label, finding: answer.subject.finding } : { schedule: groupId, subject },
    view: { runs: (answer?.executions ?? []).slice(0, 30).map((item) => `${item.at ?? ""} ${item.status_label}${item.value !== null ? ` ${item.value}` : ""}${item.version ? ` v${item.version}` : ""}`) } });
  // The Over time chart: one output at a time, over the period chosen (round 10).
  const [chosen, setChosen] = useState("");
  const [period, setPeriod] = useState<TimePeriod>({ window: "7d", from: "", to: "" });
  const [series, setSeries] = useState<OwnSeries[] | null>(null);
  const charted = chartedOutput(answer?.series ?? [], chosen);
  // Fixed per period and per poll: from Date.now() on each render, the effect below would refetch forever.
  const start = useMemo(() => periodRange(period).start, [period, answer]);
  useEffect(() => {
    if (!answer || !charted || tab !== "overview") return;
    setSeries(null);
    api.ownSeries([charted, ...(answer.versions ? [answer.versions] : [])], start).then((found) => setSeries(found.series)).catch(() => setSeries([]));
  }, [charted, answer?.versions, start, tab, Boolean(answer)]);
  if (error && !answer) return <ErrorBox text={error} />;
  if (!answer) return <Loading />;
  const { group, subject: row } = answer;
  const base = `/executions/${encodeURIComponent(groupId)}/${encodeURIComponent(subject)}`;
  const algorithmId = answer.algorithm?.id ?? "";
  const byId = new Map((series ?? []).map((item) => [item.signal, item]));
  const marks = versionMarks(answer.versions ? byId.get(answer.versions) : undefined);
  const output = answer.series.find((item) => item.id === charted);
  const lastId = answer.last_run?.id ?? "";
  const runPath = (id: string) => `${base}?tab=runs&run=${encodeURIComponent(id)}`;
  // The run shown: the one asked for, the last one asked as such, or none (the list).
  const shown = last ? answer.last_run : askedRun ? (askedRun === lastId ? answer.last_run : answer.run) : null;
  const columns: DataColumn<GroupPast>[] = [
    { key: "at", label: t("When"), sort: (item) => item.at ?? "", render: (item) => <>{formatDate(item.at)}<small>{item.at ? formatAgo(item.at) : ""}</small></> },
    { key: "result", label: t("Result"), render: (item) => <>{item.value === null || item.value === undefined ? "—" : <span className="pc-num">{formatMeasure({ label: "", value: item.value, format: row.measure?.format ?? "score" })}</span>} <StatusWord state={item.state} label={item.status_label} /></> },
    { key: "version", label: t("Version"), className: "hide-narrow", render: (item) => (item.version ? `v${item.version}` : "—") },
    { key: "took", label: t("Took"), numeric: true, className: "hide-narrow", render: (item) => <span className="pc-num">{item.duration_seconds === null || item.duration_seconds === undefined ? "—" : formatDuration(item.duration_seconds)}</span> },
    { key: "open", label: "", render: (item) => (item.id ? <Link to={runPath(item.id)} className="run-open">{t("Open")}</Link> : <small className="muted">{t("Result only")}</small>) },
  ];
  return <>
    <Heading eyebrow={<><Link to="/executions">{t("Results")}</Link> / <Link to={group.path}>{group.name}</Link></>} title={row.name}
      detail={answer.algorithm ? t("{algorithm}, version {version}", { algorithm: answer.algorithm.name, version: answer.algorithm.version ?? "—" }) : undefined}
      actions={<>
        <Link to={answer.subject_path} className="subject-place">{subjectPlace(answer.subject_path)}</Link>
        {answer.last_run && !(shown && shown === answer.last_run) && <Link to={lastId ? runPath(lastId) : `${base}?tab=runs&run=last`} className="button button-primary">{t("Open the last run")}</Link>}
      </>} />
    <PageTabs label={t("Run")} href={href} navigate={navigate} tabs={[
      { to: base, label: t("Overview"), active: tab === "overview" },
      { to: `${base}?tab=runs`, label: t("Runs"), active: tab === "runs" },
    ]} />
    {tab === "overview" && <>
      <section className="panel subject-latest" aria-label={t("Latest result")}>
        <span className="pc-overline">{t("Latest result")}</span>
        <div className="subject-latest-main"><b className="pc-num">{row.measure ? `${row.measure.label} ${formatMeasure(row.measure)}` : "—"}</b><StatusWord state={row.state} label={row.status_label} /></div>
        <small>{[row.finding, row.at ? formatAgo(row.at) : ""].filter(Boolean).join(" · ")}</small>
      </section>
      {answer.outputs.length > 0 && <section className="panel" aria-label={t("Outputs")}>
        <div className="panel-header"><div><h2>{t("Outputs")}</h2><p>{t("What each output of the latest result said.")}</p></div></div>
        <DataTable
          rows={answer.outputs}
          columns={outputColumns}
          rowKey={(item) => String(item.key ?? item.name ?? "")}
          label={t("Outputs")}
          empty={t("No outputs.")}
        />
      </section>}
      <section className="panel" aria-label={t("Over time")} data-tour="over-time">
        <div className="panel-header">
          <div><h2>{t("Over time")}</h2><p>{t("An output the algorithm records in the Historian, one value per run; a dotted line marks where a new version started.")}</p></div>
          {answer.series.length > 0 && <div className="subject-chart-tools">
            <label>{t("Output")}<select id="subject-output" value={charted} onChange={(event) => setChosen(event.target.value)}>
              {answer.series.map((item) => <option key={item.id} value={item.id}>{item.name}{item.unit ? ` (${item.unit})` : ""}</option>)}
            </select></label>
            <PeriodPicker value={period} onChange={setPeriod} windows={OUTPUT_WINDOWS} fixed={false} />
          </div>}
        </div>
        {!answer.series.length ? <p className="muted">{t("This algorithm records no output in the Historian.")}</p>
          : series === null ? <Loading />
          : output && <div className="subject-chart">
            {(() => {
              const found = byId.get(output.id);
              return found && found.t.length ? <OutputChart line={{ name: output.name, t: found.t, v: found.v, unit: output.unit }} marks={marks} start={start} />
                : <p className="muted">{t("No values in this period.")}</p>;
            })()}
          </div>}
      </section>
    </>}
    {tab === "runs" && (askedRun || last) && <>
      <p className="run-back"><Link to={`${base}?tab=runs`}>{t("All runs")}</Link></p>
      {shown
        ? <Suspense fallback={<Loading />}><RunView run={shown} algorithmId={algorithmId} subject={subject} /></Suspense>
        : <section className="panel" role="status"><p>{t("This run's diagram is no longer kept: Analytics keeps it for the last {n} runs of each target (and the runs themselves for {days} days). Its outputs are still in the Historian, on the Overview.", { n: answer.samples_kept, days: RUNS_KEPT_DAYS })}</p></section>}
    </>}
    {tab === "runs" && !askedRun && !last && <section className="panel" aria-label={t("Runs")}>
      <div className="panel-header"><div><h2>{t("Runs")}</h2><p>{t("Each time the monitor ran on {name}, newest first. Open one to see it on the diagram with its outputs and the signals it read; the last {n} keep what each wire carried, so a block's charts draw.", { name: row.name, n: answer.samples_kept })}</p></div></div>
      <DataTable
        rows={answer.executions}
        columns={columns}
        rowKey={(item) => `${item.id ?? ""}${item.at ?? ""}`}
        onRowClick={(item) => item.id && navigate(runPath(item.id))}
        label={t("Runs")}
        empty={t("Nothing ran yet.")}
      />
    </section>}
  </>;
}
