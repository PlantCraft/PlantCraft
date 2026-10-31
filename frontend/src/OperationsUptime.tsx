/** Operations › Status: each app's uptime over 24 h, 7 and 30 days (planned maintenance left
 * out), and the maintenance windows that keep the watch quiet about the apps they cover.
 * See docs/operations.md, section 4, and plantcraft/watch/uptime.py. */
import { AlertTriangle, CalendarClock, LoaderCircle, Wrench } from "lucide-react";
import { type DataColumn, DataTable, Dialog, formatDate } from "@plantcraft/ui";
import { useCallback, useEffect, useState } from "react";
import { errorText } from "./collab";
import { t } from "./i18n";
import { operationsApi, type MaintenanceWindow, type UptimeAnswer, type UptimeRow } from "./operationsApi";
import "./operations.css";

const WINDOWS = ["24h", "7d", "30d"] as const;
const WINDOW_LABEL: Record<(typeof WINDOWS)[number], string> = { "24h": "24 h", "7d": "7 days", "30d": "30 days" };

/** "99.95 %", or "—" before anything was watched. */
export function uptimeText(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(value >= 99.995 ? 0 : 2)} %`;
}

/** Below 99 % is worth a look; below 95 % is bad. */
export function uptimeTone(value: number | null | undefined): "" | "warn" | "bad" {
  if (value == null) return "";
  if (value < 95) return "bad";
  return value < 99 ? "warn" : "";
}

/** Where a window stands now: planned, in force, ended. */
export function windowState(window: Pick<MaintenanceWindow, "starts_at" | "ends_at" | "ended_at">, now = Date.now()): "planned" | "active" | "ended" {
  if (window.ended_at || Date.parse(window.ends_at) <= now) return "ended";
  return Date.parse(window.starts_at) > now ? "planned" : "active";
}

export function UptimePanel({ admin, services }: { admin: boolean; services: string[] }) {
  const [answer, setAnswer] = useState<UptimeAnswer | null>(null);
  const [error, setError] = useState("");
  const [planning, setPlanning] = useState(false);
  const load = useCallback(() => operationsApi.uptime().then((found) => { setAnswer(found); setError(""); }, (err) => setError(errorText(err))), []);
  useEffect(() => { void load(); }, [load]);
  async function end(window: MaintenanceWindow) {
    try { await operationsApi.endMaintenance(window.window_id); await load(); } catch (err) { setError(errorText(err)); }
  }
  const columns: DataColumn<UptimeRow>[] = [
    { key: "service", label: t("Service"), sort: (item) => item.service, render: (item) => <strong>{item.service}</strong> },
    ...WINDOWS.map((key): DataColumn<UptimeRow> => ({
      key, label: t(WINDOW_LABEL[key]), numeric: true, phone: key === "24h" ? undefined : "hide", sort: (item) => item.uptime[key] ?? -1,
      render: (item) => { const tone = uptimeTone(item.uptime[key]); return <span className={tone ? `ops-uptime-${tone}` : undefined}>{uptimeText(item.uptime[key])}{item.outages[key] > 0 && <small className="apps-sub">{t("{count} outages", { count: item.outages[key] })}</small>}</span>; },
    })),
  ];
  const windows = answer?.windows ?? [];
  return <section className="panel ops-uptime" aria-labelledby="ops-uptime-title">
    <div className="ops-health-head">
      <h2 id="ops-uptime-title"><CalendarClock size={17} /> {t("Uptime")}</h2>
      {admin && <button type="button" className="button button-secondary" onClick={() => setPlanning(true)}><Wrench size={15} /> {t("Plan maintenance")}</button>}
    </div>
    <p className="muted">{t("The share of time each app ran without an outage: stopped, unhealthy or restarting. Planned maintenance is left out.")}{answer?.since ? ` ${t("Watched since {date}.", { date: formatDate(answer.since) })}` : ""}</p>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!answer && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {windows.length > 0 && <ul className="ops-windows" aria-label={t("Maintenance windows")}>{windows.map((item) => { const state = windowState(item); return <li key={item.window_id} className={`ops-window ops-window-${state}`}>
      <span className={`apps-chip${state === "active" ? " apps-chip-warn" : ""}`}>{state === "active" ? t("In maintenance") : state === "planned" ? t("Planned") : t("Ended")}</span>
      <strong>{item.reason}</strong>
      <span className="muted">{formatDate(item.starts_at)} – {formatDate(item.ended_at ?? item.ends_at)} · {item.services?.length ? item.services.join(", ") : t("every app")}</span>
      {admin && state !== "ended" && <button type="button" className="button button-ghost" onClick={() => void end(item)}>{state === "planned" ? t("Cancel") : t("End now")}</button>}
    </li>; })}</ul>}
    {answer && <DataTable rows={answer.services} columns={columns} rowKey={(item) => item.service} label={t("Uptime")} initialSort={{ key: "service", descending: false }} empty={t("Nothing watched yet.")} />}
    {planning && <PlanDialog services={services} onClose={() => setPlanning(false)} onPlanned={() => { setPlanning(false); void load(); }} />}
  </section>;
}

function PlanDialog({ services, onClose, onPlanned }: { services: string[]; onClose: () => void; onPlanned: () => void }) {
  const [reason, setReason] = useState("");
  const [start, setStart] = useState("");
  const [hours, setHours] = useState("2");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const value = Number(hours.replace(",", "."));
  async function submit() {
    if (!reason.trim() || !(value > 0)) return;
    setBusy(true);
    try { await operationsApi.planMaintenance({ reason: reason.trim(), hours: value, services: chosen.length ? chosen : null, starts_at: start ? new Date(start).toISOString() : null }); onPlanned(); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <Dialog title={t("Plan maintenance")} onClose={onClose} onSubmit={() => void submit()}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !reason.trim() || !(value > 0)}>{busy ? <LoaderCircle className="spin" size={15} /> : <Wrench size={15} />} {t("Plan")}</button></>}>
    <p className="muted">{t("While it lasts, the watch keeps quiet about the apps it covers, and their uptime leaves it out.")}</p>
    <div className="ops-ask">
      <label className="ops-ask-text"><span>{t("What for")}</span><input value={reason} maxLength={300} required onChange={(event) => setReason(event.target.value)} placeholder={t("Historian upgrade")} /></label>
      <label><span>{t("Starts (now when empty)")}</span><input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label><span>{t("Hours (up to 72)")}</span><input inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value)} /></label>
      <fieldset className="ops-ask-text ops-window-apps"><legend>{t("Apps (all when none is ticked)")}</legend>
        {services.map((name) => <label key={name} className="act-mine"><input type="checkbox" checked={chosen.includes(name)} onChange={(event) => setChosen((now) => event.target.checked ? [...now, name] : now.filter((item) => item !== name))} /> {name}</label>)}
      </fieldset>
    </div>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
  </Dialog>;
}
