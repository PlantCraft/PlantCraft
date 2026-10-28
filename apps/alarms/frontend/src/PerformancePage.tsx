import { DataTable, useAssistantPage, BRAND_COLORS, currentTheme, plotTheme, statusVar } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatDuration, t } from "./i18n";
import { Plot } from "@plantcraft/ui/plot";
import { useDirectory, whoLabel } from "./people";
import type { Performance } from "./types";
import { PerformanceTabs } from "./PerformanceTabs";
import { ErrorBox, Heading, Link, Loading, Pill, PRIORITY_WORDS, WindowPicker, message } from "./ui";

const FIGURE_WORDS: Record<string, string> = { ok: "Acceptable", warning: "Manageable", alarm: "Over target" };

/** Alarm performance against the ISA-18.2 and EEMUA 191 targets. */
export function PerformancePage() {
  const [period, setPeriod] = useState("24h");
  const [data, setData] = useState<Performance | null>(null);
  const [error, setError] = useState("");
  const directory = useDirectory();
  useEffect(() => { setData(null); api.performance(period).then(setData).catch((err) => setError(message(err))); }, [period]);
  // Alarms' works here (app.toml): the load against the targets, the bad actors.
  useAssistantPage(data && { place: t("Alarms › Performance"), page: "alarmcraft:performance", facts: { period, total: data.total, unacked: data.unacked, mean_ack_seconds: data.mean_ack_seconds ?? "" },
    view: { top: data.top.slice(0, 15).map((item) => `${item.name} (${item.alarm_id}): ${item.count}, ${Math.round(100 * item.share)} %${item.chattering ? ", chattering" : ""}`), stale: data.stale.slice(0, 15).map((item) => item.alarm_id), priorities: data.priorities.map((item) => `${item.priority} ${Math.round(100 * item.share)} % (target ${Math.round(100 * item.target)} %)`) } });
  const mode = currentTheme();
  const layout = plotTheme(mode);
  const colors = BRAND_COLORS[mode];
  return <>
    <Heading eyebrow={<Link to="/">{t("Overview")}</Link>} title={t("Performance")}
      detail={t("The alarm load for one operator position against the ISA-18.2 and EEMUA 191 targets. Alerts are not counted.")}
      actions={<WindowPicker value={period} onChange={setPeriod} />} />
    <PerformanceTabs />
    {error && <ErrorBox text={error} />}
    {!data ? <Loading /> : <>
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
        <div className="panel table-panel">
          <div className="panel-header al-pad"><div><h2>{t("Most frequent alarms")}</h2><p>{t("{share}% of the load comes from these ten.", { share: data.top.reduce((sum, item) => sum + item.share, 0).toFixed(0) })}</p></div></div>
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
