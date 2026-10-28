import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { t } from "./i18n";
import { href, navigate, usePath, useSearch } from "./nav";
import { NAV, tourSteps } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";
import "./alarms.css";

// Each page loads when it is first opened: Plotly (1.4 MB) and the editors come only with the
// pages that draw them, not with every page of the app.
const AlarmPage = lazy(() => import("./AlarmPage").then((m) => ({ default: m.AlarmPage })));
const EventPage = lazy(() => import("./EventPage").then((m) => ({ default: m.EventPage })));
const EventsPage = lazy(() => import("./EventsPage").then((m) => ({ default: m.EventsPage })));
const OverviewPage = lazy(() => import("./OverviewPage").then((m) => ({ default: m.OverviewPage })));
const PerformancePage = lazy(() => import("./PerformancePage").then((m) => ({ default: m.PerformancePage })));
const PhilosophyPage = lazy(() => import("./PhilosophyPage").then((m) => ({ default: m.PhilosophyPage })));
const RuleEditor = lazy(() => import("./RuleEditor").then((m) => ({ default: m.RuleEditor })));
const RulePage = lazy(() => import("./RulePage").then((m) => ({ default: m.RulePage })));
const RulesPage = lazy(() => import("./RulesPage").then((m) => ({ default: m.RulesPage })));
const SilencesPage = lazy(() => import("./RulesPage").then((m) => ({ default: m.SilencesPage })));
const AssetPage = lazy(() => import("./SuitePages").then((m) => ({ default: m.AssetPage })));
const HelpView = lazy(() => import("./SuitePages").then((m) => ({ default: m.HelpView })));
const SummaryPage = lazy(() => import("./SummaryPage").then((m) => ({ default: m.SummaryPage })));

function Route({ path, me }: { path: string; me: Me }) {
  const search = useSearch();
  const [, section, id, action] = path.split("/").map((part) => decodeURIComponent(part));
  const from = Number(search.get("from")) || undefined;
  const rule = search.get("rule") || undefined;
  if (section === "alarms" && id) return <AlarmPage key={id} alarmId={id} me={me} ack={search.get("ack") === "1"} />;
  if (section === "alarms") return <SummaryPage key={rule ?? ""} me={me} rule={rule} />;
  if (section === "events" && id === "open") return <EventPage key={search.toString()} condition={{ app: search.get("app") ?? "", key: search.get("key") ?? "" }} me={me} />;
  if (section === "events" && id) return <EventPage key={id} eventId={Number(id) || undefined} me={me} />;
  if (section === "events") return <EventsPage me={me} />;
  const schedule = search.get("schedule") ? { id: search.get("schedule") ?? "", name: search.get("name") ?? undefined } : undefined;
  const kind = search.get("kind") || undefined;
  if (section === "rules" && id === "new") return <RuleEditor key={`new-${from ?? ""}-${kind ?? ""}-${schedule?.id ?? ""}`} me={me} fromEvent={from} fromCatalog={kind} schedule={schedule} />;
  if (section === "rules" && id && action === "edit") return <RuleEditor key={id} me={me} ruleId={id} />;
  if (section === "rules" && id) return <RulePage key={id} ruleId={id} me={me} />;
  if (section === "rules") return <RulesPage me={me} />;
  if (section === "silences") return <SilencesPage me={me} />;
  if (section === "performance" || (section === "history" && id === "performance")) return <PerformancePage />;
  if (section === "targets" || (section === "history" && id === "targets")) return <PhilosophyPage me={me} />;
  // History was folded into Alarms (owner's review, 2026-10-26): each alarm keeps its history.
  if (section === "history") return <SummaryPage me={me} />;
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
  const tour = useMemo(() => (me ? () => tourSteps() : undefined), [me]);
  return <SuiteShell
    app="alarmcraft"
    subtitle={t("Alarm management")}
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
