/** An alarm performance section of a report (ISA-18.2, EEMUA 191): what Alarms publishes, once
 * an hour, about the site or one area (`alarmcraft.alarm_performance`), laid out as the PDF,
 * Word, HTML and Markdown files lay it out (`reports/alarm_performance.py`). View never calls
 * Alarms: when Alarms has published nothing for the asset, the section says so. */
import { Dialog, Pill, errorMessage as message } from "@plantcraft/ui";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { stateStatus } from "./model";
import type { AlarmsData, AssetOption, Section, SectionData, State } from "./types";
import { ErrorBox } from "./ui";

const PERIOD_WORDS: Record<string, string> = { "24h": "the last 24 hours", "7d": "the last 7 days", "30d": "the last 30 days" };
const LEVEL_WORDS: Record<string, string> = { robust: "Robust", stable: "Stable", reactive: "Reactive", overloaded: "Overloaded" };
const LEVEL_STATE: Record<string, State> = { robust: "ok", stable: "ok", reactive: "warning", overloaded: "alarm" };
const PRIORITY_WORDS: Record<string, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const PRIORITY_STATE: Record<string, State | undefined> = { critical: "alarm", high: "alarm", medium: "warning" };
const STATUS_WORDS: Record<string, string> = { ok: "Acceptable", warning: "Manageable", alarm: "Over target" };

