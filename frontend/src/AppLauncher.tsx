/** The launcher: the apps of the suite installed here (Apps page or PLANTCRAFT_APPS), each with its mark. */
import { ArrowUpRight, LockKeyhole } from "lucide-react";
import { AppMark, BrandMark } from "./Brand";
import { appIdFor, appLabel, type AppId } from "./appMarks";
import { t } from "./i18n";
import type { SuiteAppCard } from "./types";

/** What each app of the family does, in one line (the launcher, and the tour with `tt`). */
export function appPurpose(id: AppId | null, translate: (text: string) => string = t): string {
  switch (id) {
    case "linkcraft": return translate("Finds the loops and signals that need attention, and says why.");
    case "histcraft": return translate("Keeps the history of every signal, and the apps' own results.");
    case "dashcraft": return translate("Puts trends and health side by side, on any screen.");
    case "simcraft": return translate("The simulated plant the demo runs on.");
    case "alarmcraft": return translate("Alarm performance against ISA-18.2.");
    case "modelcraft": return translate("Builds the models the twins run.");
    case "doccraft": return translate("Finds what the plant's manuals and guides say, and cites the page.");
    default: return translate("An app of the suite.");
  }
}

/** Apps this person may not open stay on the launcher, locked, so they know whom to ask. */
/** The apps as cards; `compact` (a widget) as one row of marks and names. */
export function AppLauncher({ apps, compact = false }: { apps: SuiteAppCard[]; compact?: boolean }) {
  if (compact) return <nav className="hm-launcher-compact" aria-label={t("Your apps")}>
    {!apps.length && <p className="muted small">{t("No apps installed yet")}</p>}
    {apps.map((app) => {
      const mark = appIdFor(app.id);
      const body = <>{mark ? <AppMark app={mark} size={30} /> : <BrandMark size={30} />}<span>{appLabel(app.id, app.name)}</span></>;
      return app.access ? <a key={app.id} href={app.url} title={`${appPurpose(mark)}${app.version ? ` · v${app.version}` : ""}`}>{body}</a> : <span key={app.id} className="hm-launch-locked" title={t("Ask an admin for access")}>{body}</span>;
    })}
  </nav>;
  if (!apps.length) return <div className="panel hm-empty" data-tour="apps"><strong>{t("No apps installed yet")}</strong><p>{t("The apps of the suite (Analytics, Historian, View and others) run beside PlantCraft. An administrator installs them on the Apps page, and they appear here.")}</p></div>;
  return <nav className="pc-grid hm-launcher" aria-label={t("Your apps")} data-tour="apps">
    {apps.map((app) => {
      const mark = appIdFor(app.id);
      const icon = mark ? <AppMark app={mark} size={44} /> : <BrandMark size={44} />;
      const head = (status: string) => <div className="card-head">{icon}<div><h3>{appLabel(app.id, app.name)}</h3><small>{status}</small></div></div>;
      if (!app.access) return <div key={app.id} className="panel card hm-launch hm-launch-locked" title={t("Ask an admin for access")}>
        {head(t("No access"))}<p>{appPurpose(mark)}</p><span className="card-foot"><span>{t("Ask an admin for access")}</span><LockKeyhole size={15} aria-hidden="true" /></span>
      </div>;
      return <a key={app.id} className="panel card hm-launch" href={app.url}>
        {head(`${app.access === "editor" ? t("Can edit") : t("Read only")}${app.version ? ` · v${app.version}` : ""}`)}
        <p>{appPurpose(mark)}</p>
        <span className="card-foot"><span>{t("Open")}</span><ArrowUpRight size={15} aria-hidden="true" /></span>
      </a>;
    })}
  </nav>;
}
