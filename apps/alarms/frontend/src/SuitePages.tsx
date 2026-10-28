/** The pages every app of the suite serves the same way: one asset's page and the help pages. */
import { AppHelp } from "@plantcraft/ui";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href } from "./nav";
import { AlarmTable } from "./SummaryPage";
import type { AssetAlarms, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

/** `assets/<id>`: the alarms configured on this asset or on its signals. */
export function AssetPage({ assetId, me }: { assetId: string; me: Me }) {
  const [data, setData] = useState<AssetAlarms | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.assetAlarms(assetId).then(setData).catch((err) => setError(message(err))), [assetId]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  const name = data.asset.name || data.asset.id;
  return <>
    <Heading eyebrow={data.asset.kind ? t("Asset · {kind}", { kind: data.asset.kind }) : t("Asset")} title={name}
      detail={t("Alarms on this asset and its signals.")} />
    {data.alarms.length ? <AlarmTable alarms={data.alarms} me={me} onChanged={() => void load()} /> : <div className="panel al-empty">
      <h2>{t("No alarm on this asset yet")}</h2>
      <p className="muted">{t("An editor can add a rule that covers it in Rules.")}</p>
      {me.can_edit && <Link to="/rules/new" className="button button-primary">{t("New rule")}</Link>}
    </div>}
  </>;
}

/** Help: PlantCraft Alarms' guides (docs/help, served by /api/help) in the suite's help browser. */
export function HelpView({ pageId }: { pageId?: string }) {
  return <AppHelp index={api.help} page={helpMarkdown} helpHref={href("/help")} initial={pageId} />;
}

const helpMarkdown = (id: string) => api.helpPage(id).then((page) => page.markdown);
