/**
 * A source's page: what it is, how it is read, the defaults it gives its points, and the points.
 * Every source has one, the series an app writes too ("a button to understand
 * the other sources and what their points are").
 */
import { DataTable, useSuiteApps } from "@plantcraft/ui";
import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { navigate } from "./nav";
import { ago, formatBytes, formatCount } from "./format";
import { MODE_LABELS, pointColumns, pointPath } from "./PointsPage";
import { appOfSource, Connection, KIND_ABOUT, KINDS, SourceActions, sourceName, useSourceActions } from "./SourcesPage";
import { isWritten, type Me, type Point, type Settings, type Source } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

/** A source's setting in effect: its own, else the general one. */
function inEffect(own: number | null, general: number | undefined, unit: string): string {
  if (own === 0 && unit === "days") return t("Forever, set on this source");
  if (own !== null && own !== undefined) return t("{value} {unit}, set on this source", { value: own, unit: t(unit) });
  return general === undefined ? t("From general settings") : t("{value} {unit}, from general settings", { value: general, unit: t(unit) });
}

/** What the archive holds of a source's points, summed from the points' own counts (no query of
 * its own: the collector keeps the counts, a page never scans the archive). */
function SourceArchive({ points, reads }: { points: Point[]; reads: boolean }) {
  const sum = (pick: (point: Point) => number) => points.reduce((total, point) => total + (pick(point) || 0), 0);
  const read = sum((point) => point.reads);
  const archived = sum((point) => point.archived);
  const latest = Math.max(...points.map((point) => point.at ?? 0));
  const failing = points.filter((point) => point.status === "error").length;
  const busiest = [...points].sort((a, b) => b.stored_day - a.stored_day)[0];
  return <div className="pc-grid">
    <div className="panel kpi-card"><span className="pc-overline">{t("Archived in the last 24 h")}</span><b className="pc-num">{t("{count} values", { count: formatCount(sum((point) => point.stored_day)) })}</b><small>{busiest && busiest.stored_day > 0 ? t("Most: {tag}, {count}", { tag: busiest.tag, count: formatCount(busiest.stored_day) }) : t("Nothing archived in the last 24 h")}</small></div>
    <div className="panel kpi-card"><span className="pc-overline">{t("Archive")}</span><b className="pc-num">{formatBytes(sum((point) => point.stored_bytes))}</b><small>{t("{count} values in all", { count: formatCount(sum((point) => point.stored_values)) })}</small></div>
    {reads && <div className="panel kpi-card"><span className="pc-overline">{t("Compression")}</span><b className="pc-num">{archived ? `${(read / archived).toFixed(1)} : 1` : "—"}</b><small>{t("Values read per value archived, since the collector started")}</small></div>}
    <div className="panel kpi-card"><span className="pc-overline">{t("Latest value")}</span><b>{latest ? ago(latest) : "—"}</b><small>{failing === 1 ? t("1 signal with errors") : failing ? t("{count} signals with errors", { count: failing }) : t("No signal with errors")}</small></div>
  </div>;
}

export function SourcePage({ sourceId, me }: { sourceId: string; me: Me }) {
  const [source, setSource] = useState<Source | null>(null);
  const [points, setPoints] = useState<Point[] | null>(null);
  const [general, setGeneral] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const apps = useSuiteApps();
  const load = () => Promise.all([api.sources(), api.points("", sourceId)]).then(([sources, found]) => {
    const match = sources.find((item) => item.id === sourceId);
    if (!match) { setError(t("No source {id}.", { id: sourceId })); return; }
    setSource(match); setPoints(found); setError("");
  }).catch((err: Error) => setError(err.message));
  const actions = useSourceActions(load, () => navigate("/sources"));
  useEffect(() => {
    void load();
    api.settings().then(setGeneral).catch(() => undefined);
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [sourceId]);

  if (!source && error) return <ErrorBox text={error} />;
  if (!source || !points) return <Loading />;
  const derived = isWritten(source.kind);
  const system = source.kind === "system";
  const app = source.kind === "derived" ? apps.find((item) => item.id === appOfSource(source.id)) : undefined;
  const about = KIND_ABOUT[source.kind] ?? KIND_ABOUT.opcua;
  return <>
    <div className="breadcrumb">{source.kind === "import" ? <Link to="/imports">{t("Imports")}</Link> : <Link to="/sources">{t("Sources")}</Link>} / <span>{sourceName(source)}</span></div>
    <Heading
      eyebrow={t(KINDS[source.kind] ?? source.kind)}
      title={sourceName(source)}
      detail={system ? t(about.about) : derived ? t("The series {app} calculates and writes here: every app and every trend reads them like any other signal. They are changed in {app}, not here.", { app: sourceName(source) }) : t(about.about)}
      actions={<>
        <SourceActions source={source} me={me} actions={actions} />
        {app && <a className="button button-secondary" href={app.url}>{t("Open {app}", { app: sourceName(source) })}<ArrowRight size={15} /></a>}
      </>}
    />
    {actions.notices}
    {error && <ErrorBox text={error} />}
    <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Reads from")}</span><b className="pc-mono source-endpoint">{derived ? source.id : source.kind === "calc" ? t("Formulas") : source.kind === "import" ? String(source.options.file_name ?? "—") : source.endpoint || "—"}</b><small>{source.username ? t("as {user}", { user: source.username }) : source.kind === "calc" ? t("Evaluated every scan from archived signals") : source.kind === "import" ? t("Imported by {user}", { user: String(source.options.imported_by ?? "—") }) : system ? t("Written by PlantCraft every minute") : derived ? t("Written by the app on each new value") : t("Read-only connection")}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Connection")}</span><span><Connection source={source} /></span></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("History")}</span><b>{t(MODE_LABELS[source.mode] ?? source.mode)}</b><small>{source.mode === source.default_mode ? t("default for this type") : t("set on the source")}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Signals")}</span><b className="pc-num">{points.length}</b><small>{t("Kept {retention}", { retention: inEffect(source.retention_days, general?.retention_days, "days") })}</small></div>
    </div>
    {points.length > 0 && <SourceArchive points={points} reads={!derived && source.kind !== "import"} />}
    {!derived && source.kind !== "import" && <div className="panel">
      <div className="panel-header"><div><h2>{t("Signal defaults for this source")}</h2><p>{t("A signal's own setting takes precedence. Empty fields use the general settings.")}</p></div></div>
      <dl className="settings-list">
        <dt>{t("Retention")}</dt><dd>{inEffect(source.retention_days, general?.retention_days, "days")}</dd>
        <dt>{t("Scan period")}</dt><dd>{inEffect(source.default_scan_seconds, general?.default_scan_seconds, "s")}</dd>
        <dt>{t("Deviation")}</dt><dd>{inEffect(source.default_deviation_percent, general?.default_deviation_percent, "% of span")}</dd>
        <dt>{t("Longest interval between archived values")}</dt><dd>{inEffect(source.default_max_seconds, general?.default_max_seconds, "s")}</dd>
      </dl>
    </div>}
    <h2 className="section-title">{t("Signals from this source")}</h2>
    {points.length === 0
      ? <div className="panel empty"><p>{derived ? t("No data received from this app.") : t("No signals. Browse the source to add signals.")}</p></div>
      : <DataTable rows={points} rowKey={(row) => row.signal} label={t("Signals from this source")} columns={pointColumns()} onRowClick={(row) => navigate(pointPath(row.signal))}
        searchText={(row) => `${row.signal} ${row.name} ${row.description} ${row.address}`} searchPlaceholder={t("Search tag, name or address")} />}
    {actions.dialogs}
  </>;
}
