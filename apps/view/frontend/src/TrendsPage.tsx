/**
 * Trends: pick signals, draw them on one plot or on stacked subplots that share the time axis,
 * over the last hours or a fixed period, as means of an interval or as recorded; save the trend
 * to open it again, or download what it shows as CSV.
 */
import { Dialog, confirmAction, BRAND_COLORS, type BrandTheme, useAssistantPage, timeChartLayout, timePlotConfig, fileStamp, isoOf, localOf, plotTheme, errorMessage as message, saveFile, useBrandTheme } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { Download, ExternalLink, LoaderCircle, Maximize2, Minimize2, Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { SignalSearch } from "./CardEditor";
import { formatDate, t } from "./i18n";
import { when, windowLabel } from "./model";
import { navigate } from "./nav";
import { DEFAULT_STYLE, EMPTY_VIEW, MAX_LINES, MAX_PLOTS, chipText, periodLabel, readable, styleOf, TREND_AGGS, TREND_STEPS, TREND_WINDOWS, trendCsv, trendTraces, viewFromAddress } from "./trendModel";
import type { LineStyle, Me, Trend, TrendAgg, TrendData, TrendLineSpec, TrendPeriod, TrendView } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

/** The chart's own theme: "auto" follows the platform; light or dark fixes
 * it, the PNG included, to send a chart whatever theme the page is in. Kept per browser. */
export type ChartTheme = "auto" | BrandTheme;
const CHART_THEME_KEY = "dashcraft.chart-theme";
const CHART_THEMES: Array<{ id: ChartTheme; label: string }> = [{ id: "auto", label: "As the platform" }, { id: "light", label: "Light" }, { id: "dark", label: "Dark" }];
function storedChartTheme(): ChartTheme {
  try {
    const value = localStorage.getItem(CHART_THEME_KEY);
    return value === "light" || value === "dark" ? value : "auto";
  } catch { return "auto"; }
}

/** The chart's theme, kept per browser; Trends and the trend over a process display share it. */
function useChartTheme(): [ChartTheme, (value: ChartTheme) => void] {
  const [chartTheme, setChartTheme] = useState<ChartTheme>(storedChartTheme);
  return [chartTheme, (value) => {
    setChartTheme(value);
    try { localStorage.setItem(CHART_THEME_KEY, value); } catch { /* this visit only */ }
  }];
}

function TrendChart({ data, height, theme: chosen, filename }: { data: TrendData; height?: number; theme: ChartTheme; filename: string }) {
  const platform = useBrandTheme();
  const shown = chosen === "auto" ? platform : chosen;
  const theme = plotTheme(shown);
  const surface = BRAND_COLORS[shown].surface;
  const plots = data.plots;
  const { traces, axes, anchor } = trendTraces(data, theme.yaxis);
  if (!traces.length) return <p className="muted tc-empty">{t("No samples in this period.")}</p>;
  const right = plots.some((plot) => plot.lines.some((line) => styleOf(line.style).axis === "right"));
  // The suite's time chart (@plantcraft/ui): the Historian's point page draws the same.
  const base = timeChartLayout(theme, { height: height ?? Math.max(320, 240 * plots.length), start: data.range.start, end: data.range.end, rightAxis: right });
  // A solid background, so the picture (PNG) reads in the theme it was drawn in.
  const layout = { ...base, paper_bgcolor: surface, plot_bgcolor: surface, xaxis: { ...base.xaxis, anchor }, ...axes };
  const config = { ...timePlotConfig(), toImageButtonOptions: { format: "png" as const, filename, scale: 2 } };
  return <div className="tc-trend-plot" style={{ background: surface }}><Plot data={traces} layout={layout} config={config} useResizeHandler style={{ width: "100%" }} /></div>;
}

const MODES: Array<{ id: LineStyle["mode"]; label: string }> = [{ id: "lines", label: "Line" }, { id: "markers", label: "Points" }, { id: "lines+markers", label: "Line and points" }];
const SHAPES: Array<{ id: LineStyle["shape"]; label: string }> = [{ id: "linear", label: "Straight between samples" }, { id: "hv", label: "Steps (holds each value)" }, { id: "spline", label: "Smooth" }];
const DASHES: Array<{ id: LineStyle["dash"]; label: string }> = [{ id: "solid", label: "Solid" }, { id: "dash", label: "Dashed" }, { id: "dot", label: "Dotted" }, { id: "dashdot", label: "Dash-dot" }];

/** A small picture of the line: its colour and dash, as the chart draws it. */
export function LineSample({ style }: { style?: Partial<LineStyle> | null }) {
  const value = styleOf(style);
  const dash = { solid: undefined, dash: "6 4", dot: "1.5 3", dashdot: "6 3 1.5 3" }[value.dash];
  return <svg className="tc-sample" width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">
    {value.mode !== "markers" && <line x1="1" y1="5" x2="27" y2="5" stroke={value.color || "currentColor"} strokeWidth={Math.min(value.width, 4)} strokeDasharray={dash} strokeLinecap="round" />}
    {value.mode !== "lines" && <circle cx="14" cy="5" r="3" fill={value.color || "currentColor"} />}
  </svg>;
}

/** One line on its own: label, the interval it reads at and how it summarises it, and how it is drawn. */
function LineEditor({ line, trendStep, onApply, onClose }: { line: TrendLineSpec; trendStep: number | null; onApply: (line: TrendLineSpec) => void; onClose: () => void }) {
  const [value, setValue] = useState<TrendLineSpec>({ ...line, agg: line.agg ?? "mean", step_seconds: line.step_seconds ?? null, style: styleOf(line.style) });
  const style = styleOf(value.style);
  const setStyle = (change: Partial<LineStyle>) => setValue({ ...value, style: { ...style, ...change } });
  const points = style.mode !== "lines";
  const own = value.step_seconds ?? null;
  const recorded = own === 0 || (own === null && trendStep === 0);
  return <Dialog title={<><LineSample style={style} /> {value.label || line.signal_id}</>} onClose={onClose} onSubmit={() => onApply(value)}>
      <div className="form-grid tc-settings">
        <label className="tc-wide">{t("Label")}<input maxLength={120} value={value.label ?? ""} placeholder={line.signal_id} onChange={(event) => setValue({ ...value, label: event.target.value })} /></label>
        <h3 className="tc-wide tc-section">{t("Data")}</h3>
        <label>{t("Interval")}<select value={String(own)} onChange={(event) => setValue({ ...value, step_seconds: event.target.value === "null" ? null : Number(event.target.value) })}>
          <option value="null">{t("The trend's ({interval})", { interval: t(TREND_STEPS.find((item) => item.seconds === trendStep)?.label ?? "Automatic interval") })}</option>
          {TREND_STEPS.filter((item) => item.seconds !== null).map((item) => <option key={String(item.seconds)} value={String(item.seconds)}>{t(item.label)}</option>)}
        </select><small>{t("Each line reads at its own interval: PV every minute beside SP every hour.")}</small></label>
        <label>{t("Each interval shows")}<select value={value.agg} disabled={recorded} onChange={(event) => setValue({ ...value, agg: event.target.value as TrendAgg })}>
          {TREND_AGGS.map((agg) => <option key={agg.id} value={agg.id}>{t(agg.label)}</option>)}
        </select>{recorded && <small>{t("As recorded, every sample is drawn.")}</small>}</label>
        <h3 className="tc-wide tc-section">{t("Look")}</h3>
        <div className="tc-field"><span>{t("Colour")}</span><span className="tc-colour">
          <input type="color" value={style.color || "#4c78a8"} onChange={(event) => setStyle({ color: event.target.value })} aria-label={t("Colour")} />
          <label className="check"><input type="checkbox" checked={!style.color} onChange={(event) => setStyle({ color: event.target.checked ? "" : "#4c78a8" })} /> {t("Automatic")}</label>
        </span></div>
        <label>{t("Dash")}<select value={style.dash} disabled={style.mode === "markers"} onChange={(event) => setStyle({ dash: event.target.value as LineStyle["dash"] })}>{DASHES.map((dash) => <option key={dash.id} value={dash.id}>{t(dash.label)}</option>)}</select></label>
        <label>{t("Draw as")}<select value={style.mode} onChange={(event) => setStyle({ mode: event.target.value as LineStyle["mode"] })}>{MODES.map((mode) => <option key={mode.id} value={mode.id}>{t(mode.label)}</option>)}</select></label>
        <label>{t("Between samples")}<select value={style.shape} disabled={style.mode === "markers"} onChange={(event) => setStyle({ shape: event.target.value as LineStyle["shape"] })}>{SHAPES.map((shape) => <option key={shape.id} value={shape.id}>{t(shape.label)}</option>)}</select></label>
        <label>{t("Line width")}<input type="number" min={0.5} max={8} step={0.5} value={style.width} disabled={style.mode === "markers"} onChange={(event) => setStyle({ width: Number(event.target.value) || DEFAULT_STYLE.width })} /></label>
        <label>{t("Point size")}<input type="number" min={2} max={16} step={1} value={style.marker_size} disabled={!points} onChange={(event) => setStyle({ marker_size: Number(event.target.value) || DEFAULT_STYLE.marker_size })} /></label>
        <label>{t("Y axis")}<select value={style.axis} onChange={(event) => setStyle({ axis: event.target.value as LineStyle["axis"] })}><option value="left">{t("Left")}</option><option value="right">{t("Right (its own scale)")}</option></select></label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={() => setValue({ ...value, agg: "mean", step_seconds: null, style: { ...DEFAULT_STYLE } })}>{t("Reset")}</button><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit">{t("Apply")}</button></footer>
  </Dialog>;
}

function saveCsv(name: string, text: string) {
  saveFile(name, new Blob(["﻿", text], { type: "text/csv;charset=utf-8" }));
}

export function TrendsPage({ me, trendId }: { me: Me; trendId?: string }) {
  const [saved, setSaved] = useState<Trend[] | null>(null);
  const [current, setCurrent] = useState<Trend | null>(null);
  const [name, setName] = useState("");
  const [view, setView] = useState<TrendView>(EMPTY_VIEW);
  const [data, setData] = useState<TrendData | null>(null);
  const [loading, setLoading] = useState(false);
  // Full screen: the chart panel alone, Esc leaves.
  const chartRef = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);
  // View's work here (app.toml): explain the trend on screen.
  useAssistantPage({ place: t("View › Trends"), page: "dashcraft:trends", facts: { trend: current?.name ?? "" },
    view: { plots: view.plots.slice(0, 8).map((plot) => JSON.stringify(plot).slice(0, 280)), range: data ? `${data.range.start} to ${data.range.end}` : "" } });
  useEffect(() => {
    const changed = () => setFull(document.fullscreenElement === chartRef.current && chartRef.current !== null);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  async function toggleFull() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await chartRef.current?.requestFullscreen();
    } catch { setFull(!full); }
  }
  const [chartTheme, chooseChartTheme] = useChartTheme();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<{ plot: number; line: number } | null>(null);

  const loadList = () => api.trends().then(setSaved).catch((err) => setError(message(err)));
  useEffect(() => { void loadList(); }, []);
  useEffect(() => {
    setNotice(""); setError("");
    if (!trendId) { setCurrent(null); setName(""); setView(viewFromAddress(window.location.search) ?? EMPTY_VIEW); return; }
    api.trend(trendId).then((trend) => { setCurrent(trend); setName(trend.name); setView({ plots: trend.plots, period: trend.period, step_seconds: trend.step_seconds }); })
      .catch((err) => setError(message(err)));
  }, [trendId]);

  const asked = useMemo(() => readable(view), [view]);
  const key = JSON.stringify(asked);
  useEffect(() => {
    if (!asked.plots.length) { setData(null); return; }
    if (asked.period.mode === "fixed" && (!asked.period.start || !asked.period.end)) return;
    let live = true;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api.trendData(asked).then((value) => { if (live) { setData(value); setError(""); } })
        .catch((err) => { if (live) setError(message(err)); })
        .finally(() => { if (live) setLoading(false); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [key, tick]);

  const setPlot = (index: number, change: Partial<TrendView["plots"][number]>) => setView({ ...view, plots: view.plots.map((plot, at) => (at === index ? { ...plot, ...change } : plot)) });
  const mine = !current || me.can_edit || current.created_by === me.username;

  async function save(asNew: boolean) {
    const label = name.trim() || window.prompt(t("Name of the trend"), "")?.trim();
    if (!label) return;
    try {
      const payload = { ...asked, name: label, description: current?.description ?? "" };
      const result = current && !asNew ? await api.saveTrend(current.trend_id, payload) : await api.createTrend(payload);
      setName(result.name); setCurrent(result); setNotice(t("Saved."));
      await loadList();
      if (result.trend_id !== trendId) navigate(`/trends/${result.trend_id}`);
    } catch (err) { setError(message(err)); }
  }
  async function remove() {
    if (!current || !await confirmAction(t("Delete the trend \"{name}\"?", { name: current.name }), { confirm: t("Delete"), danger: true })) return;
    try { await api.removeTrend(current.trend_id); await loadList(); navigate("/trends"); } catch (err) { setError(message(err)); }
  }
  const slug = (name || "trend").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "trend";
  const stamp = data ? `-${fileStamp(data.read_at)}` : "";
  function csv() {
    if (data) saveCsv(`${slug}${stamp}.csv`, trendCsv(data));
  }

  const period = view.period;
  return <>
    <Heading eyebrow={t("Trends")} title={current?.name ?? t("Trends")}
      detail={current ? t("Saved by {user}, updated {when}.", { user: current.updated_by ?? current.created_by ?? "—", when: when(current.updated_at) }) : t("Pick signals, one plot or several stacked on the same time axis, the period and the interval. Save it to open again.")}
      actions={<>
        <button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => setTick(tick + 1)} disabled={!asked.plots.length}><RefreshCw className={loading ? "spin" : ""} /></button>
        <button className="button button-secondary" onClick={csv} disabled={!data}><Download size={16} /> {t("CSV")}</button>
        {current && mine && <button className="button button-secondary" onClick={() => void remove()}><Trash2 size={16} /> {t("Delete")}</button>}
        {current && <button className="button button-secondary" onClick={() => void save(true)} disabled={!asked.plots.length}>{t("Save as new")}</button>}
        {mine && <button className="button button-primary" onClick={() => void save(false)} disabled={!asked.plots.length}><Save size={16} /> {t("Save")}</button>}
      </>} />
    {error && <ErrorBox text={error} />}
    {notice && <div className="notice notice-ok">{notice}</div>}
    <div className="tc-trends">
      <aside className="panel tc-trend-list">
        <h2>{t("Saved trends")}</h2>
        <Link to="/trends" className={`tc-trend-item ${!trendId ? "active" : ""}`}><Plus size={14} /> {t("New trend")}</Link>
        {!saved ? <Loading /> : saved.length === 0 ? <p className="muted small">{t("None yet: build one and save it.")}</p>
          : saved.map((item) => <Link key={item.trend_id} to={`/trends/${item.trend_id}`} className={`tc-trend-item ${item.trend_id === trendId ? "active" : ""}`}>
            <span>{item.name}</span><small className="muted">{periodLabel(item)} · {item.created_by ?? ""}</small>
          </Link>)}
      </aside>
      <section className="tc-trend-main">
        <div className="panel tc-trend-form">
          <label>{t("Name")}<input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("Name of the trend")} disabled={!mine} /></label>
          <label>{t("Period")}<select value={period.mode === "fixed" ? "fixed" : period.window} onChange={(event) => setView({ ...view, period: event.target.value === "fixed" ? { ...period, mode: "fixed", start: period.start ?? isoOf(localOf(new Date(Date.now() - 86_400_000).toISOString())), end: period.end ?? isoOf(localOf(new Date().toISOString())) } : { ...period, mode: "relative", window: event.target.value } })}>
            {TREND_WINDOWS.map((window) => <option key={window} value={window}>{t("Last {window}", { window: windowLabel(window) })}</option>)}
            <option value="fixed">{t("From – to")}</option>
          </select></label>
          {period.mode === "fixed" && <>
            <label>{t("From")}<input type="datetime-local" value={localOf(period.start ?? "")} onChange={(event) => setView({ ...view, period: { ...period, start: isoOf(event.target.value) || null } })} /></label>
            <label>{t("To")}<input type="datetime-local" value={localOf(period.end ?? "")} onChange={(event) => setView({ ...view, period: { ...period, end: isoOf(event.target.value) || null } })} /></label>
          </>}
          <label>{t("Interval")}<select value={String(view.step_seconds)} onChange={(event) => setView({ ...view, step_seconds: event.target.value === "null" ? null : Number(event.target.value) })}>
            {TREND_STEPS.map((step) => <option key={String(step.seconds)} value={String(step.seconds)}>{t(step.label)}</option>)}
          </select></label>
        </div>
        <div className="panel tc-plots">
          {view.plots.map((plot, index) => <div key={index} className="tc-plot-row">
            <div className="tc-plot-head">
              <input className="tc-plot-title" value={plot.title ?? ""} onChange={(event) => setPlot(index, { title: event.target.value })} placeholder={t("Plot {n}", { n: index + 1 })} aria-label={t("Plot title")} />
              {view.plots.length > 1 && <button type="button" className="icon-button" title={t("Remove this plot")} aria-label={t("Remove this plot")} onClick={() => setView({ ...view, plots: view.plots.filter((_, at) => at !== index) })}><Trash2 size={14} /></button>}
            </div>
            <div className="tc-plot-lines">
              {plot.lines.map((line, at) => <span key={`${line.signal_id}-${at}`} className="tag tc-line-chip"><button type="button" className="tc-line-edit" title={t("Interval, colour and dash of this line")} onClick={() => setEditing({ plot: index, line: at })}><LineSample style={line.style} />{chipText(line)}</button><button type="button" aria-label={t("Remove {name}", { name: line.label || line.signal_id })} onClick={() => setPlot(index, { lines: plot.lines.filter((_, which) => which !== at) })}><X size={12} /></button></span>)}
              {plot.lines.length < MAX_LINES && <SignalSearch key={plot.lines.length} value="" onPick={(signal) => setPlot(index, { lines: [...plot.lines, { signal_id: signal.id, label: "" }] })} />}
            </div>
          </div>)}
          {view.plots.length < MAX_PLOTS && <button type="button" className="button button-secondary button-small" onClick={() => setView({ ...view, plots: [...view.plots, { title: "", lines: [] }] })}><Plus size={14} /> {t("Add a subplot")}</button>}
        </div>
        <div className="panel tc-trend-chart" ref={chartRef}>
          {/* Its own row above the chart, on the left: the chart's buttons (Plotly's) stay top right. */}
          {asked.plots.length > 0 && <div className="tc-trend-toolbar">
            <button type="button" className="button button-secondary button-small" disabled={!data} onClick={() => void toggleFull()}>{full ? <><Minimize2 size={14} /> {t("Exit full screen")}</> : <><Maximize2 size={14} /> {t("Full screen")}</>}</button>
            <label className="tc-chart-theme">{t("Chart")}<select value={chartTheme} onChange={(event) => chooseChartTheme(event.target.value as ChartTheme)} title={t("The chart's colours, the picture (PNG) included, whatever the platform's theme")}>
              {CHART_THEMES.map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}
            </select></label>
            {loading && <LoaderCircle size={14} className="spin" aria-label={t("Reading…")} />}
          </div>}
          {!asked.plots.length && loading && <LoaderCircle size={14} className="spin tc-trend-busy" />}
          {!asked.plots.length ? <p className="muted tc-empty">{t("Add a signal to a plot to draw it.")}</p>
            : data ? <>
              <TrendChart key={full ? "full" : "page"} data={data} theme={chartTheme} filename={`${slug}${stamp}`} height={full ? Math.max(320, globalThis.innerHeight - 140) : undefined} />
              {data.range.shifted && <p className="tc-note">{t("No samples in the period: showing the newest data, up to {end}.", { end: formatDate(data.range.end) })}</p>}
              <ul className="tc-problems">{data.plots.flatMap((plot) => plot.lines).filter((line) => line.note).map((line, index) => <li key={`note-${index}`} className="tc-note-item"><b>{line.label}</b> {line.note}</li>)}{data.plots.flatMap((plot) => plot.lines).filter((line) => line.error).map((line, index) => <li key={index}><b>{line.label}</b> {line.error}</li>)}</ul>
            </> : <Loading />}
        </div>
      </section>
    </div>
    {editing && view.plots[editing.plot]?.lines[editing.line] && <LineEditor line={view.plots[editing.plot].lines[editing.line]} trendStep={view.step_seconds} onClose={() => setEditing(null)}
      onApply={(line) => { const plot = view.plots[editing.plot]; setPlot(editing.plot, { lines: plot.lines.map((item, at) => (at === editing.line ? line : item)) }); setEditing(null); }} />}
  </>;
}

/** A trend over another page: a click on a value of a process display draws
 * its signals here, with the period, the interval and each line's settings as in Trends, without
 * leaving the display; "Open in Trends" goes on with it there (to save it, add subplots).
 * Rendered where it is opened, so it shows inside a full-screen display too. */
export function TrendDialog({ title, signals, period: initial, onClose }: { title: string; signals: string[]; period: TrendPeriod; onClose: () => void }) {
  const [view, setView] = useState<TrendView>(() => ({ plots: [{ title: "", lines: signals.slice(0, MAX_LINES).map((signal_id) => ({ signal_id, label: "" })) }], period: initial, step_seconds: null }));
  const [data, setData] = useState<TrendData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [chartTheme, chooseChartTheme] = useChartTheme();
  const asked = useMemo(() => readable(view), [view]);
  const key = JSON.stringify(asked);
  useEffect(() => {
    if (!asked.plots.length) { setData(null); return undefined; }
    let live = true;
    setLoading(true);
    api.trendData(asked).then((value) => { if (live) { setData(value); setError(""); } })
      .catch((err) => { if (live) setError(message(err)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);
  const lines = view.plots[0].lines;
  const setLines = (next: TrendLineSpec[]) => setView({ ...view, plots: [{ ...view.plots[0], lines: next }] });
  const period = view.period;
  function openInTrends() {
    const params = new URLSearchParams();
    for (const line of lines) params.append("signal", line.signal_id);
    if (data && period.mode === "fixed") { params.set("start", data.range.start); params.set("end", data.range.end); }
    onClose();
    navigate(`/trends?${params.toString()}`);
  }
  return <Dialog wide title={title} onClose={onClose}
    footer={<>
      <button type="button" className="button button-secondary" onClick={() => data && saveCsv(`trend${data ? `-${fileStamp(data.read_at)}` : ""}.csv`, trendCsv(data))} disabled={!data}><Download size={16} /> {t("CSV")}</button>
      <button type="button" className="button button-secondary" onClick={openInTrends} disabled={!lines.length}><ExternalLink size={16} /> {t("Open in Trends")}</button>
      <button type="button" className="button button-primary" onClick={onClose}>{t("Close")}</button>
    </>}>
    <div className="tc-trend-dialog">
      <div className="tc-trend-form tc-trend-dialog-form">
        <label>{t("Period")}<select value={period.mode === "fixed" ? "fixed" : period.window} onChange={(event) => setView({ ...view, period: event.target.value === "fixed" ? { ...period, mode: "fixed", start: period.start ?? isoOf(localOf(new Date(Date.now() - 86_400_000).toISOString())), end: period.end ?? isoOf(localOf(new Date().toISOString())) } : { ...period, mode: "relative", window: event.target.value } })}>
          {TREND_WINDOWS.map((window) => <option key={window} value={window}>{t("Last {window}", { window: windowLabel(window) })}</option>)}
          <option value="fixed">{t("From – to")}</option>
        </select></label>
        {period.mode === "fixed" && <>
          <label>{t("From")}<input type="datetime-local" value={localOf(period.start ?? "")} onChange={(event) => setView({ ...view, period: { ...period, start: isoOf(event.target.value) || null } })} /></label>
          <label>{t("To")}<input type="datetime-local" value={localOf(period.end ?? "")} onChange={(event) => setView({ ...view, period: { ...period, end: isoOf(event.target.value) || null } })} /></label>
        </>}
        <label>{t("Interval")}<select value={String(view.step_seconds)} onChange={(event) => setView({ ...view, step_seconds: event.target.value === "null" ? null : Number(event.target.value) })}>
          {TREND_STEPS.map((step) => <option key={String(step.seconds)} value={String(step.seconds)}>{t(step.label)}</option>)}
        </select></label>
        <label>{t("Chart")}<select value={chartTheme} onChange={(event) => chooseChartTheme(event.target.value as ChartTheme)}>
          {CHART_THEMES.map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}
        </select></label>
        <button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => setTick(tick + 1)} disabled={!lines.length}><RefreshCw className={loading ? "spin" : ""} /></button>
      </div>
      <div className="tc-plot-lines">
        {lines.map((line, at) => <span key={`${line.signal_id}-${at}`} className="tag tc-line-chip"><button type="button" className="tc-line-edit" title={t("Interval, colour and dash of this line")} onClick={() => setEditing(at)}><LineSample style={line.style} />{chipText(line)}</button><button type="button" aria-label={t("Remove {name}", { name: line.label || line.signal_id })} onClick={() => setLines(lines.filter((_, which) => which !== at))}><X size={12} /></button></span>)}
        {lines.length < MAX_LINES && <SignalSearch key={lines.length} value="" onPick={(signal) => setLines([...lines, { signal_id: signal.id, label: "" }])} />}
      </div>
      {error && <ErrorBox text={error} />}
      {!lines.length ? <p className="muted tc-empty">{t("Add a signal to draw it.")}</p>
        : data ? <>
          <TrendChart data={data} theme={chartTheme} filename="trend" height={Math.max(260, Math.min(460, globalThis.innerHeight - 330))} />
          {data.range.shifted && <p className="tc-note">{t("No samples in the period: showing the newest data, up to {end}.", { end: formatDate(data.range.end) })}</p>}
          <ul className="tc-problems">{data.plots.flatMap((plot) => plot.lines).filter((line) => line.error).map((line, index) => <li key={index}><b>{line.label}</b> {line.error}</li>)}</ul>
        </> : <Loading />}
    </div>
    {editing !== null && lines[editing] && <LineEditor line={lines[editing]} trendStep={view.step_seconds} onClose={() => setEditing(null)}
      onApply={(line) => { setLines(lines.map((item, at) => (at === editing ? line : item))); setEditing(null); }} />}
  </Dialog>;
}
