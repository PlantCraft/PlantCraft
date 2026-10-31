/** Setup › Audit log (administrators): who changed what in PlantCraft and in every app, and every
 * sign-in, failed sign-in and sign-out (IEC 62443-4-2 CR 2.8). Read only; the same rows download
 * as a CSV for a review. Laid out like a log explorer (after Grafana's Explore):
 * the period and quick filters on top, the rows per hour or day as a chart (a click on a bar
 * zooms in), the table, and every row's full detail with its values to filter by. */
import { DataTable, Heading, PeriodPicker, localOf, periodRange, type TimePeriod } from "@plantcraft/ui";
import { AlertTriangle, Download, Filter, LoaderCircle, RefreshCw, ScrollText, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { requestJson } from "./api";
import { locale, t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import "./access.css";

export type AuditRow = { audit_id: number; at: string; username: string; app_id: string | null; action: string; subject: string; detail: unknown };
type AuditPage = { rows: AuditRow[]; limit: number; truncated: boolean };
export type AuditBucket = { at: string; total: number; failed: number };
type AuditVolume = { bucket: "hour" | "day"; buckets: AuditBucket[]; people: { username: string; count: number }[]; apps: { app_id: string | null; count: number }[] };
export type AuditFilters = { period: TimePeriod; kind: string; username: string; appId: string };

const WINDOWS = ["1h", "24h", "7d", "30d", "90d", "365d"];
const PAGE = 500;
export const QUICK = [
  { value: "", label: () => t("Everything") },
  { value: "changes", label: () => t("Changes") },
  { value: "sign_ins", label: () => t("Sign-ins") },
  { value: "failed", label: () => t("Failed sign-ins") },
];
// Shown with a warning mark: failed or blocked sign-ins, and the assistant reading a lot for one
// person (its daily limit reached, many signals in one answer: B13, 2026-10-31).
const FAILED = new Set([
  "session.sign_in_failed",
  "session.sign_in_blocked",
  "assistant.read_limit",
  "assistant.bulk_read",
]);

function Link({ to, children }: { to: string; children: ReactNode }) {
  return <a href={to} onClick={(event) => { event.preventDefault(); navigate(to); }}>{children}</a>;
}

function when(value: string, seconds = true) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined }).format(date);
}

/** The action in words for the sign-in rows; any other action as the app wrote it. */
export function actionLabel(action: string): string {
  const words: Record<string, string> = {
    "session.sign_in": t("Signed in"),
    "session.sign_in_failed": t("Sign-in failed"),
    "session.sign_in_blocked": t("Sign-in blocked (too many attempts)"),
    "session.sign_out": t("Signed out"),
    "assistant.read_limit": t("Assistant read limit reached (possible extraction)"),
    "assistant.bulk_read": t("Assistant read many signals at once (possible extraction)"),
  };
  return words[action] ?? action;
}

