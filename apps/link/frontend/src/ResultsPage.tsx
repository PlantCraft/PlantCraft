/**
 * Results (owner, 2026-10-23): the latest result of every algorithm on every asset it runs on, on
 * one list, whatever the algorithm: the asset and its type, the algorithm and its version, the
 * status in the suite's words, the headline measure, the finding, when, and the algorithm's tags.
 * The filters are the algorithm, the tag, the asset type, the responsible group and the status;
 * **Report** prints what the filter keeps. Nothing here is specific to loops or signals: a loop is
 * registered as an asset in PlantCraft. Its second tab is the run history of every algorithm.
 */
import { DataTable, MultiSelect, PageTabs, type DataColumn, useAssistantPage } from "@plantcraft/ui";
import { FileDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { methodLabel } from "./labels";
import { href, navigate } from "./nav";
import { suiteLabel } from "./status";
import { RESULT_FILTERS, type Me, type ResultFilter, type ResultList, type ResultQuery, type ResultRow, type RunRow } from "./types";
import { ErrorBox, formatMeasure, Heading, Link, Loading, Pill } from "./ui";

/** Every result is read at once; the table pages them (25/50/100 a page). */
const LIMIT = 5000;
const STATUSES = ["alarm", "warning", "unknown", "ok"];
const FILTER_LABELS: Record<ResultFilter, string> = { algorithm: "Algorithm", tag: "Label", asset_type: "Asset type", group: "Group" };

type Filters = Record<ResultFilter | "status", string[]>;
const NO_FILTERS: Filters = { status: [], algorithm: [], tag: [], asset_type: [], group: [] };

/** The filters in the address. ``kind`` (signal, loop) of older links is an asset type. */
export function readFilters(search: string): Filters & { q: string } {
  const params = new URLSearchParams(search);
  const list = (key: string) => (params.get(key) ?? "").split(",").filter(Boolean);
  const types = [...new Set([...list("asset_type"), ...list("kind").filter((item) => item !== "asset")])];
  return { status: list("status"), algorithm: list("algorithm"), tag: list("tag"), asset_type: types, group: list("group"), q: params.get("q") ?? "" };
}

/** The address of the Results page with these filters (``kind`` reads as the asset type). */
export function resultsPath(filters: ResultQuery & { kind?: string[] }): string {
  const { kind, ...rest } = filters;
  const types = [...new Set([...(rest.asset_type ?? []), ...(kind ?? [])])];
  const search = new URLSearchParams();
  for (const key of ["status", ...RESULT_FILTERS] as const) {
    const values = key === "asset_type" ? types : rest[key] ?? [];
    if (values.length) search.set(key, values.join(","));
  }
  if (rest.q) search.set("q", rest.q);
  const text = search.toString();
  return `/results${text ? `?${text}` : ""}`;
}

/** A signal verdict or a loop priority in the suite's words (the filters of the Results page). */
export const SUITE_OF: Record<string, string> = { bad: "alarm", suspect: "warning", good: "ok", unknown: "unknown", unchecked: "unknown", critical: "alarm", high: "alarm", medium: "warning", normal: "ok" };

/** The Results page for an old address: /signals?status=bad -> /results?asset_type=signal&status=alarm. */
export function legacyResultsPath(kind: "signal" | "loop", search: string): string {
  const params = new URLSearchParams(search);
  const status = [...new Set((params.get("status") ?? "").split(",").filter(Boolean).map((item) => SUITE_OF[item] ?? "unknown"))];
  return resultsPath({ asset_type: [kind], status, q: params.get("q") ?? "" });
}

/** A limiting finding's name: a method or check id, written as people read it. */
const limitingName = (id: string | null) => (id ? methodLabel(id) : "");

/** Latest results | Run history, under the Results heading. */
function ResultTabs({ runs }: { runs: boolean }) {
  return <PageTabs label={t("Results")} href={href} navigate={navigate} tabs={[
    { to: "/results", label: t("Latest results"), active: !runs },
    { to: "/results/runs", label: t("Run history"), active: runs },
  ]} />;
}

export const RESULT_COLUMNS: DataColumn<ResultRow>[] = [
  { key: "status", label: t("Status"), sort: (row) => STATUSES.indexOf(row.status), render: (row) => <Pill status={row.status} label={suiteLabel(row.status)} /> },
  { key: "name", label: t("Asset"), sort: (row) => row.name, render: (row) => <><Link to={row.path} className="pc-mono strong nowrap" title={row.id}>{row.name}</Link><small>{[row.caption, row.area].filter(Boolean).join(" · ")}</small></> },
  { key: "type", label: t("Type"), className: "hide-narrow", sort: (row) => row.asset_type_label, render: (row) => row.asset_type_label },
  { key: "algorithm", label: t("Algorithm"), sort: (row) => row.algorithm.name, render: (row) => (row.algorithm.name ? <><Link to={`/algorithms/${encodeURIComponent(row.algorithm.id)}`}>{row.algorithm.name}</Link>{row.algorithm.version ? <small>{t("version {number}", { number: row.algorithm.version })}</small> : null}</> : <span className="muted">—</span>) },
  { key: "measure", label: t("Result"), numeric: true, sort: (row) => row.measure.value, render: (row) => <span className="pc-num nowrap">{row.measure.label} <b>{formatMeasure(row.measure)}</b></span> },
  { key: "finding", label: t("Finding"), sort: (row) => limitingName(row.limiting) || row.finding, render: (row) => (row.limiting ? <><b>{limitingName(row.limiting)}</b><small className="clamp">{row.finding}</small></> : <small className="clamp">{row.finding || "—"}</small>) },
  { key: "tags", label: t("Labels"), className: "hide-narrow", sort: (row) => row.tags.join(", "), render: (row) => (row.tags.length ? <span className="alg-tags">{row.tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}</span> : <span className="muted">—</span>) },
  { key: "at", label: t("When"), className: "hide-narrow", sort: (row) => row.at, render: (row) => <span title={formatDate(row.at)}>{row.at ? formatAgo(row.at) : "—"}</span> },
];

export function ResultsPage({ me: _me }: { me: Me }) {
  const initial = useRef(readFilters(window.location.search)).current;
  const [filters, setFilters] = useState<Filters>({ ...NO_FILTERS, ...initial });
  const [query, setQuery] = useState(initial.q);
  const [data, setData] = useState<ResultList | null>(null);
  const [error, setError] = useState("");
  const params: ResultQuery = { ...filters, q: query.trim() };
  const key = JSON.stringify(params);

  const load = () => api.results({ ...params, limit: LIMIT }).then((value) => { setData(value); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 200 : 0);
    window.history.replaceState({}, "", href(resultsPath(params)));
    return () => window.clearTimeout(timer);
  }, [key]);
  useEffect(() => { const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); });

  const set = (name: ResultFilter | "status") => (value: string[]) => setFilters((now) => ({ ...now, [name]: value }));
  const filtered = Object.values(filters).some((value) => value.length > 0) || Boolean(query);
  const columns = useMemo(() => RESULT_COLUMNS, []);
  // What the assistant can do on this page (the button beside the title): Link's works for the results
  // (app.toml) with the rows shown, and one task that reads them too.
  useAssistantPage({
    page: "linkcraft:results",
    view: { query, filters, rows: (data?.items ?? []).slice(0, 25).map((item) => `${item.name} (${item.kind} ${item.id}): ${item.status}, ${item.measure.label} ${item.measure.value ?? "—"}; ${item.finding || item.limiting || ""}`) },
    subject: "app:linkcraft", title: t("Results"), place: t("Analytics › Results"),
    context: data ? `Link's results: ${data.total} subjects shown${filtered ? " (filtered)" : ""}; by status ${Object.entries(data.counts.status).map(([key, count]) => `${key} ${count}`).join(", ")}.` : "",
  });
  return <>
    <Heading
      eyebrow={t("What the algorithms concluded")}
      title={t("Results")}
      detail={t("The latest result of every algorithm on every asset it runs on, worst first. Filter by algorithm, label, asset type, group or status; open one to see its outputs and the signals behind it.")}
      actions={<>
        <a className="button button-secondary" href={api.resultsReportUrl(params)}><FileDown size={16} />{t("Report")}</a>
      </>}
    />
    <ResultTabs runs={false} />
    {error && <ErrorBox text={error} />}
    {!data ? (error ? null : <Loading text={t("Loading results…")} />)
      : data.total === 0 && !filtered
        ? <div className="panel empty"><h2>{t("No results yet")}</h2><p>{t("Results appear after the first run of an algorithm: Signal quality, a loop's algorithm or an algorithm on assets.")}</p></div>
        : <DataTable
          rows={data.items}
          columns={columns}
          rowKey={(row) => `${row.kind}:${row.id}`}
          onRowClick={(row) => navigate(row.path)}
          label={t("Results")}
          className="results-table"
          empty={t("No results match. Change the search or the filters.")}
          toolbar={<div className="toolbar results-filters">
            <label className="search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search asset, algorithm, label or finding")} aria-label={t("Search")} /></label>
            {RESULT_FILTERS.map((name) => (data.options[name].length > 0 || filters[name].length > 0) && <MultiSelect key={name} label={t(FILTER_LABELS[name])} value={filters[name]} onChange={set(name)}
              options={[...data.options[name], ...filters[name].filter((value) => !data.options[name].some((item) => item.id === value)).map((value) => ({ id: value, label: value, count: 0 }))]} />)}
            <MultiSelect label={t("Status")} value={filters.status} onChange={set("status")} options={STATUSES.map((name) => ({ id: name, label: suiteLabel(name), count: data.counts.status[name] ?? null, icon: <i className={`dot dot-${name}`} aria-hidden="true" /> }))} />
            {filtered && <button type="button" className="button button-secondary button-small" onClick={() => { setFilters(NO_FILTERS); setQuery(""); }}>{t("Clear filters")}</button>}
          </div>}
        />}
  </>;
}

