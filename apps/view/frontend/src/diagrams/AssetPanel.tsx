/** The panel a click on a piece of equipment opens beside a process display (owner, 2026-10-27:
 * "no dashboard covers this asset yet" was a dead end): what the asset is, its values on this
 * display, its signals, each a trend away, and the way on to its page in PlantCraft and to the
 * dashboards that show it. It stays on the display, full screen included. */
import { errorMessage as message } from "@plantcraft/ui";
import { ExternalLink, LineChart, LayoutDashboard, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { formatValue } from "../model";
import type { AssetDashboards } from "../types";
import { Link, Loading } from "../ui";
import type { BindingRow } from "./model";

export function AssetPanel({ assetId, name, values, onTrend, onClose }: {
  assetId: string; name: string; values: BindingRow[];
  onTrend: (title: string, signals: string[]) => void; onClose: () => void;
}) {
  const [data, setData] = useState<AssetDashboards | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null); setError("");
    api.assetDashboards(assetId).then(setData).catch((err) => setError(message(err)));
  }, [assetId]);
  useEffect(() => {
    const leave = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    globalThis.addEventListener("keydown", leave);
    return () => globalThis.removeEventListener("keydown", leave);
  }, [onClose]);
  const asset = data?.asset;
  const title = asset?.name || name || assetId;
  const shown = values.filter((row, at) => row.signal && values.findIndex((other) => other.signal === row.signal) === at);
  const signals = Object.entries(asset?.signals ?? {});
  const every = [...new Set([...shown.map((row) => row.signal as string), ...signals.map(([, signal]) => signal)])];
  return <aside className="dg-asset-panel" aria-label={t("Asset {name}", { name: title })} onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
    <header>
      <div><span className="dg-asset-kind">{asset?.kind_label || asset?.kind || t("Asset")}</span><h2>{title}</h2></div>
      <button type="button" className="icon-button" aria-label={t("Close")} title={t("Close")} onClick={onClose}><X size={16} /></button>
    </header>
    {asset?.description && <p className="dg-asset-description">{asset.description}</p>}
    {shown.length > 0 && <section>
      <h3>{t("On this display")}</h3>
      <ul className="dg-asset-rows">{shown.map((row) => <li key={`${row.element}/${row.slot}/${row.signal}`}>
        <button type="button" data-state={row.state} title={t("Trend of {name}", { name: row.label || row.signal || "" })} onClick={() => onTrend(row.label || title, [row.signal as string])}>
          <span className="dg-asset-name"><i className="dg-asset-dot" />{row.label || row.signal}</span>
          <span className="dg-asset-value">{row.error ? "?" : `${formatValue(row.value ?? null)}${row.unit ? ` ${row.unit}` : ""}`}</span>
        </button>
      </li>)}</ul>
    </section>}
    {error && <p className="dg-problems">{error}</p>}
    {!data && !error ? <Loading /> : <>
      {signals.length > 0 && <section>
        <h3>{t("Signals")}</h3>
        <ul className="dg-asset-rows">{signals.map(([role, signal]) => <li key={role}>
          <button type="button" title={t("Trend of {name}", { name: signal })} onClick={() => onTrend(`${title} · ${role}`, [signal])}>
            <span className="dg-asset-name">{role}</span><span className="dg-asset-signal">{signal}</span>
          </button>
        </li>)}</ul>
      </section>}
      {data && data.dashboards.length > 0 && <section>
        <h3>{t("Dashboards")}</h3>
        <ul className="dg-asset-links">{data.dashboards.map((item) => <li key={item.dashboard_id}>
          <Link to={`/d/${item.dashboard_id}${item.picks_asset ? `?asset=${encodeURIComponent(assetId)}` : ""}`}><LayoutDashboard size={14} /> {item.name}</Link>
        </li>)}</ul>
      </section>}
    </>}
    <footer>
      <button type="button" className="button button-primary button-small" disabled={!every.length} onClick={() => onTrend(title, every)}><LineChart size={14} /> {t("Trend")}</button>
      {/* PlantCraft's own page for the asset: the frame opens it, the address leaves View. */}
      <a className="button button-secondary button-small" href={`/assets/${encodeURIComponent(assetId)}`}><ExternalLink size={14} /> {t("Asset page")}</a>
    </footer>
  </aside>;
}
