import { DataTable, useAssistantPage, BRAND_COLORS, currentTheme, plotTheme, statusVar } from "@plantcraft/ui";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { formatDate, formatDuration, t } from "./i18n";
import { Plot } from "@plantcraft/ui/plot";
import { homeConsole } from "./consoles";
import { useDirectory, whoLabel } from "./people";
import type { ConsoleLoads, Me, Performance } from "./types";
import { PerformanceTabs } from "./PerformanceTabs";
import { ErrorBox, Heading, Link, Loading, Pill, PRIORITY_WORDS, WindowPicker, message } from "./ui";

const FIGURE_WORDS: Record<string, string> = { ok: "Acceptable", warning: "Manageable", alarm: "Over target" };

const EEMUA_WORDS: Record<string, string> = { robust: "Robust", stable: "Stable", reactive: "Reactive", overloaded: "Overloaded" };
const EEMUA_STATUS: Record<string, string> = { robust: "ok", stable: "ok", reactive: "warning", overloaded: "alarm" };

/** Each operator position's load against its own target (shown once consoles are set). */
function ConsolesTable({ loads, chosen, onChoose }: { loads: ConsoleLoads; chosen: string; onChoose: (id: string) => void }) {
  return <section className="panel table-panel">
    <div className="panel-header al-pad"><div><h2>{t("Consoles")}</h2><p>{t("Each operator position against its own target, in this period.")}</p></div></div>
    <DataTable rows={loads.consoles} rowKey={(item) => item.id} label={t("Consoles")} columns={[
      { key: "name", label: t("Console"), sort: (item) => item.name, render: (item) => <button type="button" className={`link-button${item.id === chosen ? " strong" : ""}`} onClick={() => onChoose(item.id)}>{item.name}</button> },
      { key: "alarms", label: t("Alarms"), numeric: true, phone: "hide", sort: (item) => item.alarms },
      { key: "total", label: t("Raised"), numeric: true, sort: (item) => item.total },
      { key: "per_hour", label: t("Per hour"), numeric: true, sort: (item) => item.per_hour, render: (item) => <><span className="pc-num">{item.per_hour}</span> <small className="muted">≤ {item.target_per_hour}</small> <Pill status={item.per_hour_status} label={t(FIGURE_WORDS[item.per_hour_status] ?? item.per_hour_status)} /></> },
      { key: "peak", label: t("Peak in 10 min"), numeric: true, phone: "hide", sort: (item) => item.peak_10min, render: (item) => <Pill status={item.peak_status} label={String(item.peak_10min)} /> },
      { key: "eemua", label: t("EEMUA 191"), sort: (item) => item.eemua, render: (item) => <Pill status={EEMUA_STATUS[item.eemua] ?? "unknown"} label={t(EEMUA_WORDS[item.eemua] ?? item.eemua)} /> },
    ]} />
  </section>;
}

/** Alarm performance against the ISA-18.2 and EEMUA 191 targets: of every alarm the person
 * sees, or of one console (operator position) against its own target. */
