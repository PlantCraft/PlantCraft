import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourExample, tourSteps } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";

// Each page loads when it is first opened: Plotly (1.4 MB) and the editors come only with the
// pages that draw them, not with every page of the app.
const ExportPage = lazy(() => import("./ExportPage").then((m) => ({ default: m.ExportPage })));
const HelpPage = lazy(() => import("./HelpPage").then((m) => ({ default: m.HelpPage })));
const ImportsPage = lazy(() => import("./ImportsPage").then((m) => ({ default: m.ImportsPage })));
const OverviewPage = lazy(() => import("./OverviewPage").then((m) => ({ default: m.OverviewPage })));
const PointPage = lazy(() => import("./PointPage").then((m) => ({ default: m.PointPage })));
const PointsPage = lazy(() => import("./PointsPage").then((m) => ({ default: m.PointsPage })));
const SettingsPage = lazy(() => import("./SettingsPage").then((m) => ({ default: m.SettingsPage })));
const SourcePage = lazy(() => import("./SourcePage").then((m) => ({ default: m.SourcePage })));
const SourcesPage = lazy(() => import("./SourcesPage").then((m) => ({ default: m.SourcesPage })));

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, ...rest] = path.split("/");
  const id = rest.length ? decodeURIComponent(rest.join("/")) : "";
  if (section === "points" && id) return <PointPage signal={id} me={me} />;
  if (section === "points") return <PointsPage me={me} />;
  if (section === "sources" && id) return <SourcePage sourceId={id} me={me} />;
  if (section === "sources") return <SourcesPage me={me} />;
  // Imports and Exports, each its own page (owner, 2026-10-26); /transfer, /transfer/exports
  // and /export are their old addresses.
  if (section === "imports" || (section === "transfer" && !id)) return <ImportsPage me={me} />;
  if (section === "exports" || section === "export" || (section === "transfer" && id === "exports")) return <ExportPage me={me} />;
  if (section === "settings") return <SettingsPage me={me} section={id} />;
  if (section === "help") return <HelpPage />;
  if (!section) return <OverviewPage />;
  return <ErrorBox text={t("Page not found.")} />;
}

export function App() {
  const path = usePath();
  const [me, setMe] = useState<Me | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [error, setError] = useState("");
  useSuiteSession(UNAUTHORIZED_EVENT);
  useEffect(() => {
    api.me().then((answer) => { setMe(answer); setVersion((now) => now ?? answer.version ?? null); }).catch((err: Error) => setError(err.message));
    // The manifest's version (app.toml); /api/me's is the fallback.
    api.meta().then((meta) => { if (meta?.app?.version) setVersion(meta.app.version); }).catch(() => undefined);
  }, []);
  // The tour opens one signal of a control loop (owner, 2026-10-28): found before it starts.
  const [example, setExample] = useState<string | null | undefined>(undefined);
  useEffect(() => { if (me) void tourExample().then(setExample); }, [me]);
  const tour = useMemo(() => (me && example !== undefined ? () => tourSteps(example) : undefined), [me, example]);
  return <SuiteShell
    app="histcraft"
    subtitle={t("Historian")}
    nav={NAV.map((item) => ({ ...item, label: t(item.label) }))}
    path={path}
    href={href}
    navigate={navigate}
    user={me ? { name: me.name, role: t(me.role) } : null}
    onSignOut={() => void signOut()}
    helpTo="/help"
    version={version}
    tour={tour}
  >
    {error ? <ErrorBox text={error} /> : me ? <Suspense fallback={<Loading />}><Route path={path} me={me} /></Suspense> : <Loading />}
  </SuiteShell>;
}
