/** Operations › Logs: every server of the suite in one list, newest first, with the filters the
 * servers apply themselves (period, lowest level, text, request) and the messages that come back
 * most often. A row opens the whole record; "Same request" follows one request through every app. */
import { AlertTriangle, Download, LoaderCircle, RefreshCw, Search, X } from "lucide-react";
import { type DataColumn, DataTable, Dialog, formatDate, Heading, saveFile } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { t } from "./i18n";
import { LOG_LEVELS, operationsApi, type LogRecord, type LogsAnswer, type LogsQuery } from "./operationsApi";
import "./apps.css";
import "./operations.css";

const PERIODS: Array<{ hours: number; label: string }> = [
  { hours: 1, label: t("Last hour") },
  { hours: 6, label: t("Last 6 hours") },
  { hours: 24, label: t("Last 24 hours") },
  { hours: 24 * 7, label: t("Last 7 days") },
];
const LEVEL_LABELS: Record<string, string> = {
  DEBUG: t("Debug and above"),
  INFO: t("Info and above"),
  WARNING: t("Warnings and errors"),
  ERROR: t("Errors only"),
  CRITICAL: t("Critical only"),
};
const SERVICE_NAMES: Record<string, string> = {
  processcraft: "PlantCraft",
  histcraft: "Historian",
  linkcraft: "Analytics",
  dashcraft: "View",
  alarmcraft: "Alarms",
  modelcraft: "Models",
  doccraft: "Documents",
  simcraft: "Simulator",
};
const LIMIT = 500;
// Log lines a second apart must read apart: the time with seconds.
const SECONDS: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" };
const SHOWN_FIELDS = new Set(["time", "level", "service", "app", "logger", "message", "request_id", "error", "version"]);

export function serviceName(service: string): string {
  return SERVICE_NAMES[service] ?? service;
}

export function levelClass(level: string): string {
  if (level === "ERROR" || level === "CRITICAL") return "ops-level ops-level-error";
  if (level === "WARNING") return "ops-level ops-level-warning";
  return "ops-level";
}

