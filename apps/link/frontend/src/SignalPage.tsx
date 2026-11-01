import { ChevronRight, Play, X } from "lucide-react";
import { DataTable, FollowUp, NextSteps, BRAND_COLORS, currentTheme, plotTheme, seriesVar, statusColors, statusVar, type DataColumn, type JourneyStep } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import type { Data, Layout, Shape } from "plotly.js";
import { eventShapes, plotTime } from "./chart";
import { api } from "./api";
import { formatAgo, formatDate, formatNumber, t } from "./i18n";
import { Plot } from "@plantcraft/ui/plot";
import { checkResultLabel, RESULT_ORDER, signalLabel, signalStatus } from "./signalStatus";
import type { CheckResult, CheckSpec, HistoryPoint, Me, QualityEvent, SignalData, SignalDetail, SignalLab } from "./types";
import { SUITE_OF } from "./ResultsPage";
import { checkName, ErrorBox, Heading, Link, Loading, Pill, Quality, ResultHeadline, useCatalog } from "./ui";
import { href, navigate } from "./nav";
import { resultsPath } from "./ResultsPage";

/** Roles whose value is constant by design: the frozen check is off for them unless switched on. */
const CONSTANT_ROLES = ["sp", "mode", "op"];
// Checks a sampled signal (laboratory analyses) skips unless switched on (signals/assess.py).
const LAB_SKIPPED = ["sq_frozen", "sq_noise", "sq_resolution"];

function useCheckColors(catalog: CheckSpec[]) {
  const theme = currentTheme();
  return useMemo(() => {
    const ids = catalog.map((item) => item.id);
    const index = (check: string) => Math.max(0, ids.indexOf(check));
    return {
      hex: (check: string) => BRAND_COLORS[theme].series[index(check) % 8],
      css: (check: string) => seriesVar(index(check)),
    };
  }, [catalog, theme]);
}

function Chart({ detail, data, colors }: { detail: SignalDetail; data: SignalData; colors: ReturnType<typeof useCheckColors> }) {
  const theme = plotTheme();
  const c = BRAND_COLORS[currentTheme()];
  const text = detail.kind === "text";
  const results = detail.verdict?.checks ?? [];
  const traces: Data[] = [{
    type: "scatter", mode: "lines", name: detail.id, x: data.series.t.map(plotTime), y: data.series.v,
    line: { width: 1.3, color: c.text2, ...(text ? { shape: "hv" as const } : {}) }, hovertemplate: `%{y}${detail.unit ? ` ${detail.unit}` : ""}<extra></extra>`,
  }];
  if (data.reference?.t.length) {
    traces.push({ type: "scatter", mode: "lines", name: t("Reference {id}", { id: detail.settings.reference ?? "" }), x: data.reference.t.map(plotTime), y: data.reference.v, line: { width: 1.2, color: c.series[0], dash: "dot" } });
  }
  const shapes: Partial<Shape>[] = eventShapes(results, colors.hex, data.start, data.end);
  const annotations: Layout["annotations"] = [];
  if (!text) {
    for (const [value, label] of [[detail.low, t("Low limit")], [detail.high, t("High limit")]] as const) {
      if (value === null || value === undefined) continue;
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: value, y1: value, line: { color: c.text3, width: 1.2, dash: "dash" } });
      annotations.push({ xref: "paper", x: 1, xanchor: "right", yref: "y", y: value, yanchor: "bottom", text: `${label} ${formatNumber(value, 3)}`, showarrow: false, font: { size: 10, color: c.text3 } });
    }
  }
  const layout: Partial<Layout> = {
    ...theme, height: 340, margin: { l: 52, r: 12, t: 10, b: 36 }, shapes, annotations, hovermode: "x unified",
    showlegend: traces.length > 1, legend: { ...theme.legend, orientation: "h", y: 1.12, x: 0 },
    xaxis: { ...theme.xaxis, type: "date", title: { text: t("Time"), font: { size: 10.5 } } },
    yaxis: { ...theme.yaxis, ...(text ? { type: "category" as const } : {}), title: { text: detail.unit, font: { size: 10.5 } } },
  };
  return <Plot data={traces} layout={layout} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />;
}

