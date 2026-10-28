/** The pages every app of the suite serves the same way: one asset's page and the help pages. */
import { AppHelp } from "@plantcraft/ui";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href } from "./nav";
import { RunsTable } from "./RunsPage";
import type { AssetRuns, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

/** `assets/<id>`: the simulations fed by this asset's signals, or compared with them. */
export function AssetPage({ assetId, me }: { assetId: string; me: Me }) {
  const [data, setData] = useState<AssetRuns | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.assetRuns(assetId).then(setData).catch((err) => setError(message(err))), [assetId]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  const name = data.asset.name || data.asset.id;
  return <>
    <Heading eyebrow={data.asset.kind ? t("Asset · {kind}", { kind: data.asset.kind }) : t("Asset")} title={name}
      detail={t("Simulations that used this asset's signals as inputs or as a comparison.")} />
    {data.runs.length ? <RunsTable runs={data.runs} me={me} onChanged={() => void load()} /> : <div className="panel empty">
      <h2>{t("No simulation used this asset yet")}</h2>
      <p className="muted">{t("In the code editor, Simulate → Use plant data feeds a model's inputs with signals such as {signals}.", { signals: data.signals.slice(0, 3).join(", ") || t("this asset's") })}</p>
      <Link to="/models" className="button button-primary">{t("Open the models")}</Link>
    </div>}
  </>;
}

/** Help: PlantCraft Models' guides (docs/help, served by /api/help) in the suite's help browser. */
export function HelpView({ pageId }: { pageId?: string }) {
  return <AppHelp index={api.help} page={helpMarkdown} helpHref={href("/help")} initial={pageId} />;
}

const helpMarkdown = (id: string) => api.helpPage(id).then((page) => page.markdown);
