import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { DiagramView, DiagramsPage } from "./DiagramsPage";
import { DrawingView, DrawingsPage } from "./DrawingsPage";
import { PlantMapPage } from "./PlantMapPage";
import { HelpView } from "./SuitePages";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourSteps } from "./pages";
import type { LicenseState, Me } from "./types";
import { ErrorBox, Loading } from "./ui";

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, id, part, extra] = path.split("/").map((piece) => decodeURIComponent(piece));
  if (section === "drawings" && id) return <DrawingView key={id} drawingId={id} me={me} />;
  if (section === "drawings") return <DrawingsPage me={me} />;
  if (section === "diagrams" && id && part) return <DiagramView key={`${id}-${part}-${extra ?? ""}`} revId={id} page={Number(part) || 1} me={me} pick={extra || undefined} />;
  if (section === "diagrams") return <DiagramsPage me={me} />;
  if (section === "help") return <HelpView pageId={id || undefined} />;
  // The suite's asset deep link (assets/<id>) opens the plant map.
  if (!section || section === "plant-map" || section === "assets") return <PlantMapPage me={me} />;
  return <ErrorBox text={t("Page not found.")} />;
}

/** A closed app says plainly when its licence is missing or ending (PlantCraft docs/app-package.md, 8). */
function LicenceBanner({ licence }: { licence: LicenseState | null }) {
  if (!licence || licence.status === "valid") return null;
  return <div className="panel licence-banner" role="status">
    <strong>{licence.usable ? t("The licence is ending") : t("PID needs a licence")}</strong>
    <p className="muted">{licence.message}</p>
  </div>;
}

export function App() {
  const path = usePath();
  const [me, setMe] = useState<Me | null>(null);
  const [licence, setLicence] = useState<LicenseState | null>(null);
  const [error, setError] = useState("");
  useSuiteSession(UNAUTHORIZED_EVENT);
  useEffect(() => {
    api.me().then(setMe).catch((err: Error) => setError(err.message));
    api.license().then(setLicence).catch(() => setLicence(null));
  }, []);
  const tour = useMemo(() => (me ? () => tourSteps() : undefined), [me]);
  return <SuiteShell
    app="pidcraft"
    appName="PID"
    subtitle={t("Engineering")}
    nav={NAV.map((item) => ({ ...item, label: t(item.label) }))}
    path={path}
    href={href}
    navigate={navigate}
    user={me ? { name: me.name, role: t(me.role) } : null}
    onSignOut={() => void signOut()}
    helpTo="/help"
    version={me?.version ?? null}
    tour={tour}
  >
    <LicenceBanner licence={licence} />
    {error ? <ErrorBox text={error} /> : me && licence?.usable === false ? null : me ? <Route path={path} me={me} /> : <Loading />}
  </SuiteShell>;
}
