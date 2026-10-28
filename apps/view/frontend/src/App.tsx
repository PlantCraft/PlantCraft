import { AppLockup, SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourExamples, tourSteps, type TourExamples } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";
import "./dashboards.css";

// Each page loads when it is first opened: Plotly (1.4 MB) only comes with a page that draws.
const DashboardPage = lazy(() => import("./DashboardPage").then((m) => ({ default: m.DashboardPage })));
const DashboardsPage = lazy(() => import("./DashboardsPage").then((m) => ({ default: m.DashboardsPage })));
const OverviewPage = lazy(() => import("./OverviewPage").then((m) => ({ default: m.OverviewPage })));
const ReportPage = lazy(() => import("./ReportPage").then((m) => ({ default: m.ReportPage })));
const ReportsPage = lazy(() => import("./ReportsPage").then((m) => ({ default: m.ReportsPage })));
const TrendsPage = lazy(() => import("./TrendsPage").then((m) => ({ default: m.TrendsPage })));
const AssetPage = lazy(() => import("./SuitePages").then((m) => ({ default: m.AssetPage })));
const DiagramPage = lazy(() => import("./diagrams/DiagramPage").then((m) => ({ default: m.DiagramPage })));
const PublicDiagramPage = lazy(() => import("./diagrams/DiagramPage").then((m) => ({ default: m.PublicDiagramPage })));
const DiagramsPage = lazy(() => import("./diagrams/DiagramsPage").then((m) => ({ default: m.DiagramsPage })));
const HelpView = lazy(() => import("./SuitePages").then((m) => ({ default: m.HelpView })));

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, id] = path.split("/").map((part) => decodeURIComponent(part));
  // /dashboards/<id> is the address a #dashboard: reference opens (app.toml), /d/<id> the list's.
  if ((section === "d" || section === "dashboards") && id) return <DashboardPage key={id} dashboardId={id} me={me} />;
  if (section === "trends") return <TrendsPage me={me} trendId={id || undefined} />;
  if (section === "diagrams" && id) return <DiagramPage key={id} diagramId={id} me={me} />;
  if (section === "diagrams") return <DiagramsPage me={me} />;
  if (section === "reports" && id) return <ReportPage key={id} reportId={id} me={me} />;
  if (section === "reports") return <ReportsPage me={me} />;
  if (section === "assets" && id) return <AssetPage key={id} assetId={id} />;
  if (section === "help") return <HelpView pageId={id || undefined} />;
  if (section === "dashboards") return <DashboardsPage me={me} />;
  if (!section) return <OverviewPage />;
  return <ErrorBox text={t("Page not found.")} />;
}

/** A public link: one dashboard (or one diagram), read-only, no sign-in and no suite frame. */
function PublicApp({ token, diagram = false }: { token: string; diagram?: boolean }) {
  const home = diagram ? `/share/diagram/${encodeURIComponent(token)}` : `/share/${encodeURIComponent(token)}`;
  return <div className="shell tc-public-shell">
    <main className="content"><Suspense fallback={<Loading />}>{diagram ? <PublicDiagramPage token={token} /> : <DashboardPage token={token} />}</Suspense></main>
    <a className="tc-public-brand" href={href(home)}><AppLockup app="dashcraft" size={20} /></a>
  </div>;
}

export function App() {
  const path = usePath();
  const diagram = /^\/share\/diagram\/([^/]+)$/.exec(path);
  if (diagram) return <PublicApp token={decodeURIComponent(diagram[1])} diagram />;
  const shared = /^\/share\/([^/]+)$/.exec(path);
  return shared ? <PublicApp token={decodeURIComponent(shared[1])} /> : <SignedInApp path={path} />;
}

function SignedInApp({ path }: { path: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  useSuiteSession(UNAUTHORIZED_EVENT);
  useEffect(() => {
    api.me().then(setMe).catch((err: Error) => setError(err.message));
  }, []);
  // The tour opens a dashboard, a process display, a report and a trend (owner, 2026-10-28).
  const [examples, setExamples] = useState<TourExamples | undefined>(undefined);
  useEffect(() => { if (me) void tourExamples().then(setExamples); }, [me]);
  const tour = useMemo(() => (me && examples ? () => tourSteps(examples) : undefined), [me, examples]);
  return <SuiteShell
    app="dashcraft"
    subtitle={t("Dashboards, trends and reports")}
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
    {error ? <ErrorBox text={error} /> : me ? <Suspense fallback={<Loading />}><Route path={path} me={me} /></Suspense> : <Loading />}
  </SuiteShell>;
}
