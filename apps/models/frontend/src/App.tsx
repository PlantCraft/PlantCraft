import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourExamples, tourSteps, type TourExamples } from "./pages";
import { blockTab, modelTab, movedTo } from "./paths";
import type { Me } from "./types";
import { ErrorBox, Loading, Redirect } from "./ui";
import "./models.css";

// Each page loads when it is first opened: Plotly (1.4 MB) and the editors come only with the
// pages that draw them, not with every page of the app.
const BlockPage = lazy(() => import("./BlocksPage").then((m) => ({ default: m.BlockPage })));
const BlocksPage = lazy(() => import("./BlocksPage").then((m) => ({ default: m.BlocksPage })));
const ExecutionsPage = lazy(() => import("./ExecutionsPage").then((m) => ({ default: m.ExecutionsPage })));
const GroupPage = lazy(() => import("./ExecutionsPage").then((m) => ({ default: m.GroupPage })));
const QueuePage = lazy(() => import("./ExecutionsPage").then((m) => ({ default: m.QueuePage })));
const ModelEditorWindow = lazy(() => import("./ModelEditor").then((m) => ({ default: m.ModelEditorWindow })));
const NewModelPage = lazy(() => import("./ModelNew").then((m) => ({ default: m.NewModelPage })));
const ModelPage = lazy(() => import("./ModelPage").then((m) => ({ default: m.ModelPage })));
const ModelsPage = lazy(() => import("./ModelsPage").then((m) => ({ default: m.ModelsPage })));
const OverviewPage = lazy(() => import("./OverviewPage").then((m) => ({ default: m.OverviewPage })));
const RunPage = lazy(() => import("./RunsPage").then((m) => ({ default: m.RunPage })));
const NewStudyPage = lazy(() => import("./StudiesPage").then((m) => ({ default: m.NewStudyPage })));
const StudiesPage = lazy(() => import("./StudiesPage").then((m) => ({ default: m.StudiesPage })));
const StudyPage = lazy(() => import("./StudiesPage").then((m) => ({ default: m.StudyPage })));
const AssetPage = lazy(() => import("./SuitePages").then((m) => ({ default: m.AssetPage })));
const HelpView = lazy(() => import("./SuitePages").then((m) => ({ default: m.HelpView })));
const Workbench = lazy(() => import("./Workbench").then((m) => ({ default: m.Workbench })));

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, id, sub, tab] = path.split("/").map((part) => decodeURIComponent(part));
  const moved = movedTo(path, window.location.search);
  if (moved !== null) return <Redirect to={moved} />;
  if (section === "models" && id === "new") return <NewModelPage me={me} />;
  if (section === "models" && id && sub) return <ModelPage key={`${id}/${sub}`} projectId={id} model={sub} tab={modelTab(tab)} me={me} />;
  if (section === "models") return <ModelsPage key={window.location.search} me={me} />;
  if (section === "code" && id) return <Workbench key={id} projectId={id} me={me} />;
  if (section === "studies" && id === "new") return <NewStudyPage />;
  if (section === "studies" && id && sub === "runs" && tab) return <RunPage key={tab} runId={tab} me={me} inStudy={id} />;
  if (section === "studies" && id) return <StudyPage key={id} studyId={id} me={me} />;
  if (section === "studies") return <StudiesPage key={window.location.search} me={me} />;
  if (section === "executions" && id === "queue") return <QueuePage me={me} />;
  if (section === "executions" && id) return <GroupPage key={id} studyId={id} me={me} />;
  if (section === "executions") return <ExecutionsPage me={me} />;
  if (section === "runs" && id) return <RunPage key={id} runId={id} me={me} />;
  if (section === "runs") return <Redirect to="/executions" />;
  if (section === "blocks" && id) return <BlockPage key={id} blockId={id} tab={blockTab(sub)} me={me} />;
  if (section === "blocks") return <BlocksPage me={me} />;
  if (section === "assets" && id) return <AssetPage key={id} assetId={id} me={me} />;
  if (section === "help") return <HelpView pageId={id || undefined} />;
  if (!section) return <OverviewPage me={me} />;
  return <ErrorBox text={t("Page not found.")} />;
}

export function App() {
  const path = usePath();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  useSuiteSession(UNAUTHORIZED_EVENT);
  useEffect(() => {
    api.me().then(setMe).catch((err: Error) => setError(err.message));
  }, []);
  // The tour opens a block, a model and a simulation: found before it starts.
  const [examples, setExamples] = useState<TourExamples | undefined>(undefined);
  useEffect(() => { if (me) void tourExamples().then(setExamples); }, [me]);
  const tour = useMemo(() => (me && examples ? () => tourSteps(examples) : undefined), [me, examples]);
  const editor = /^\/editor\/([^/]+)\/([^/]+)$/.exec(path);
  // A model's editor has a window of its own, without the frame, as Link's.
  if (editor) return error ? <ErrorBox text={error} /> : me ? <Suspense fallback={<Loading />}><ModelEditorWindow key={path} projectId={decodeURIComponent(editor[1])} model={decodeURIComponent(editor[2])} me={me} /></Suspense> : <Loading />;
  return <SuiteShell
    app="modelcraft"
    subtitle={t("Process models")}
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
