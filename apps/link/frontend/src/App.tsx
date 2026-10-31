import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { t } from "./i18n";
import { href, navigate, SIGNAL_RUN_PREFIX, usePath } from "./nav";
import { NAV, tourExamples, tourSteps, type TourExamples } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";
import { parseResult } from "./loopResult";

// Each page loads when it is first opened: Plotly (1.4 MB), the code editor and the diagram
// editor come only with the pages that draw them, not with every page of Link.
const AssetLinkPage = lazy(() => import("./AssetLink").then((m) => ({ default: m.AssetLinkPage })));
const HelpPage = lazy(() => import("./HelpPage").then((m) => ({ default: m.HelpPage })));
const LoopPage = lazy(() => import("./LoopPage").then((m) => ({ default: m.LoopPage })));
const MethodPage = lazy(() => import("./MethodsPage").then((m) => ({ default: m.MethodPage })));
const OverviewPage = lazy(() => import("./OverviewPage").then((m) => ({ default: m.OverviewPage })));
const EditorWindow = lazy(() => import("./AlgorithmEditor").then((m) => ({ default: m.EditorWindow })));
const NewAlgorithmPage = lazy(() => import("./AlgorithmNew").then((m) => ({ default: m.NewAlgorithmPage })));
const AlgorithmsPage = lazy(() => import("./AlgorithmList").then((m) => ({ default: m.AlgorithmsPage })));
// /algorithms/<id>[/<tab>] and /blocks/<id>[/<tab>]: the page module reads its own route.
const AlgorithmRoute = lazy(() => import("./AlgorithmsPage").then((m) => ({
  default: ({ id, me }: { id: string; me: Me }) => { const { algorithmId, tab } = m.algorithmRoute(id); return <m.AlgorithmPage key={algorithmId} algorithmId={algorithmId} tab={tab} me={me} />; },
})));
const NewBlockPage = lazy(() => import("./BlockEdit").then((m) => ({ default: m.NewBlockPage })));
const BlocksPage = lazy(() => import("./BlocksPage").then((m) => ({ default: m.BlocksPage })));
const BlockRoute = lazy(() => import("./BlocksPage").then((m) => ({
  default: ({ id, me }: { id: string; me: Me }) => { const { blockId, tab } = m.blockRoute(id); return <m.BlockPage key={blockId} blockId={blockId} tab={tab} me={me} />; },
})));
const ExecutionGroupsPage = lazy(() => import("./ExecutionGroups").then((m) => ({ default: m.ExecutionGroupsPage })));
const ExecutionGroupPage = lazy(() => import("./ExecutionGroups").then((m) => ({ default: m.ExecutionGroupPage })));
const SubjectHistoryPage = lazy(() => import("./ExecutionGroups").then((m) => ({ default: m.SubjectHistoryPage })));
const ExecutionsPage = lazy(() => import("./ExecutionsPage").then((m) => ({ default: m.ExecutionsPage })));
const RunPage = lazy(() => import("./RunsPage").then((m) => ({ default: m.RunPage })));
const SchedulesPage = lazy(() => import("./SchedulesPage").then((m) => ({ default: m.SchedulesPage })));
const SchedulePage = lazy(() => import("./SchedulesPage").then((m) => ({ default: m.SchedulePage })));
const ResultsPage = lazy(() => import("./ResultsPage").then((m) => ({ default: m.ResultsPage })));
const RunHistoryPage = lazy(() => import("./ResultsPage").then((m) => ({ default: m.RunHistoryPage })));
// The lists of signals and of loops became the Results page, filtered.
const LegacyResultsPage = lazy(() => import("./ResultsPage").then((m) => ({
  default: ({ kind, me }: { kind: "signal" | "loop"; me: Me }) => {
    const target = m.legacyResultsPath(kind, window.location.search);
    window.history.replaceState({}, "", href(target));
    return <m.ResultsPage key={target} me={me} />;
  },
})));
const SignalPage = lazy(() => import("./SignalPage").then((m) => ({ default: m.SignalPage })));
const SignalQualityPage = lazy(() => import("./SignalQualityPage").then((m) => ({ default: m.SignalQualityPage })));
const SignalRunPage = lazy(() => import("./SignalQualityPage").then((m) => ({ default: m.SignalRunPage })));

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, ...rest] = path.split("/");
  const id = rest.length ? rest.map(decodeURIComponent).join("/") : "";
  if (section === "assets" && id) return <AssetLinkPage assetId={id} me={me} />;
  if (section === "help") return <HelpPage path={path} />;
  if (section === "signals" && id) return <SignalPage signalId={id} me={me} />;
  if ((section === "signals" || section === "loops") && !id) return <LegacyResultsPage kind={section === "signals" ? "signal" : "loop"} me={me} />;
  if (section === "results" && id === "runs") return <RunHistoryPage me={me} />;
  if (section === "results") return <ResultsPage me={me} />;
  if (section === "loops" && id) return <LoopPage loopId={id} me={me} />;
  if (section === "loop-results" && id) {
    // #loop_result:<loop>@<window end> from an action (loopResult.ts): the loop's page.
    const target = `/loops/${encodeURIComponent(parseResult(id).loopId)}`;
    window.history.replaceState({}, "", href(target));
    return <LoopPage loopId={parseResult(id).loopId} me={me} />;
  }
  if (section === "protocols") {
    // The protocols of 0.2 became algorithms.
    const target = !id ? "/algorithms" : id === "signal-quality" ? "/algorithms/signal_quality/settings" : `/algorithms/${encodeURIComponent(id)}`;
    window.history.replaceState({}, "", href(target));
    return <Route path={target} me={me} />;
  }
  if (section === "algorithms" && id === "signal_quality/settings") return <SignalQualityPage me={me} />;
  if (section === "algorithms" && id === "new") return <NewAlgorithmPage me={me} />;
  if (section === "algorithms" && id) return <AlgorithmRoute id={id} me={me} />;
  if (section === "algorithms") return <AlgorithmsPage me={me} />;
  if (section === "blocks" && id === "new") return <NewBlockPage me={me} />;
  if (section === "blocks" && id) return <BlockRoute id={id} me={me} />;
  if (section === "blocks") return <BlocksPage me={me} />;
  if (section === "executions" && id === "queue") return <ExecutionsPage me={me} />;
  if (section === "executions" && id) {
    // /executions/<schedule>[/<subject>]: a subject id may hold "/" (signals), the schedule never does.
    const [groupId, ...subject] = rest.map(decodeURIComponent);
    if (subject.length) return <SubjectHistoryPage key={id} groupId={groupId} subject={subject.join("/")} me={me} />;
    return <ExecutionGroupPage key={groupId} groupId={groupId} me={me} />;
  }
  if (section === "executions") return <ExecutionGroupsPage me={me} />;
  if (section === "schedules" && id) return <SchedulePage key={id} scheduleId={id === "new" ? null : id} me={me} />;
  if (section === "schedules") return <SchedulesPage me={me} />;
  if (section === "runs" && id.startsWith(SIGNAL_RUN_PREFIX)) return <SignalRunPage runId={id.slice(SIGNAL_RUN_PREFIX.length)} me={me} />;
  if (section === "runs" && id) return <RunPage jobId={id} me={me} />;
  if (section === "runs") {
    // The Runs page became Results > Run history.
    window.history.replaceState({}, "", href("/results/runs"));
    return <RunHistoryPage me={me} />;
  }
  if (section === "methods" && id) return <MethodPage methodId={id} me={me} />;
  if (section === "methods") {
    // Methods became the blocks that run them.
    window.history.replaceState({}, "", href("/blocks"));
    return <BlocksPage me={me} />;
  }
  if (section === "assistant") {
    // The assistant is the suite's button at the top of every page, not a page of Link's.
    window.history.replaceState({}, "", href("/"));
    return <OverviewPage />;
  }
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
  const editor = /^\/editor\/(.+)$/.exec(path);
  // The tour opens a block, an algorithm and a result: found before it starts.
  const [examples, setExamples] = useState<TourExamples | undefined>(undefined);
  useEffect(() => { if (me) void tourExamples().then(setExamples); }, [me]);
  const tour = useMemo(() => (me && examples ? () => tourSteps(examples) : undefined), [me, examples]);
  // The algorithm editor has a window of its own, without the frame.
  if (editor) return error ? <ErrorBox text={error} /> : me ? <Suspense fallback={<Loading />}><EditorWindow key={editor[1]} algorithmId={decodeURIComponent(editor[1])} me={me} /></Suspense> : <Loading />;
  return <SuiteShell
    app="linkcraft"
    subtitle={t("Signal and loop quality")}
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