/** The detail in one line: "address 10.0.0.5 · method ldap", or the JSON. */
export function detailText(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail !== "object" || Array.isArray(detail)) return JSON.stringify(detail);
  return Object.entries(detail as Record<string, unknown>)
    .map(([key, value]) => `${key} ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

/** What the page asks the server for: the period as start and end, and the filters. */
export function auditQuery(filters: AuditFilters, now = Date.now()): string {
  const range = periodRange(filters.period, now);
  const params = new URLSearchParams();
  if (range.start) params.set("start", range.start);
  if (range.end && filters.period.window === "fixed") params.set("end", range.end);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.username) params.set("username", filters.username);
  if (filters.appId) params.set("app_id", filters.appId);
  return params.toString();
}

/** The period one bar of the chart covers, to zoom in on it. */
export function bucketPeriod(bucket: AuditBucket, size: "hour" | "day"): TimePeriod {
  const start = new Date(bucket.at).getTime();
  const end = start + (size === "hour" ? 3_600_000 : 86_400_000);
  return { window: "fixed", from: localOf(new Date(start).toISOString()), to: localOf(new Date(end).toISOString()) };
}

/** Every hour or day of the period, the empty ones too, so the bars sit on a real time axis. */
export function fillBuckets(found: AuditBucket[], size: "hour" | "day", start: string, end: string): AuditBucket[] {
  const step = size === "hour" ? 3_600_000 : 86_400_000;
  const from = Math.floor(new Date(start).getTime() / step) * step;
  const until = new Date(end).getTime();
  if (!Number.isFinite(from) || !Number.isFinite(until) || until < from || (until - from) / step > 400) return found;
  const byTime = new Map(found.map((item) => [new Date(item.at).getTime(), item]));
  const all: AuditBucket[] = [];
  for (let at = from; at <= until; at += step) all.push(byTime.get(at) ?? { at: new Date(at).toISOString(), total: 0, failed: 0 });
  return all;
}

function VolumeChart({ volume, range, onZoom }: { volume: AuditVolume; range: { start: string; end: string }; onZoom: (bucket: AuditBucket) => void }) {
  const items = volume.buckets.length ? fillBuckets(volume.buckets, volume.bucket, range.start, range.end || new Date().toISOString()) : [];
  const top = Math.max(1, ...items.map((item) => item.total));
  const width = 1000, height = 120, gap = items.length > 60 ? 1 : 3;
  const bar = items.length ? width / items.length : width;
  const label = (item: AuditBucket) => `${volume.bucket === "hour" ? when(item.at, false) : new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric" }).format(new Date(item.at))}: ${t("{count} rows", { count: item.total })}${item.failed ? `, ${t("{count} failed sign-ins", { count: item.failed })}` : ""}`;
  return <figure className="audit-volume">
    <figcaption>
      <span>{volume.bucket === "hour" ? t("Rows per hour") : t("Rows per day")}</span>
      <span className="audit-legend"><i className="audit-key" /> {t("Rows")} <i className="audit-key audit-key-failed" /> {t("Failed sign-ins")}</span>
    </figcaption>
    {items.length ? <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={t("Rows over time")}>
      {items.map((item, index) => {
        const total = (item.total / top) * (height - 4);
        const failed = (item.failed / top) * (height - 4);
        const x = index * bar + gap / 2, w = Math.max(1, bar - gap);
        return <g key={item.at} className="audit-bar" onClick={() => item.total && onZoom(item)}>
          <title>{label(item)}</title>
          <rect x={index * bar} y={0} width={bar} height={height} className="audit-bar-hit" />
          <rect x={x} y={height - total} width={w} height={total - failed} className="audit-bar-total" />
          {item.failed > 0 && <rect x={x} y={height - failed} width={w} height={failed} className="audit-bar-failed" />}
        </g>;
      })}
    </svg> : <p className="muted">{t("Nothing recorded in this period.")}</p>}
    {items.length > 0 && <div className="audit-axis"><span>{when(items[0].at, false)}</span><span>{t("Click a bar to look closer")}</span><span>{when(items[items.length - 1].at, false)}</span></div>}
  </figure>;
}

function DetailDrawer({ row, onClose, onFilter }: { row: AuditRow; onClose: () => void; onFilter: (change: Partial<AuditFilters>) => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const detail = row.detail && typeof row.detail === "object" && !Array.isArray(row.detail) ? Object.entries(row.detail as Record<string, unknown>) : null;
  const value = (item: unknown) => (typeof item === "string" ? item : JSON.stringify(item, null, 2));
  return <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <aside className="action-drawer audit-drawer" role="dialog" aria-label={t("Audit row {id}", { id: row.audit_id })}>
      <header><div><span className="eyebrow"><ScrollText size={13} /> {t("Audit row {id}", { id: row.audit_id })}</span><h2>{actionLabel(row.action)}</h2></div>
        <button type="button" className="button button-ghost button-icon" onClick={onClose} aria-label={t("Close")}><X /></button></header>
      <dl className="audit-facts">
        <div><dt>{t("When")}</dt><dd>{when(row.at)}<small className="muted">{row.at} (UTC)</small></dd></div>
        <div><dt>{t("Who")}</dt><dd><strong>{row.username}</strong><button type="button" className="link-button" onClick={() => onFilter({ username: row.username })}><Filter size={12} /> {t("Only this person")}</button></dd></div>
        <div><dt>{t("App")}</dt><dd>{row.app_id ?? "—"}{row.app_id && <button type="button" className="link-button" onClick={() => onFilter({ appId: row.app_id ?? "" })}><Filter size={12} /> {t("Only this app")}</button>}</dd></div>
        <div><dt>{t("Action")}</dt><dd><code>{row.action}</code></dd></div>
        <div><dt>{t("Target")}</dt><dd><code>{row.subject || "—"}</code></dd></div>
      </dl>
      <h3 className="audit-detail-title">{t("Detail")}</h3>
      {detail ? <dl className="audit-facts">{detail.map(([key, item]) => <div key={key}><dt>{key}</dt><dd><pre>{value(item)}</pre></dd></div>)}</dl>
        : row.detail == null ? <p className="muted">{t("No detail.")}</p> : <pre className="audit-json">{value(row.detail)}</pre>}
    </aside>
  </div>;
}

export default function AuditLogPage() {
  const isAdmin = useIsAdmin();
  const [filters, setFilters] = useState<AuditFilters>({ period: { window: "7d", from: "", to: "" }, kind: "", username: "", appId: "" });
  const [data, setData] = useState<AuditPage | null>(null);
  const [volume, setVolume] = useState<AuditVolume | null>(null);
  const [error, setError] = useState("");
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState<AuditRow | null>(null);
  const query = useMemo(() => auditQuery(filters), [filters]);
  const load = useCallback(() => {
    setError("");
    const failed = (err: unknown) => setError(err instanceof Error ? err.message : t("Couldn't complete the operation."));
    requestJson<AuditVolume>(`/api/audit/volume?${query}`).then(setVolume).catch(failed);
    return requestJson<AuditPage>(`/api/audit?${query}&limit=${PAGE}`).then(setData).catch(failed);
  }, [query]);
  useEffect(() => { void load(); }, [load]);
  const change = (next: Partial<AuditFilters>) => { setFilters((current) => ({ ...current, ...next })); setOpen(null); };
  async function loadMore() {
    if (!data?.rows.length) return;
    setMore(true);
    try {
      const page = await requestJson<AuditPage>(`/api/audit?${query}&limit=${PAGE}&before_id=${data.rows[data.rows.length - 1].audit_id}`);
      setData({ ...page, rows: [...data.rows, ...page.rows] });
    } catch (err) { setError(err instanceof Error ? err.message : t("Couldn't complete the operation.")); }
    setMore(false);
  }
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins read the audit log.")}</span></div>;
  const filtered = Boolean(filters.kind || filters.username || filters.appId || filters.period.window === "fixed");

  return <>
    <Heading eyebrow={<><ScrollText size={14} /> {t("Administration")} · <Link to="/setup">{t("Settings")}</Link></>} title={t("Audit log")}
      detail={t("Who changed what, in PlantCraft and in every app, and every sign-in, failed sign-in and sign-out, with the address it came from. Rows are only added: nobody can edit or remove them.")}
      actions={<>
        <button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => void load()}><RefreshCw /></button>
        <a className="button button-secondary" href={`/api/audit.csv?${query}`} download><Download /> {t("Download CSV")}</a>
      </>} />
    <section className="panel audit-filters" aria-label={t("Filters")}>
      <PeriodPicker value={filters.period} windows={WINDOWS} onChange={(period) => change({ period })} />
      <div className="segmented" role="group" aria-label={t("Show")}>
        {QUICK.map((item) => <button key={item.value} type="button" className={filters.kind === item.value ? "on" : undefined} aria-pressed={filters.kind === item.value} onClick={() => change({ kind: item.value })}>{item.label()}</button>)}
      </div>
      <label className="audit-field">{t("Person")}<select id="audit-person" value={filters.username} onChange={(event) => change({ username: event.target.value })}>
        <option value="">{t("Everyone")}</option>
        {filters.username && !volume?.people.some((item) => item.username === filters.username) && <option value={filters.username}>{filters.username}</option>}
        {volume?.people.map((item) => <option key={item.username} value={item.username}>{item.username} ({item.count})</option>)}
      </select></label>
      <label className="audit-field">{t("App")}<select id="audit-app" value={filters.appId} onChange={(event) => change({ appId: event.target.value })}>
        <option value="">{t("Every app")}</option>
        {filters.appId && !volume?.apps.some((item) => item.app_id === filters.appId) && <option value={filters.appId}>{filters.appId}</option>}
        {volume?.apps.filter((item) => item.app_id).map((item) => <option key={item.app_id} value={item.app_id ?? ""}>{item.app_id} ({item.count})</option>)}
      </select></label>
      {filtered && <button type="button" className="button button-ghost button-small" onClick={() => change({ kind: "", username: "", appId: "", period: { window: "7d", from: "", to: "" } })}><X /> {t("Clear filters")}</button>}
    </section>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {volume && <section className="panel"><VolumeChart volume={volume} range={periodRange(filters.period)} onZoom={(bucket) => change({ period: bucketPeriod(bucket, volume.bucket) })} /></section>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {data && <section className="panel" aria-label={t("Audit log")}>
      <DataTable rows={data.rows} rowKey={(row) => String(row.audit_id)} label={t("Audit log")} initialSort={{ key: "at", descending: true }}
        searchText={(row) => `${row.username} ${row.action} ${actionLabel(row.action)} ${row.subject} ${detailText(row.detail)}`} searchPlaceholder={t("Search person, action, target or address")}
        empty={t("Nothing recorded in this period.")} onRowClick={setOpen}
        rowClassName={(row) => (FAILED.has(row.action) ? "audit-failed" : undefined)}
        columns={[
          { key: "at", label: t("When"), sort: (row) => row.audit_id, render: (row) => <span className="nowrap">{when(row.at)}</span> },
          { key: "who", label: t("Who"), sort: (row) => row.username, render: (row) => <strong>{row.username}</strong> },
          { key: "app", label: t("App"), sort: (row) => row.app_id ?? "", render: (row) => row.app_id ?? "—" },
          { key: "action", label: t("Action"), sort: (row) => row.action, filter: { value: (row) => actionLabel(row.action) }, render: (row) => FAILED.has(row.action) ? <span className="audit-bad"><AlertTriangle size={13} /> {actionLabel(row.action)}</span> : actionLabel(row.action) },
          { key: "subject", label: t("Target"), sort: (row) => row.subject, render: (row) => <code>{row.subject || "—"}</code> },
          { key: "detail", label: t("Detail"), render: (row) => <span className="muted clamp">{detailText(row.detail)}</span> },
        ]} />
      {data.truncated && <div className="more"><button type="button" className="button button-secondary" disabled={more} onClick={() => void loadMore()}>{more && <LoaderCircle className="spin" />} {t("Load older rows")}</button></div>}
    </section>}
    {open && <DetailDrawer row={open} onClose={() => setOpen(null)} onFilter={change} />}
  </>;
}
