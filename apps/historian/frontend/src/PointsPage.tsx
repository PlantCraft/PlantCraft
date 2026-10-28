import { DataTable, useAssistantPage, type DataColumn } from "@plantcraft/ui";
import { Calculator } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { CalcPointDialog } from "./CalcPoint";
import { RetiredPoints } from "./RetiredPoints";
import { ago, formatBytes, formatCount, formatValue } from "./format";
import { t } from "./i18n";
import { compression } from "./levels";
import { navigate } from "./nav";
import { isWritten, type Me, type Point } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";

export const STATUS_LABELS: Record<string, string> = {
  ok: "Collecting", uncertain: "Uncertain value", substituted: "Substituted value", bad: "Bad value", disconnected: "Disconnected", waiting: "Waiting", disabled: "Disabled",
};
// Where a point's history comes from (docs/data-layer.md).
export const MODE_LABELS: Record<string, string> = {
  source: "Read from the source", archive: "Archived here", both: "Source and archive",
};
/** A point's status as said: an imported or app-written point that is fine is not "collecting". */
export function statusLabel(row: Pick<Point, "status" | "source_kind">): string {
  if (row.status === "ok" && row.source_kind === "import") return t("Imported");
  if (row.status === "ok" && isWritten(row.source_kind)) return t("Written by its app");
  return t(STATUS_LABELS[row.status] ?? row.status);
}
const ORDER = ["disconnected", "bad", "uncertain", "substituted", "waiting", "ok", "disabled"];

/** The page of a point, by its signal id (`<source id>:<tag>`). */
export const pointPath = (signal: string) => `/points/${encodeURIComponent(signal)}`;


/** The plant's own points first, then the series apps write (source `app-<app>`), each by tag. */
export function plantFirst(a: { source_id: string; signal: string }, b: { source_id: string; signal: string }) {
  const derived = (row: { source_id: string }) => (row.source_id.startsWith("app-") ? 1 : 0);
  return derived(a) - derived(b) || a.signal.localeCompare(b.signal);
}

/** What kind of signal a row is, for the Signals table's "Type" filter: the plant's own, a
 * calculated one, an imported file's, or one an app or PlantCraft writes. */
export function signalType(row: Pick<Point, "source_kind">): string {
  if (row.source_kind === "calc") return t("Calculated");
  if (row.source_kind === "import") return t("Imported");
  if (row.source_kind === "derived") return t("Written by an app");
  if (row.source_kind === "system") return t("Written by PlantCraft");
  return t("Read from the plant");
}

const STATUS_RANK = Object.fromEntries(ORDER.map((key, index) => [key, index]));

/** The columns of a table of points (Points, a source's page): each sorts. */
export function pointColumns(): DataColumn<Point>[] {
  return [
    { key: "tag", label: t("Tag"), sort: (row) => row.tag, render: (row) => <><Link to={pointPath(row.signal)} className="pc-mono strong">{row.tag}</Link><small className="pc-mono">{row.source_id}</small><small>{row.description || row.name}</small></> },
    { key: "value", label: t("Value"), numeric: true, sort: (row) => (typeof row.value === "number" ? row.value : null), render: (row) => <>{formatValue(row.value, row.unit)}<small>{ago(row.at)}</small></> },
    { key: "status", label: t("Status"), sort: (row) => STATUS_RANK[row.status] ?? 99, render: (row) => <><Pill status={row.status} label={statusLabel(row)} />{row.detail && <small className="clamp">{row.detail}</small>}</> },
    { key: "mode", label: t("Mode"), sort: (row) => t(MODE_LABELS[row.mode] ?? row.mode), filter: { value: (row) => t(MODE_LABELS[row.mode] ?? row.mode) }, render: (row) => <>{t(MODE_LABELS[row.mode] ?? row.mode)}<small>{row.own_mode ? t("set on the signal") : t("source default")}</small></> },
    { key: "scan", label: t("Scan and deviation"), numeric: true, sort: (row) => (isWritten(row.source_kind) ? null : row.scan_seconds), filter: { value: signalType, label: t("Type") }, render: (row) => <>{row.source_kind === "system" ? t("Written by PlantCraft") : row.source_kind === "derived" ? t("Written by the app") : row.source_kind === "calc" ? t("Calculated every {scan} s", { scan: row.scan_seconds }) : t("{scan} s", { scan: row.scan_seconds })}<small>{compression(row)}</small></> },
    { key: "stored", label: t("Archived"), numeric: true, sort: (row) => row.stored_values, render: (row) => <>{formatCount(row.stored_values)}<small>{t("{count} a day", { count: formatCount(row.stored_day) })} · {formatBytes(row.stored_bytes)}</small></> },
    { key: "ratio", label: t("Compression"), numeric: true, sort: (row) => (row.archived ? row.reads / row.archived : null), render: (row) => (row.archived ? `${(row.reads / row.archived).toFixed(1)} : 1` : "—") },
  ];
}

