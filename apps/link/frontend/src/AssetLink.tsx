import { DataTable, type DataColumn } from "@plantcraft/ui";
import { ArrowUpRight, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { navigate } from "./nav";
import type { AssetLink, AssetRun, Me } from "./types";
import { signalLabel, signalStatus } from "./signalStatus";
import { resultLabel, suiteLabel } from "./status";
import { ErrorBox, Heading, Link, Loading, Pill, Quality, signalPath } from "./ui";
import { RESULT_COLUMNS, resultsPath } from "./ResultsPage";

// On an asset, each result says what it judged (the loop, or one of its signals) instead of the type.
const ASSET_RESULT_COLUMNS = RESULT_COLUMNS.filter((column) => column.key !== "type").map((column) => (column.key === "name" ? { ...column, label: t("On") } : column));

/** PlantCraft's page for an asset (`/assets/<id>`); the id is opaque, only encoded. */
export function processCraftAssetUrl(me: Me, assetId: string) {
  return `${(me.processcraft_url || "/").replace(/\/$/, "")}/assets/${encodeURIComponent(assetId)}`;
}

/** PlantCraft's action form, filled in for an asset (`/actions?new=1&ref=asset:<id>&title=...`). */
export function processCraftActionUrl(me: Me, assetId: string, title: string) {
  const query = new URLSearchParams({ new: "1", ref: `asset:${assetId}`, title });
  return `${(me.processcraft_url || "/").replace(/\/$/, "")}/actions?${query.toString()}`;
}

/** `<prefix>assets/<id>`, the suite's deep link: opens the loop of that asset, or says why not. */
type LinkSignal = NonNullable<AssetLink["signals"]>[number];
const SIGNAL_COLUMNS: DataColumn<LinkSignal>[] = [
  { key: "role", label: t("Role"), sort: (item) => item.role, className: "pc-mono", render: (item) => item.role.toUpperCase() },
  { key: "signal", label: t("Signal"), sort: (item) => item.signal, render: (item) => <Link to={signalPath(item.signal)} className="pc-mono strong">{item.signal}</Link> },
  { key: "status", label: t("Status"), sort: (item) => signalLabel(item.status), render: (item) => <Pill status={signalStatus(item.status)} label={signalLabel(item.status)} />, filter: { value: (item) => signalLabel(item.status) } },
  { key: "quality", label: t("Quality"), numeric: true, sort: (item) => item.quality, render: (item) => <Quality value={item.quality} status={item.status} /> },
  { key: "message", label: t("Why"), className: "hide-narrow", render: (item) => <small>{item.message || "—"}</small> },
];

/** `/assets/<id>`: the asset's page in Link, the deep link every app of the suite uses. The latest
 * result of every algorithm that runs on it (its loop's algorithm, Signal quality on its signals,
 * the algorithms on assets that name it), each opening the series behind it; the quality of its
 * signals; and the latest word of each algorithm on assets (owner, 2026-10-23). */
export function AssetLinkPage({ assetId, me }: { assetId: string; me: Me }) {
  const [link, setLink] = useState<AssetLink | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.assetLink(assetId).then(setLink).catch((err: Error) => setError(err.message)); }, [assetId]);
  if (error) return <ErrorBox text={error} />;
  if (!link) return <Loading />;
  const open = <a className="button button-secondary" href={processCraftAssetUrl(me, assetId)}>{t("Open the asset in PlantCraft")}<ArrowUpRight size={15} /></a>;
  if (!link.covered) return <>
    <Heading eyebrow={t("Asset")} title={assetId} />
    <section className="panel asset-not-covered" role="status">
      <h2>{t("No result yet")}</h2>
      <p>{link.reason}</p>
      <div className="heading-actions">
        {open}
        <Link to="/schedules/new" className="button button-secondary">{t("Monitor with an algorithm")}</Link>
        <Link to={resultsPath({})} className="button button-secondary">{t("Every result")}</Link>
      </div>
    </section>
  </>;
  const results = link.results ?? [];
  return <>
    <nav className="breadcrumb"><Link to={resultsPath({})}>{t("Results")}</Link><ChevronRight size={12} /><span className="pc-mono">{link.name ?? assetId}</span></nav>
    <Heading eyebrow={t("Asset")} title={link.name ?? assetId} detail={link.quality?.summary}
      actions={<>{link.loop_id && <Link to={`/loops/${encodeURIComponent(link.loop_id)}`} className="button button-secondary">{t("Loop analysis")}</Link>}{open}</>} />
    <h2 className="section-title">{t("Results on this asset")}</h2>
    {results.length
      ? <DataTable rows={results} columns={ASSET_RESULT_COLUMNS} rowKey={(row) => `${row.kind}:${row.id}`} onRowClick={(row) => navigate(row.path)} label={t("Results on this asset")} />
      : <div className="panel empty"><p>{t("No algorithm has a result on it yet.")}</p></div>}
    {link.quality && <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Worst of its signals")}</span><Pill status={link.quality.status} label={suiteLabel(link.quality.status)} /><Quality value={link.quality.score} /></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Usable for analysis")}</span><b>{link.quality.usable === null ? "—" : link.quality.usable ? t("Yes") : t("No")}</b><small>{t("What Analytics publishes on the asset in PlantCraft.")}</small></div>
    </div>}
    {!!link.signals?.length && <>
      <h2 className="section-title">{t("Its signals")}</h2>
      <DataTable rows={link.signals} columns={SIGNAL_COLUMNS} rowKey={(item) => `${item.role}-${item.signal}`} initialSort={{ key: "role", descending: false }} label={t("Signals")} />
    </>}
  </>;
}
