/** The pages every app of the suite serves the same way: one asset's page and the help pages. */
import { AppHelp, errorMessage as message } from "@plantcraft/ui";
import { ChevronRight, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href } from "./nav";
import type { AssetDashboards } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

/** `assets/<id>`: the dashboards that show this asset (PlantCraft's asset page links here). */
export function AssetPage({ assetId }: { assetId: string }) {
  const [data, setData] = useState<AssetDashboards | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.assetDashboards(assetId).then(setData).catch((err) => setError(message(err))); }, [assetId]);
  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  const name = data.asset.name || data.asset.id;
  return <>
    <Heading eyebrow={data.asset.kind ? t("Asset · {kind}", { kind: data.asset.kind }) : t("Asset")} title={name}
      detail={t("Dashboards that show this asset.")} />
    {!data.dashboards.length && <div className="panel tc-empty-list">
      <h2>{t("No dashboard covers this asset yet")}</h2>
      <p className="muted">{t("No dashboard picks assets of this kind or names this asset. An editor can make one with an asset picker for its kind.")}</p>
    </div>}
    {data.dashboards.length > 0 && <section className="pc-grid">
      {data.dashboards.map((item) => {
        const target = `/d/${item.dashboard_id}${item.picks_asset ? `?asset=${encodeURIComponent(data.asset.id)}` : ""}`;
        return <article key={item.dashboard_id} className="panel tc-list-card">
          <Link to={target} className="tc-list-main">
            <div><h2>{item.name}</h2><p>{item.description || t("No description.")}</p>
              <span className="tc-chips"><span className="tag">{item.picks_asset ? t("Opens on {name}", { name }) : t("Names this asset")}</span></span></div>
            <ChevronRight size={16} />
          </Link>
          <footer><small /><span><Link to={`${target}${target.includes("?") ? "&" : "?"}screen=1`} className="icon-button"><Monitor size={15} aria-label={t("Full screen")} /></Link></span></footer>
        </article>;
      })}
    </section>}
  </>;
}

/** Help: the Dashboards guides (docs/help, served by /api/help) in the suite's help browser.
 * `?doc=<id>` opens one guide; `/help/<id>` (the address before the suite frame) still does. */
export function HelpView({ pageId }: { pageId?: string }) {
  return <AppHelp index={api.help} page={helpMarkdown} helpHref={href("/help")} initial={pageId} />;
}

const helpMarkdown = (id: string) => api.helpPage(id).then((page) => page.markdown);