export function PointsPage({ me }: { me: Me }) {
  const [rows, setRows] = useState<Point[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  // The source in the address (`/points?source=plantcraft`): a source's page links here.
  const [source] = useState(() => new URLSearchParams(window.location.search).get("source") ?? "");
  const [calculating, setCalculating] = useState(false);
  // The Historian's works here (app.toml): which points need attention.
  useAssistantPage({ place: t("Historian › Signals"), page: "histcraft:points", facts: { points: rows?.length ?? 0, source },
    view: { filter, attention: (rows ?? []).filter((item) => item.status !== "ok").slice(0, 30).map((item) => `${item.signal} ${item.status}${item.detail ? `: ${item.detail.slice(0, 80)}` : ""}`) } });

  useEffect(() => {
    const load = () => api.points().then((answer) => { setRows(answer); setError(""); }).catch((err: Error) => setError(err.message));
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const counts = useMemo(() => {
    const found: Record<string, number> = {};
    (rows ?? []).forEach((row) => { found[row.status] = (found[row.status] ?? 0) + 1; });
    return found;
  }, [rows]);
  const shown = useMemo(() => (rows ?? [])
    .filter((row) => !filter || row.status === filter)
    .sort(plantFirst), [rows, filter]);
  // Filtered by source too, here: the source is in the tag's cell.
  const columns = useMemo(() => pointColumns().map((column) => (column.key === "tag" ? { ...column, filter: { value: (row: Point) => row.source_id, label: t("Source") } } : column)), []);

  if (!rows && error) return <ErrorBox text={error} />;
  if (!rows) return <Loading />;
  return <>
    <Heading
      eyebrow={t("Historian")}
      title={t("Signals")}
      detail={t("Every value Historian archives: where it is read, how often, and how it is compressed.")}
      actions={<>
        {me.can_edit && <button className="button button-primary" onClick={() => setCalculating(true)}><Calculator size={16} />{t("Add calculated signal")}</button>}
      </>}
    />
    {error && <ErrorBox text={error} />}
    {calculating && <CalcPointDialog onClose={() => setCalculating(false)} />}
    <div className="kpis">
      {ORDER.filter((key) => counts[key]).map((key) => <button key={key} className={`kpi ${filter === key ? "kpi-on" : ""}`} onClick={() => setFilter(filter === key ? "" : key)}>
        <Pill status={key} label={t(STATUS_LABELS[key] ?? key)} /><b className="pc-num">{counts[key]}</b>
      </button>)}
    </div>
    {rows.length === 0
      ? <div className="panel empty"><h2>{t("No signals yet")}</h2><p>{t("Open a source, browse it and pick the variables to archive.")}</p></div>
      : <DataTable
        rows={shown}
        rowKey={(row) => row.signal}
        label={t("Signals")}
        searchText={(row) => `${row.signal} ${row.name} ${row.description} ${row.address}`}
        searchPlaceholder={t("Search tag, source, name or address")}
        initialFilters={source ? { tag: [source] } : undefined}
        onRowClick={(row) => navigate(pointPath(row.signal))}
        empty={t("No signal matches the filters.")}
        columns={columns}
      />}
    {me.is_admin && <RetiredPoints />}
  </>;
}