export function PerformancePage({ me, console: asked }: { me: Me; console?: string }) {
  const [period, setPeriod] = useState("24h");
  const [data, setData] = useState<Performance | null>(null);
  const [loads, setLoads] = useState<ConsoleLoads | null>(null);
  const [chosen, setChosen] = useState<string | null>(asked ?? null);
  const [error, setError] = useState("");
  const directory = useDirectory();
  const picked = useRef(asked !== undefined);
  useEffect(() => { api.consoleLoads(period).then(setLoads).catch(() => setLoads({ window: period, consoles: [], defined: 0 })); }, [period]);
  // Opened without a console: the one the person sits at, once the consoles are known.
  useEffect(() => {
    if (picked.current || !loads) return;
    picked.current = true;
    setChosen(loads.defined ? homeConsole(loads.consoles, me.username) : "");
  }, [loads, me.username]);
  useEffect(() => {
    if (chosen === null) return;
    setData(null); setError("");
    api.performance(period, chosen || undefined).then(setData).catch((err) => setError(message(err)));
  }, [period, chosen]);
  const choose = (id: string) => { picked.current = true; setChosen(id); };
  // Alarms' works here (app.toml): the load against the targets, the bad actors.
  useAssistantPage(data && { place: t("Alarms › Performance"), page: "alarmcraft:performance", facts: { period, console: data.console?.name ?? "", total: data.total, unacked: data.unacked, mean_ack_seconds: data.mean_ack_seconds ?? "" },
    view: { top: data.top.slice(0, 15).map((item) => `${item.name} (${item.alarm_id}): ${item.count}, ${Math.round(100 * item.share)} %${item.chattering ? ", chattering" : ""}`), stale: data.stale.slice(0, 15).map((item) => item.alarm_id), priorities: data.priorities.map((item) => `${item.priority} ${Math.round(100 * item.share)} % (target ${Math.round(100 * item.target)} %)`) } });
  const mode = currentTheme();
  const layout = plotTheme(mode);
  const colors = BRAND_COLORS[mode];
  return <>
    <Heading eyebrow={<Link to="/">{t("Overview")}</Link>} title={t("Performance")}
      detail={t("The alarm load for one operator position against the ISA-18.2 and EEMUA 191 targets. Alerts are not counted.")}
      actions={<WindowPicker value={period} onChange={setPeriod} />} />
    <PerformanceTabs />
    {loads && loads.defined > 0 && <div className="al-console-pick">
      <label>{t("Console")} <select aria-label={t("Console")} value={chosen ?? ""} onChange={(event) => choose(event.target.value)}>
        <option value="">{t("Every alarm")}</option>
        {loads.consoles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {data?.console && <span className="muted small">{t("Console {name}: at most {n} alarms an hour for its operator.", { name: data.console.name, n: data.console.per_hour })}</span>}
      <Link to="/targets">{t("Set the consoles")}</Link>
    </div>}
    {error && <ErrorBox text={error} />}
    {!data ? <Loading /> : <>
      {loads && loads.defined > 0 && <ConsolesTable loads={loads} chosen={chosen ?? ""} onChoose={choose} />}
      <section className="pc-grid">
        {data.figures.map((figure) => <div key={figure.id} className="panel kpi-card" style={{ borderTopColor: statusVar(figure.status) }}>
          <small>{t(figure.label)}</small>
          <span className="kpi-value pc-num">{figure.value}{figure.unit ?? ""}</span>
          <Pill status={figure.status} label={t(FIGURE_WORDS[figure.status] ?? figure.status)} />
          <small>{t("Target: {target}", { target: figure.target })}</small>
          {figure.help && <small className="muted">{t(figure.help)}</small>}
        </div>)}
        <div className="panel kpi-card">
          <small>{t("Alarms raised")}</small>
          <span className="kpi-value pc-num">{data.total}</span>
          <small>{data.mean_ack_seconds === null ? t("No acknowledgement yet") : t("Acknowledged after {time} on average", { time: formatDuration(data.mean_ack_seconds) })}</small>
        </div>
      </section>
      <section className="panel">
        <div className="panel-header"><div><h2>{t("Alarms per 10 minutes")}</h2><p>{t("Above the line (10) the operator is in a flood.")}</p></div></div>
        <Plot
          data={[{ type: "bar", x: data.per_slot.map((slot) => slot.at), y: data.per_slot.map((slot) => slot.count), marker: { color: data.per_slot.map((slot) => (slot.count > 10 ? colors.problem : colors.primary)) }, hovertemplate: "%{x}<br>%{y}<extra></extra>" }]}
          layout={{ ...layout, height: 260, margin: { l: 40, r: 10, t: 10, b: 40 }, shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 10, y1: 10, line: { dash: "dot", width: 1, color: colors.problem } }] }}
          config={{ displaylogo: false, responsive: true }}
          style={{ width: "100%" }}
          useResizeHandler
        />
      </section>
      <section className="pc-grid pc-grid-2">
        <EemuaChart data={data} />
        <div className="panel">
          <div className="panel-header"><div><h2>{t("Floods")}</h2><p>{t("A flood starts above {limit} alarms in 10 minutes and ends below half of it, so a short lull does not split it.", { limit: 10 })}</p></div></div>
          {data.floods.length ? <ul>{data.floods.map((flood) => <li key={flood.start}>
            {formatDate(flood.start)}: <b>{t("{minutes} min", { minutes: flood.minutes })}</b>, {t("{alarms} alarms, peak {peak} in 10 minutes", { alarms: flood.alarms, peak: flood.peak })}
          </li>)}</ul> : <p className="muted">{t("No flood in this period.")}</p>}
          <h3>{t("Time to acknowledge")}</h3>
          {data.acknowledge.length ? <ul>{data.acknowledge.map((row) => <li key={row.priority}>
            {t(PRIORITY_WORDS[row.priority] ?? row.priority)}: {t("half within {median}, 9 in 10 within {p90}", { median: formatDuration(row.median_seconds ?? 0), p90: formatDuration(row.p90_seconds ?? 0) })} <span className="muted">({row.count})</span>
          </li>)}</ul> : <p className="muted">{t("No acknowledgement yet")}</p>}
          <h3>{t("Fleeting alarms")}</h3>
          {data.fleeting.length ? <p>{data.fleeting.map((item, index) => <span key={item.alarm_id}>{index ? ", " : ""}<Link to={`/alarms/${item.alarm_id}`}>{item.name}</Link> ({item.count})</span>)}</p>
            : <p className="muted">{t("None: every alarm stayed long enough to be read.")}</p>}
        </div>
      </section>
      <section className="pc-grid pc-grid-2">
        <div className="panel table-panel">
          <div className="panel-header al-pad"><div><h2>{t("Most frequent alarms")}</h2><p>{t("The 20 raised most often; {share}% of the load comes from the first ten.", { share: data.top.slice(0, 10).reduce((sum, item) => sum + item.share, 0).toFixed(0) })}</p></div></div>
          {data.top.length ? <DataTable rows={data.top} rowKey={(item) => item.alarm_id} label={t("Most frequent alarms")} initialSort={{ key: "count", descending: true }} columns={[
            { key: "name", label: t("Alarm"), sort: (item) => item.name, render: (item) => <><Link to={`/alarms/${item.alarm_id}`}>{item.name}</Link>{item.chattering && <> <Pill status="alarm" label={t("Chattering")} /></>}</> },
            { key: "owner", label: t("Owner"), className: "small", sort: (item) => whoLabel(item.owner, directory), render: (item) => whoLabel(item.owner, directory) },
            { key: "count", label: t("Raised"), numeric: true, sort: (item) => item.count },
            { key: "share", label: t("Share"), numeric: true, sort: (item) => item.share, render: (item) => `${item.share}%` },
          ]} /> : <p className="muted al-pad">{t("No alarm was raised in this period.")}</p>}
        </div>
        <div className="panel">
          <div className="panel-header"><div><h2>{t("Priority distribution")}</h2><p>{t("Most alarms should be low priority.")}</p></div></div>
          <div className="al-shares">{data.priorities.map((item) => <div key={item.priority} className="al-share">
            <span>{t(PRIORITY_WORDS[item.priority] ?? item.priority)}</span>
            <div className="health-bar"><span style={{ width: `${Math.min(100, item.share)}%`, background: statusVar(`priority-${item.priority}`) }} /></div>
            <b className="pc-num">{item.share}%</b>
            <small className="muted">{t("target {target}%", { target: item.target })}</small>
          </div>)}</div>
          {data.stale.length > 0 && <p>{t("Stale (active over 24 h):")} {data.stale.map((item, index) => <span key={item.alarm_id}>{index ? ", " : ""}<Link to={`/alarms/${item.alarm_id}`}>{item.name}</Link></span>)}</p>}
        </div>
      </section>
    </>}
  </>;
}