const RUN_STATES = ["alarm", "warning", "running", "pending", "ok", "unknown"];
const runStateLabel = (state: string) => (state === "running" ? t("Running") : state === "pending" ? t("Waiting") : suiteLabel(state));

/** Every algorithm's runs, newest first: Signal quality rounds and loop runs on one list. */
export function RunHistoryPage({ me }: { me: Me }) {
  const [rows, setRows] = useState<RunRow[] | null>(null);
  const [algorithms, setAlgorithms] = useState<string[]>([]);
  const [states, setStates] = useState<string[]>([]);
  const [error, setError] = useState("");
  const load = () => api.runs(1000).then((value) => { setRows(value.items); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 15_000); return () => window.clearInterval(timer); }, []);
  const names = useMemo(() => {
    const seen = new Map<string, { name: string; count: number }>();
    for (const row of rows ?? []) {
      const key = row.algorithm.id || row.algorithm.name;
      seen.set(key, { name: row.algorithm.name || key, count: (seen.get(key)?.count ?? 0) + 1 });
    }
    return [...seen.entries()].map(([id, item]) => ({ id, label: item.name, count: item.count }));
  }, [rows]);
  const shown = (rows ?? []).filter((row) => (!algorithms.length || algorithms.includes(row.algorithm.id || row.algorithm.name)) && (!states.length || states.includes(row.state)));
  const columns: DataColumn<RunRow>[] = [
    { key: "started_at", label: t("Started"), sort: (row) => row.started_at, render: (row) => <><Link to={row.path}>{formatDate(row.started_at)}</Link><small>{row.started_at ? formatAgo(row.started_at) : ""}</small></> },
    { key: "algorithm", label: t("Algorithm"), sort: (row) => row.algorithm.name, render: (row) => (row.algorithm.id ? <Link to={`/algorithms/${encodeURIComponent(row.algorithm.id)}`}>{row.algorithm.name}</Link> : row.algorithm.name || "—") },
    { key: "subject", label: t("On"), sort: (row) => row.subject, render: (row) => (row.subject_path ? <Link to={row.subject_path} className="pc-mono">{row.subject}</Link> : row.subject) },
    { key: "state", label: t("Status"), sort: (row) => RUN_STATES.indexOf(row.state), render: (row) => <Pill status={row.state} label={row.status_label} /> },
    { key: "finding", label: t("Found"), sort: (row) => row.finding, render: (row) => <small className="clamp">{row.finding || "—"}</small> },
    { key: "duration", label: t("Duration"), numeric: true, className: "hide-narrow", sort: (row) => row.duration_seconds, render: (row) => <span className="pc-num">{formatDuration(row.duration_seconds)}</span> },
    { key: "trigger", label: t("Trigger"), className: "hide-narrow", sort: (row) => row.trigger, render: (row) => <>{row.trigger}{row.by && <small>{row.by}</small>}</> },
  ];
  return <>
    <Heading eyebrow={t("Signals, loops and algorithm outputs")} title={t("Results")}
      detail={t("Every run of every algorithm, newest first. Monitors live on each algorithm's page.")} />
    <ResultTabs runs />
    {error && <ErrorBox text={error} />}
    {!rows ? (error ? null : <Loading />)
      : <DataTable
        rows={shown}
        columns={columns}
        rowKey={(row) => row.id}
        onRowClick={(row) => navigate(row.path)}
        searchText={(row) => `${row.algorithm.name} ${row.subject} ${row.finding} ${row.by}`}
        searchPlaceholder={t("Search algorithm, target or finding")}
        label={t("Run history")}
        empty={t("No algorithm has run yet.")}
        toolbar={<>
          <MultiSelect label={t("Algorithm")} value={algorithms} onChange={setAlgorithms} options={names} />
          <MultiSelect label={t("Status")} value={states} onChange={setStates} options={RUN_STATES.filter((key) => (rows ?? []).some((row) => row.state === key)).map((key) => ({ id: key, label: runStateLabel(key), icon: <i className={`dot dot-${key}`} aria-hidden="true" /> }))} />
        </>}
      />}
  </>;
}