/** "40 s", "12 min", "1.5 h", as the files write it. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "–";
  if (seconds < 90) return `${seconds.toFixed(0)} s`;
  if (seconds < 90 * 60) return `${(seconds / 60).toFixed(0)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

const short = (at: string) => formatDate(at, { dateStyle: "short", timeStyle: "short" });
const priority = (value: string) => <Pill status={stateStatus(PRIORITY_STATE[value])} label={t(PRIORITY_WORDS[value] ?? value)} />;

/** What the section shows on the report page. */
export function AlarmsView({ section, read, tick }: { section: Section; read: () => Promise<SectionData>; tick: number }) {
  const [state, setState] = useState<{ data: AlarmsData | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });
  useEffect(() => {
    let live = true;
    setState((old) => ({ ...old, loading: true }));
    read().then((found) => { if (live) setState({ data: (found.data as AlarmsData | null) ?? null, error: found.error ?? "", loading: false }); })
      .catch((err) => { if (live) setState({ data: null, error: message(err), loading: false }); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(section), tick]);
  const { data, error, loading } = state;
  const reading = data?.reading ?? null;
  const title = section.title || t("Alarm performance");
  if (!section.alarms?.asset_id) return <div className="tc-report-events"><h3>{title}</h3><p className="muted">{t("Pick the site or area in the section's settings.")}</p></div>;
  const level = reading?.eemua.level ?? "";
  return <div className="tc-report-events tc-report-alarms">
    <h3>{title}{loading && <LoaderCircle size={13} className="spin" />}</h3>
    {error && <div className="tc-card-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!data && !error && <div className="tc-card-loading"><LoaderCircle className="spin" /></div>}
    {data && reading && <>
      <p className="tc-report-lead">
        <Pill status={stateStatus(LEVEL_STATE[level])} label={`EEMUA 191: ${t(LEVEL_WORDS[level] ?? level)}`} />{" "}
        {t("{asset}, {period}: average {average} and peak {peak} alarms per 10 minutes. Alarms raised: {total}. Floods: {floods} ({minutes} min).", {
          asset: data.asset_name, period: t(PERIOD_WORDS[data.period] ?? data.period),
          average: reading.eemua.average_per_10min, peak: reading.eemua.peak_per_10min, total: reading.total,
          floods: reading.flood_count, minutes: reading.flood_minutes,
        })}
        {!data.exact && ` ${t("Alarms publishes 24 hours, 7 days and 30 days; this is the closest.")}`}
      </p>
      <h4>{t("Figures against the targets")}</h4>
      <table className="tc-report-table">
        <thead><tr><th>{t("Figure")}</th><th className="pc-num">{t("Value")}</th><th>{t("Target")}</th><th>{t("Status")}</th></tr></thead>
        <tbody>{reading.figures.map((figure) => <tr key={figure.id}>
          <td>{t(figure.label || figure.id)}</td>
          <td className="pc-num">{figure.value ?? "–"}{figure.unit}</td>
          <td>{figure.target}</td>
          <td><Pill status={stateStatus(figure.status as State)} label={t(STATUS_WORDS[figure.status] ?? figure.status)} /></td>
        </tr>)}</tbody>
      </table>
      <h4>{t("Most frequent alarms")}</h4>
      {reading.top.length ? <table className="tc-report-table">
        <thead><tr><th className="pc-num">#</th><th>{t("Alarm name")}</th><th>{t("Priority")}</th><th className="pc-num">{t("Raised")}</th><th className="pc-num">{t("Share")}</th></tr></thead>
        <tbody>{reading.top.map((row, index) => <tr key={row.alarm_id}>
          <td className="pc-num">{index + 1}</td>
          <td>{row.name}{row.chattering && <small className="muted"> ({t("chattering")})</small>}</td>
          <td>{priority(row.priority)}</td>
          <td className="pc-num"><b>{row.count}</b></td>
          <td className="pc-num">{row.share}%</td>
        </tr>)}</tbody>
      </table> : <p className="muted">{t("No alarm was raised in the period.")}</p>}
      <h4>{t("Floods")}</h4>
      {reading.floods.length ? <table className="tc-report-table">
        <thead><tr><th>{t("Start")}</th><th>{t("End")}</th><th className="pc-num">{t("Minutes")}</th><th className="pc-num">{t("Alarms")}</th><th className="pc-num">{t("Peak in 10 min")}</th></tr></thead>
        <tbody>{reading.floods.map((flood) => <tr key={flood.start}>
          <td className="pc-num">{short(flood.start)}</td><td className="pc-num">{short(flood.end)}</td>
          <td className="pc-num">{flood.minutes}</td><td className="pc-num">{flood.alarms}</td><td className="pc-num">{flood.peak}</td>
        </tr>)}</tbody>
      </table> : <p className="muted">{t("No flood in the period.")}</p>}
      {reading.flood_count > reading.floods.length && <small className="muted">{t("The {n} latest of {total} are listed.", { n: reading.floods.length, total: reading.flood_count })}</small>}
      <h4>{t("Time to acknowledge")}</h4>
      {reading.acknowledge.length ? <table className="tc-report-table">
        <thead><tr><th>{t("Priority")}</th><th className="pc-num">{t("Acknowledged")}</th><th className="pc-num">{t("Half within")}</th><th className="pc-num">{t("9 in 10 within")}</th></tr></thead>
        <tbody>{reading.acknowledge.map((row) => <tr key={row.priority}>
          <td>{priority(row.priority)}</td><td className="pc-num">{row.count}</td>
          <td className="pc-num">{duration(row.median_seconds)}</td><td className="pc-num">{duration(row.p90_seconds)}</td>
        </tr>)}</tbody>
      </table> : <p className="muted">{t("No alarm was acknowledged in the period.")}</p>}
      {reading.unacked > 0 && <small className="muted">{t("{n} alarms of the period are not acknowledged yet.", { n: reading.unacked })}</small>}
      <h4>{t("Fleeting alarms")}</h4>
      {reading.fleeting.length ? <table className="tc-report-table">
        <thead><tr><th>{t("Alarm name")}</th><th className="pc-num">{t("Times")}</th></tr></thead>
        <tbody>{reading.fleeting.map((row) => <tr key={row.alarm_id}><td>{row.name}</td><td className="pc-num">{row.count}</td></tr>)}</tbody>
      </table> : <p className="muted">{t("None: every alarm stayed long enough to be read.")}</p>}
      {data.at && <small className="muted">{t("Published by Alarms {when}.", { when: short(data.at) })}</small>}
    </>}
  </div>;
}

/** Which part of the plant the section covers: the site or one area (Alarms publishes those). */
export function AlarmsDialog({ section, onSave, onClose }: { section: Section; onSave: (section: Section) => void; onClose: () => void }) {
  const [value, setValue] = useState<Section>({ ...section, alarms: section.alarms ?? { asset_id: "" } });
  const [assets, setAssets] = useState<AssetOption[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.assets().then(setAssets).catch((err) => { setAssets([]); setError(message(err)); }); }, []);
  const listed = useMemo(() => {
    const rank: Record<string, number> = { site: 0, area: 1, unit: 2 };
    return (assets ?? []).filter((asset) => asset.kind in rank || !asset.parent)
      .sort((a, b) => (rank[a.kind] ?? 3) - (rank[b.kind] ?? 3) || a.name.localeCompare(b.name));
  }, [assets]);
  const assetId = value.alarms?.asset_id ?? "";
  return <Dialog title={t("Alarm performance section")} onClose={onClose} onSubmit={() => onSave(value)}>
    {error && <ErrorBox text={error} />}
    <div className="form-grid tc-settings">
      <label className="tc-wide">{t("Title")}<input autoFocus maxLength={120} value={value.title} onChange={(event) => setValue({ ...value, title: event.target.value })} /></label>
      <label className="tc-wide">{t("Site or area")}
        <select value={assetId} onChange={(event) => setValue({ ...value, alarms: { asset_id: event.target.value } })}>
          <option value="">{assets === null ? t("Reading the assets…") : t("Pick one")}</option>
          {listed.map((asset) => <option key={asset.id} value={asset.id}>{asset.name} ({asset.kind})</option>)}
        </select>
        <small className="muted">{t("Alarms publishes, every hour, the site's performance and each area's: the figures against the philosophy's targets, the EEMUA 191 level, floods, time to acknowledge, the most frequent and the fleeting alarms. The report shows the reading closest to its period (24 hours, 7 days or 30 days).")}</small>
      </label>
    </div>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit" disabled={!assetId}>{t("Apply")}</button></footer>
  </Dialog>;
}