/** The EEMUA 191 chart: the period as one point, average against peak alarms per 10 minutes,
 * over the four bands (robust, stable, reactive, overloaded). */
function EemuaChart({ data }: { data: Performance }) {
  const mode = currentTheme();
  const layout = plotTheme(mode);
  const colors = BRAND_COLORS[mode];
  const { level, average_per_10min: average, peak_per_10min: peak } = data.eemua;
  const x = Math.max(average, 0.01);
  const y = Math.max(peak, 1);
  const band = (x0: number, x1: number, y0: number, y1: number, color: string) => ({ type: "rect", xref: "x", yref: "y", x0, x1, y0, y1, fillcolor: color, opacity: 0.12, line: { width: 0 }, layer: "below" });
  return <div className="panel">
    <div className="panel-header"><div><h2>{t("EEMUA 191 level")}</h2><p>{t("Average against peak alarms per 10 minutes.")}</p></div>
      <Pill status={EEMUA_STATUS[level] ?? "unknown"} label={t(EEMUA_WORDS[level] ?? level)} /></div>
    <Plot
      data={[{ type: "scatter", mode: "markers+text", x: [x], y: [y], text: [t("This period")], textposition: "top center", marker: { size: 12, color: colors.primary } }]}
      layout={{ ...layout, height: 260, margin: { l: 50, r: 10, t: 10, b: 40 }, showlegend: false,
        xaxis: { ...layout.xaxis, type: "log", range: [-2, 3], title: { text: t("Average per 10 minutes") } },
        yaxis: { ...layout.yaxis, type: "log", range: [0, 4], title: { text: t("Peak per 10 minutes") } },
        shapes: [band(0.01, 1, 1, 10, colors.good), band(0.01, 1, 10, 100, colors.primary), band(0.01, 1, 100, 10000, colors.attention), band(1, 10, 1, 10000, colors.attention), band(10, 1000, 1, 10000, colors.problem)] }}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: "100%" }}
      useResizeHandler
    />
  </div>;
}