function ChartLegend({ results, colors }: { results: CheckResult[]; colors: ReturnType<typeof useCheckColors> }) {
  const flagged = results.filter((item) => (item.status === "warning" || item.status === "bad") && item.events?.length);
  if (!flagged.length) return <p className="muted chart-note">{t("No check marked a stretch of this window.")}</p>;
  return <ul className="event-legend">{flagged.map((item) => <li key={item.check}>
    <i style={{ background: colors.css(item.check) }} /><b>{item.name}</b>
    <span className="muted">{t("{count} marked", { count: item.events?.length ?? 0 })}</span>
  </li>)}</ul>;
}

/** The last 30 days up to the newest point, so one point does not stretch the axis to milliseconds. */
function historyRange(points: HistoryPoint[]): [string, string] {
  const newest = Math.max(...points.map((item) => Date.parse(item.checked_at)).filter(Number.isFinite));
  return [plotTime(new Date(newest - 30 * 86_400_000).toISOString()), plotTime(new Date(newest + 86_400_000).toISOString())];
}

function History({ points }: { points: HistoryPoint[] }) {
  const theme = plotTheme();
  const colors = statusColors();
  if (!points.length) return <p className="muted">{t("No history yet: one value per run.")}</p>;
  return <Plot
    data={[{ type: "scatter", mode: "lines+markers", x: points.map((item) => plotTime(item.checked_at)), y: points.map((item) => item.quality),
      marker: { size: 7, color: points.map((item) => colors[item.status] ?? BRAND_COLORS[currentTheme()].inactive) }, line: { width: 1.4, color: BRAND_COLORS[currentTheme()].text3 },
      text: points.map((item) => signalLabel(item.status)), hovertemplate: "%{text}: %{y}<extra></extra>", name: t("Quality") }]}
    layout={{ ...theme, height: 190, margin: { l: 36, r: 12, t: 8, b: 30 }, showlegend: false, yaxis: { ...theme.yaxis, range: [-4, 104] }, xaxis: { ...theme.xaxis, type: "date", range: historyRange(points) } }}
    config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />;
}

function metricText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? t("Yes") : t("No");
  if (typeof value === "number") return formatNumber(value, Math.abs(value) < 1 ? 4 : 2);
  if (typeof value === "string" && /^\d{4}-\d\d-\d\dT/.test(value)) return formatDate(value);
  return typeof value === "string" ? value : JSON.stringify(value);
}

const label = (key: string) => t(key.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase()));

function duration(event: QualityEvent): string {
  const seconds = (Date.parse(event.end_time) - Date.parse(event.start_time)) / 1000;
  if (!Number.isFinite(seconds) || seconds <= 0) return t("instant");
  if (seconds < 120) return t("{n} s", { n: formatNumber(seconds, 0) });
  if (seconds < 7200) return t("{n} min", { n: formatNumber(seconds / 60, 1) });
  return t("{n} h", { n: formatNumber(seconds / 3600, 1) });
}

const eventSeconds = (event: QualityEvent) => (Date.parse(event.end_time) - Date.parse(event.start_time)) / 1000;
const eventColumns: DataColumn<QualityEvent>[] = [
  { key: "start", label: t("From"), sort: (event) => event.start_time, render: (event) => formatDate(event.start_time) },
  { key: "end", label: t("To"), className: "hide-narrow", sort: (event) => event.end_time, render: (event) => (event.end_time && event.end_time !== event.start_time ? formatDate(event.end_time) : "—") },
  { key: "length", label: t("Length"), numeric: true, sort: (event) => (Number.isFinite(eventSeconds(event)) ? eventSeconds(event) : null), render: duration },
  { key: "what", label: t("What"), sort: (event) => event.label, filter: { value: (event) => event.label }, render: (event) => <>{event.label}{event.details && Object.keys(event.details).length > 0 && <small>{Object.entries(event.details).map(([key, value]) => `${label(key)} ${metricText(value)}`).join(" · ")}</small>}</> },
];