/** The records as CSV (time in UTC, as written), for a ticket or an email to support. */
export function logsCsv(records: LogRecord[]): string {
  const cell = (value: unknown) => {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const head = ["time", "service", "level", "logger", "message", "request_id", "error"];
  return [head.join(","), ...records.map((item) => head.map((key) => cell(item[key])).join(","))].join("\n") + "\n";
}

const COLUMNS: DataColumn<LogRecord>[] = [
  { key: "time", label: t("Time"), sort: (item) => item.time, render: (item) => <span className="ops-time">{formatDate(item.time, SECONDS)}</span> },
  { key: "service", label: t("App"), sort: (item) => serviceName(item.service), filter: { value: (item) => serviceName(item.service) }, render: (item) => serviceName(item.service) },
  { key: "level", label: t("Level"), sort: (item) => LOG_LEVELS.indexOf(item.level as (typeof LOG_LEVELS)[number]), filter: { value: (item) => item.level }, render: (item) => <span className={levelClass(item.level)}>{item.level}</span> },
  { key: "message", label: t("Message"), render: (item) => <span className="ops-message" title={item.message}>{item.message}{item.error ? <small className="apps-sub">{t("with an error trace")}</small> : null}</span> },
  { key: "request_id", label: t("Request"), phone: "hide", render: (item) => (item.request_id ? <code className="ops-request">{item.request_id.slice(0, 8)}</code> : "—") },
];

export function LogsPage() {
  const [hours, setHours] = useState(6);
  const [level, setLevel] = useState("WARNING");
  const [services, setServices] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [requestId, setRequestId] = useState("");
  const [query, setQuery] = useState<LogsQuery>({ hours: 6, level: "WARNING", limit: LIMIT });
  const [answer, setAnswer] = useState<LogsAnswer | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<LogRecord | null>(null);
  const load = useCallback((next: LogsQuery) => {
    setBusy(true);
    operationsApi.logs(next).then((value) => { setAnswer(value); setError(""); }, (err) => setError(err instanceof Error ? err.message : t("Couldn't load."))).finally(() => setBusy(false));
  }, []);
  useEffect(() => load(query), [load, query]);
  function apply(event?: FormEvent, changes: Partial<LogsQuery> = {}) {
    event?.preventDefault();
    setQuery({ hours, level, services, text, request_id: requestId, limit: LIMIT, ...changes });
  }
  function sameRequest(record: LogRecord) {
    if (!record.request_id) return;
    setRequestId(record.request_id);
    setLevel("DEBUG");
    setServices([]);
    setText("");
    setOpen(null);
    setQuery({ hours: Math.max(hours, 24), level: "DEBUG", request_id: record.request_id, limit: LIMIT });
  }
  function toggleService(service: string) {
    setServices((current) => (current.includes(service) ? current.filter((item) => item !== service) : [...current, service]));
  }
  const records = answer?.records ?? [];
  return <div className="apps-page ops-logs">
    <Heading title={t("Logs")} actions={<>
      <button type="button" className="button button-secondary" disabled={!records.length} onClick={() => saveFile(`plantcraft-logs-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "")}.csv`, logsCsv(records), "text/csv")}><Download size={15} /> {t("Export CSV")}</button>
      <button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => load(query)}><RefreshCw /></button>
    </>} />
    <form className="panel ops-log-filters" onSubmit={(event) => apply(event)} aria-label={t("Filters")}>
      <label><span>{t("Period")}</span>
        <select value={hours} onChange={(event) => setHours(Number(event.target.value))}>{PERIODS.map((item) => <option key={item.hours} value={item.hours}>{item.label}</option>)}</select>
      </label>
      <label><span>{t("Level")}</span>
        <select value={level} onChange={(event) => setLevel(event.target.value)}>{LOG_LEVELS.map((item) => <option key={item} value={item}>{LEVEL_LABELS[item]}</option>)}</select>
      </label>
      <label className="ops-log-text"><span>{t("Text")}</span>
        <input type="search" value={text} maxLength={200} placeholder={t("In the message, the logger or the error")} onChange={(event) => setText(event.target.value)} />
      </label>
      <label><span>{t("Request id")}</span>
        <input type="search" value={requestId} maxLength={64} placeholder={t("All requests")} onChange={(event) => setRequestId(event.target.value)} />
      </label>
      <fieldset className="ops-log-services">
        <legend>{t("Apps")}</legend>
        {(answer?.services ?? ["processcraft"]).map((service) => <label key={service} className={`ops-chip${services.includes(service) ? " ops-chip-on" : ""}`}>
          <input type="checkbox" checked={services.includes(service)} onChange={() => toggleService(service)} /> {serviceName(service)}
        </label>)}
        {services.length > 0 && <button type="button" className="button button-ghost" onClick={() => setServices([])}><X size={14} /> {t("All apps")}</button>}
      </fieldset>
      <button className="button button-primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />} {t("Search")}</button>
    </form>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {answer && answer.missing.length > 0 && <div className="module-state ops-missing"><AlertTriangle size={15} /><span>{t("Not read: {apps}. A server that is down or older than this page does not answer; its logs are on its disk and in the diagnostic bundle.", { apps: answer.missing.map(serviceName).join(", ") })}</span></div>}
    {answer && answer.top.length > 0 && <section className="panel ops-top" aria-labelledby="ops-top-title">
      <h2 id="ops-top-title">{t("Most frequent warnings and errors")}</h2>
      <ul>{answer.top.slice(0, 6).map((item) => <li key={`${item.service}-${item.level}-${item.message}`}>
        <span className="ops-top-count">{item.count}×</span>
        <span className={levelClass(item.level)}>{item.level}</span>
        <span className="ops-top-app">{serviceName(item.service)}</span>
        <button type="button" className="ops-top-message" title={t("Search for it")} onClick={() => { const words = item.message.split("#")[0].trim(); setText(words); apply(undefined, { text: words, services: [item.service] }); setServices([item.service]); }}>{item.message}</button>
      </li>)}</ul>
    </section>}
    <DataTable rows={records} columns={COLUMNS} rowKey={(item) => `${item.service}|${item.time}|${item.logger}|${item.message.slice(0, 60)}`} searchText={(item) => `${item.message} ${item.logger ?? ""} ${item.service}`} searchPlaceholder={t("Filter these records")} onRowClick={setOpen} label={t("Log records")}
      empty={busy ? t("Reading the logs…") : t("No records match these filters.")} />
    {answer?.truncated && <p className="muted">{t("Showing the newest {count} records; narrow the period or the filters to see older ones.", { count: records.length })}</p>}
    {open && <RecordDialog record={open} onClose={() => setOpen(null)} onSameRequest={sameRequest} />}
  </div>;
}

function RecordDialog({ record, onClose, onSameRequest }: { record: LogRecord; onClose: () => void; onSameRequest: (record: LogRecord) => void }) {
  const extra = Object.entries(record).filter(([key]) => !SHOWN_FIELDS.has(key));
  return <Dialog title={`${serviceName(record.service)} · ${record.level}`} onClose={onClose} wide
    footer={<>{record.request_id && <button type="button" className="button button-secondary" onClick={() => onSameRequest(record)}>{t("Same request in every app")}</button>}<button type="button" className="button button-primary" onClick={onClose}>{t("Close")}</button></>}>
    <dl className="ops-record">
      <dt>{t("Time")}</dt><dd>{formatDate(record.time, SECONDS)} <small className="muted">({record.time})</small></dd>
      <dt>{t("Logger")}</dt><dd><code>{record.logger ?? "—"}</code></dd>
      {record.version && <><dt>{t("Version")}</dt><dd>{record.version}</dd></>}
      {record.request_id && <><dt>{t("Request id")}</dt><dd><code>{record.request_id}</code></dd></>}
      {extra.map(([key, value]) => <span key={key} className="ops-record-pair"><dt>{key}</dt><dd><code>{typeof value === "string" ? value : JSON.stringify(value)}</code></dd></span>)}
    </dl>
    <pre className="ops-record-text">{record.message}</pre>
    {record.error && <><h3>{t("Error")}</h3><pre className="ops-record-text ops-record-error">{record.error}</pre></>}
  </Dialog>;
}