function Checks({ results, colors }: { results: CheckResult[]; colors: ReturnType<typeof useCheckColors> }) {
  const sorted = [...results].sort((a, b) => RESULT_ORDER.indexOf(a.status) - RESULT_ORDER.indexOf(b.status));
  return <div className="panel check-list">{sorted.map((item) => {
    const metrics = Object.entries(item.metrics ?? {}).filter(([key]) => key !== "apt");
    const events = item.events ?? [];
    const failing = item.status === "warning" || item.status === "bad";
    return <details key={item.check} className="check-item" open={failing && events.length > 0 && events.length <= 6}>
      <summary>
        <span className="check-swatch" style={{ background: failing && events.length ? colors.css(item.check) : "transparent" }} />
        <Pill status={item.status} label={checkResultLabel(item.status)} />
        <span className="check-title"><b>{item.name}</b><small>{item.message}</small></span>
        <span className="check-score">{["ok", "warning", "bad"].includes(item.status) ? <Quality value={100 - item.score} status={item.status === "ok" ? "good" : item.status === "warning" ? "suspect" : "bad"} /> : <span className="muted">—</span>}</span>
      </summary>
      <div className="check-body">
        {metrics.length > 0 && <dl className="facts metrics">{metrics.map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd className="pc-num">{metricText(value)}</dd></div>)}</dl>}
        {events.length > 0 && <DataTable rows={events} columns={eventColumns} rowKey={(event) => `${event.start_time}|${event.end_time ?? ""}|${event.label}`} initialSort={{ key: "start", descending: true }} label={t("Events")} className="events" />}
        <p className="check-more"><Link to={`/methods/${encodeURIComponent(item.check)}`} className="text-link">{t("How this check works")}</Link></p>
      </div>
    </details>;
  })}</div>;
}

function Settings({ detail, me, catalog, onChanged }: { detail: SignalDetail; me: Me; catalog: CheckSpec[]; onChanged: () => void }) {
  const own = detail.settings ?? {};
  const pcLimits = detail.processcraft_limits;
  const [form, setForm] = useState({ low: own.low?.toString() ?? "", high: own.high?.toString() ?? "", reference: own.reference ?? "", interval: own.sample_interval_minutes?.toString() ?? "" });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const editable = me.can_edit;
  useEffect(() => { setForm({ low: own.low?.toString() ?? "", high: own.high?.toString() ?? "", reference: own.reference ?? "", interval: own.sample_interval_minutes?.toString() ?? "" }); }, [detail]);

  async function change(payload: Record<string, unknown>, done = t("Saved. It applies from the next check.")) {
    setError(""); setSaved("");
    try { await api.updateSignal(detail.id, payload); setSaved(done); onChanged(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  function save() {
    const payload: Record<string, unknown> = {};
    const clear: string[] = [];
    for (const key of ["low", "high"] as const) {
      const text = form[key].trim();
      if (text === "") { if (own[key] !== undefined && own[key] !== null) clear.push(key); continue; }
      const value = Number(text);
      if (!Number.isFinite(value)) { setError(t("The {field} limit must be a number.", { field: key === "low" ? t("low") : t("high") })); return; }
      payload[key] = value;
    }
    const reference = form.reference.trim();
    if (reference) payload.reference = reference; else if (own.reference) clear.push("reference");
    const interval = form.interval.trim();
    if (interval === "") { if (own.sample_interval_minutes) clear.push("sample_interval_minutes"); } else {
      const minutes = Number(interval);
      if (!Number.isFinite(minutes) || minutes <= 0) { setError(t("The sampling interval must be a number of minutes above zero.")); return; }
      payload.sample_interval_minutes = minutes;
    }
    void change({ ...payload, clear });
  }

  const roles = detail.roles ?? [];
  const offs = new Set(own.checks_off ?? []);
  const ons = new Set(own.checks_on ?? []);
  const isText = detail.kind === "text";
  function runs(item: CheckSpec): { on: boolean; why: string } {
    if (isText && !item.text_signals) return { on: false, why: t("Not for text signals") };
    if (offs.has(item.id)) return { on: false, why: t("Off for this signal") };
    if (ons.has(item.id)) return { on: true, why: t("On for this signal") };
    if (detail.sampled && LAB_SKIPPED.includes(item.id)) return { on: false, why: t("Off: laboratory samples repeat and are spaced by design") };
    if (item.id === "sq_frozen" && roles.some((role) => CONSTANT_ROLES.includes(role))) return { on: false, why: t("Off: a {role} is constant by design", { role: roles.join(", ").toUpperCase() }) };
    return item.enabled ? { on: true, why: t("Default") } : { on: false, why: t("Off for all signals") };
  }
  function toggle(item: CheckSpec, on: boolean) {
    const nextOff = new Set(offs); const nextOn = new Set(ons);
    if (on) { nextOff.delete(item.id); if (!item.enabled || item.id === "sq_frozen" || (detail.sampled && LAB_SKIPPED.includes(item.id))) nextOn.add(item.id); } else { nextOn.delete(item.id); nextOff.add(item.id); }
    void change({ checks_off: [...nextOff], checks_on: [...nextOn] });
  }
  const placeholder = (value: number | null) => value === null || value === undefined ? t("none in PlantCraft") : t("{value} from PlantCraft", { value: formatNumber(value, 6) });

  return <section className="panel">
    <div className="panel-header"><div><h2>{t("Settings")}</h2><p>{editable ? t("Overrides for this signal; empty fields use PlantCraft's values.") : t("Only editors change these settings.")}</p></div></div>
    <div className="form-grid">
      <label className="check"><input type="checkbox" checked={detail.enabled} disabled={!editable} onChange={(event) => void change({ enabled: event.target.checked }, event.target.checked ? t("Switched on: the next run checks it.") : t("Switched off: runs skip it."))} />{t("Checked in every run")}</label>
    </div>
    <div className="form-grid settings-fields">
      {(["low", "high"] as const).map((key) => {
        const current = own[key];
        return <label key={key}>{key === "low" ? t("Low limit") : t("High limit")}{detail.unit && <small>{detail.unit}</small>}
          <span className="input-row"><input inputMode="decimal" value={form[key]} disabled={!editable} placeholder={placeholder(pcLimits[key])} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
            {editable && current !== null && current !== undefined && <button type="button" className="icon-button" title={t("Clear: use PlantCraft's limit")} aria-label={t("Clear {field}", { field: key })} onClick={() => void change({ clear: [key] })}><X size={15} /></button>}</span>
        </label>;
      })}
      <label>{t("Sampling")}<small>{detail.sampled ? t("Laboratory or manual samples: freshness and gaps are measured against the sampling interval; no frozen, noise or resolution checks.") : t("A continuous process signal, judged by every check.")}</small>
        <select value={own.sampling ?? ""} disabled={!editable} onChange={(event) => void change(event.target.value ? { sampling: event.target.value } : { clear: ["sampling"] })}>
          <option value="">{detail.source_kind === "csv" ? t("Automatic: laboratory (file source)") : t("Automatic: continuous")}</option>
          <option value="lab">{t("Laboratory or manual samples")}</option>
          <option value="continuous">{t("Continuous process signal")}</option>
        </select>
      </label>
      {detail.sampled && <label>{t("Sampling interval")}<small>{t("Minutes between samples; empty, read from the samples themselves.")}</small>
        <input inputMode="decimal" value={form.interval} disabled={!editable} placeholder={t("from the samples")} onChange={(event) => setForm({ ...form, interval: event.target.value })} />
      </label>}
      <label>{t("Reference signal")}<small>{t("A redundant measurement of the same quantity, or its lab analysis (laboratory:<analysis>): the drift check compares with it, and the page shows the signal against it.")}</small>
        <span className="input-row"><input className="pc-mono" value={form.reference} disabled={!editable} placeholder={t("Signal id")} onChange={(event) => setForm({ ...form, reference: event.target.value })} />
          {editable && own.reference && <button type="button" className="icon-button" title={t("Clear")} aria-label={t("Clear {field}", { field: "reference" })} onClick={() => void change({ clear: ["reference"] })}><X size={15} /></button>}</span>
      </label>
    </div>
    {editable && <div className="row-actions"><button className="button button-primary" onClick={save}>{t("Save")}</button></div>}
    <h3>{t("Checks for this signal")}</h3>
    <ul className="toggles">{catalog.map((item) => {
      const state = runs(item);
      return <li key={item.id}><label className="check">
        <input type="checkbox" checked={state.on} disabled={!editable || (isText && !item.text_signals)} onChange={(event) => toggle(item, event.target.checked)} />
        <span><b>{item.name}</b><small>{state.why}</small></span>
      </label></li>;
    })}</ul>
    {saved && <div className="notice notice-ok">{saved}</div>}
    {error && <div className="notice notice-error" role="alert">{error}</div>}
  </section>;
}

/** How a virtual sensor's health 0 to 100 reads (sensor_health in the SDK). */
const healthStatus = (value: number) => (value >= 75 ? "good" : value >= 50 ? "suspect" : "bad");

/** The signal against the lab results of its reference: health, bias over time, actual × predicted. */
function AgainstLab({ detail }: { detail: SignalDetail }) {
  const [lab, setLab] = useState<SignalLab | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setLab(null); setError("");
    api.signalLab(detail.id).then(setLab).catch((err: Error) => setError(err.message));
  }, [detail.id, detail.settings?.reference]);
  const theme = plotTheme();
  const c = BRAND_COLORS[currentTheme()];
  const unit = detail.unit ? ` ${detail.unit}` : "";
  const body = () => {
    if (error) return <ErrorBox text={error} />;
    if (!lab) return <Loading text={t("Loading the lab results…")} />;
    if (!lab.samples.length) return <p className="muted">{t("No result of {id} in the last 7 days.", { id: lab.reference })}</p>;
    const counted = lab.samples.filter((item) => item.status !== "rejected");
    const values = counted.flatMap((item) => [item.lab, item.online, item.corrected]).filter((v): v is number => v !== null);
    const low = Math.min(...values); const high = Math.max(...values);
    const scatter: Data[] = [
      { type: "scatter", mode: "lines", x: [low, high], y: [low, high], name: t("Agreement"), hoverinfo: "skip", line: { color: c.text3, width: 1, dash: "dash" } },
      { type: "scatter", mode: "markers", name: detail.id, x: counted.map((item) => item.lab), y: counted.map((item) => item.online), marker: { color: c.text2, size: 6 }, hovertemplate: `${t("Lab")} %{x}${unit}<br>${t("Signal")} %{y}${unit}<extra></extra>` },
      { type: "scatter", mode: "markers", name: t("Corrected"), x: counted.map((item) => item.lab), y: counted.map((item) => item.corrected), marker: { color: c.series[0], size: 6 }, hovertemplate: `${t("Lab")} %{x}${unit}<br>${t("Corrected")} %{y}${unit}<extra></extra>` },
    ];
    const bias: Data[] = [{ type: "scatter", mode: "lines", name: t("Bias"), x: lab.bias_series.t.map(plotTime), y: lab.bias_series.v, line: { color: c.series[0], width: 1.4, shape: "hv" }, hovertemplate: `%{y}${unit}<extra></extra>` }];
    const small: Partial<Layout> = { ...theme, height: 280, margin: { l: 52, r: 12, t: 10, b: 40 }, showlegend: false };
    const pending = lab.samples.filter((item) => item.status === "entered").length;
    const rejected = lab.samples.length - counted.length;
    return <>
      <div className="pc-grid">
        <div className="panel kpi-card"><span className="pc-overline">{t("Health against the lab")}</span>{lab.health === null ? <b>—</b> : <Quality value={lab.health} status={healthStatus(lab.health)} />}<small>{t("0 to 100 from the error at the {count} sampling times; 100 within a quarter of the lab's spread.", { count: counted.length })}</small></div>
        <div className="panel kpi-card"><span className="pc-overline">{t("Corrected by the lab")}</span>{lab.health_corrected === null ? <b>—</b> : <Quality value={lab.health_corrected} status={healthStatus(lab.health_corrected)} />}<small>{t("The signal minus its bias, as known at each sampling time.")}</small></div>
        <div className="panel kpi-card"><span className="pc-overline">{t("Bias now")}</span><b className="pc-num">{lab.bias === null ? "—" : `${formatNumber(lab.bias, 4)}${unit}`}</b><small>{t("{used} results corrected it{pending}{rejected}.", { used: lab.used, pending: pending ? t(", {n} waiting for approval", { n: pending }) : "", rejected: rejected ? t(", {n} rejected", { n: rejected }) : "" })}</small></div>
      </div>
      <div className="pc-grid pc-grid-2">
        <div><h3>{t("Actual × predicted")}</h3><Plot data={scatter} layout={{ ...small, xaxis: { ...theme.xaxis, title: { text: `${t("Lab")}${unit}`, font: { size: 10.5 } } }, yaxis: { ...theme.yaxis, title: { text: `${t("Signal")}${unit}`, font: { size: 10.5 } } } }} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} /></div>
        <div><h3>{t("Bias over time")}</h3><Plot data={bias} layout={{ ...small, xaxis: { ...theme.xaxis, type: "date" }, yaxis: { ...theme.yaxis, title: { text: detail.unit, font: { size: 10.5 } } } }} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} /></div>
      </div>
      {!lab.timed && <p className="muted chart-note">{t("{id} has no laboratory times: each of its values counts from the moment it was taken.", { id: lab.reference })}</p>}
    </>;
  };
  return <section className="panel">
    <div className="panel-header"><div><h2>{t("Against the lab")}</h2><p>{t("This signal against {id} over the last 7 days. Each result counts at its sampling time, from its approval; a rejected one is left out.", { id: detail.settings?.reference ?? "" })}</p></div></div>
    {body()}
  </section>;
}

export function SignalPage({ signalId, me }: { signalId: string; me: Me }) {
  const [detail, setDetail] = useState<SignalDetail | null>(null);
  const [data, setData] = useState<SignalData | null>(null);
  const [dataError, setDataError] = useState("");
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const catalog = useCatalog();
  const colors = useCheckColors(catalog);

  const loadDetail = () => api.signal(signalId).then((value) => { setDetail(value); setError(""); }).catch((err: Error) => setError(err.message));
  const loadData = () => {
    api.signalData(signalId).then((value) => { setData(value); setDataError(""); }).catch((err: Error) => setDataError(err.message));
    api.signalHistory(signalId).then(setHistory).catch(() => setHistory([]));
  };
  useEffect(() => { void loadDetail(); loadData(); }, [signalId]);

  async function checkNow() {
    setBusy(true); setMessage(""); setError("");
    try {
      const verdict = await api.checkSignal(signalId);
      setMessage(t("Checked now: {status}, quality {quality}.", { status: signalLabel(verdict.status), quality: formatNumber(verdict.quality, 0) }));
      await loadDetail(); loadData();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }

  if (error && !detail) return <ErrorBox text={error} />;
  if (!detail) return <Loading text={t("Loading the signal…")} />;
  const verdict = detail.verdict;
  const status = signalStatus(detail.status);
  const overridden = (key: "low" | "high") => detail.settings?.[key] !== undefined && detail.settings?.[key] !== null;
  const limits = detail.low === null && detail.high === null ? t("None") : `${formatNumber(detail.low, 6)} … ${formatNumber(detail.high, 6)}${detail.unit ? ` ${detail.unit}` : ""}`;
  return <>
    <nav className="breadcrumb"><Link to={resultsPath({ kind: ["signal"] })}>{t("Results")}</Link><ChevronRight size={12} /><span>{t("Signal")}</span><ChevronRight size={12} /><span className="pc-mono">{detail.id}</span></nav>
    <Heading
      eyebrow={[detail.source, ...detail.assets].filter(Boolean).join(" · ") || t("Signal")}
      title={detail.name && detail.name !== detail.id ? `${detail.id} · ${detail.name}` : detail.id}
      detail={verdict?.window_start ? t("Checked {ago} on data from {start} to {end}.", { ago: formatAgo(verdict.checked_at), start: formatDate(verdict.window_start), end: formatDate(verdict.window_end) }) : t("Not checked yet: a result appears after the next run of the Signal quality algorithm.")}
      actions={me.can_edit && <button className="button button-primary" disabled={busy} onClick={() => void checkNow()}><Play size={16} className={busy ? "spin" : ""} />{busy ? t("Checking…") : t("Check now")}</button>}
    />
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    {detail.missing && <div className="notice">{t("PlantCraft no longer lists this signal; its last result stays here.")}</div>}
    <div className="pc-grid">
      <ResultHeadline measure={{ label: t("Quality"), value: detail.quality ?? null, format: "score" }} status={SUITE_OF[detail.status ?? "unchecked"] ?? "unknown"} native={{ label: signalLabel(detail.status), status }} algorithm={{ id: "signal_quality", name: t("Signal quality") }} at={verdict?.checked_at} />
      <div className="panel kpi-card"><span className="pc-overline">{t("Limiting check")}</span>{detail.limiting ? <><b>{checkName(catalog, detail.limiting)}</b><small>{detail.message}</small></> : <><b>{verdict ? t("None") : "—"}</b><small>{detail.message}</small></>}<small>{t("Usable for analysis: {answer}", { answer: detail.apt === null || detail.apt === undefined ? "—" : detail.apt ? t("Yes") : t("No") })}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Limits")}</span><b className="pc-num">{limits}</b><small>{overridden("low") || overridden("high") ? t("Set in Analytics (PlantCraft: {low} … {high})", { low: formatNumber(detail.processcraft_limits.low, 6), high: formatNumber(detail.processcraft_limits.high, 6) }) : t("From PlantCraft")}{detail.roles.length ? ` · ${t("Role {roles}", { roles: detail.roles.join(", ").toUpperCase() })}` : ""}</small></div>
    </div>
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Input signals")}</h2><p>{data ? t("{count} samples{resampled}. Shaded: stretches a check marked.", { count: formatNumber(data.series.t.length, 0), resampled: data.resampled ? t(", resampled") : "" }) : t("The data the last check read, from PlantCraft.")}</p></div></div>
      {dataError ? <ErrorBox text={dataError} /> : !data ? <Loading text={t("Loading data…")} /> : data.series.t.length === 0 ? <p className="muted">{t("No samples in this window.")}</p> : <>
        <Chart detail={detail} data={data} colors={colors} />
        <ChartLegend results={verdict?.checks ?? []} colors={colors} />
      </>}
    </section>
    {detail.settings?.reference && detail.kind !== "text" && <AgainstLab detail={detail} />}
    <div className="section-head"><h2 className="section-title">{t("Algorithm and outputs")}</h2><Link to="/algorithms/signal_quality" className="text-link">{t("Open the algorithm")}</Link></div>
    <p className="muted section-lead">{t("The checks of the Signal quality algorithm on this window, each with what it found. The worst decides the result.")}</p>
    {verdict?.checks.length ? <Checks results={verdict.checks} colors={colors} /> : <p className="muted">{t("No results yet.")}</p>}
    <div className="pc-grid pc-grid-2">
      <section className="panel"><div className="panel-header"><div><h2>{t("Derived signals")}</h2><p>{t("The signal's quality over 30 days, one value per check, coloured by its result.")}</p></div></div><History points={history} /></section>
      <Settings detail={detail} me={me} catalog={catalog} onChanged={() => void loadDetail()} />
    </div>
    {detail.description && detail.description !== detail.name && <p className="muted">{detail.description}</p>}
    <FollowUp subject={`signal:${detail.id}`} newTitle={detail.limiting ? `${detail.id}: ${checkName(catalog, detail.limiting)}` : detail.id} platformUrl={me.processcraft_url} canCreate={me.can_edit}
      detail={t("What was decided about this signal, in PlantCraft: a transmitter to check, a tag to fix.")} />
    <NextSteps items={signalNextSteps(detail)} href={href} navigate={navigate} />
  </>;
}

/** Where to go from a signal: the assets (loops) that read it, then the list. */
export function signalNextSteps(detail: SignalDetail): JourneyStep[] {
  return [
    ...detail.assets.slice(0, 3).map((asset): JourneyStep => ({ title: t("Asset {id}", { id: asset }), detail: t("Uses this signal: its loop in Analytics, when it is one."), to: `/assets/${encodeURIComponent(asset)}`, cta: t("Open the loop") })),
    { title: t("Back to the results"), detail: t("The other signals, worst first."), to: resultsPath({ kind: ["signal"] }), cta: t("Open the results") },
  ];
}
