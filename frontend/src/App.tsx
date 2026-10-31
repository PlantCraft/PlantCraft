/** The platform's front end: sign-in, then two apps in one page: Desk, each
 * person's day, at "/", and PlantCraft, the suite's setup and administration, at "/admin". */
import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowRight, Building2, CalendarDays, ChevronDown, ClipboardCheck, CloudDownload, DatabaseBackup, Gauge, KeyRound, Languages, LayoutDashboard, LifeBuoy, ListTodo, LoaderCircle, LockKeyhole, Network, Package, ScrollText, Settings2, ShieldCheck, SlidersHorizontal, StickyNote, Sun, UserRound, Users, XCircle } from "lucide-react";
import { announceMessagesChanged, AppFrames, appPrefix, claimPanel, isFramed, otherPanelOpen, PythonMark, sanitizeIcon, SuiteShell, toApp, toFrame, FRAME_ATTR, FRAME_OFF, type FrameState, type ShellNavItem, type SuiteApp } from "@plantcraft/ui";
import { api, requestJson, UNAUTHORIZED_EVENT } from "./api";
import { BrandMark } from "./Brand";
import { DemoUsers, HelpPage, NoAccess, NotFound } from "./CorePages";
import { DemoGuide, startGuide } from "./DemoGuide";
import { NoticeFollowUp } from "./NoticeFollowUp";
import { DemoContact, DemoEntry, DemoVisitBar } from "./DemoVisit";
import type { DemoVisitInfo, PublicDemoInfo } from "./demoApi";
import { directoryApi, ssoStartUrl, type SignInMethods } from "./directoryApi";
import { EMBEDDED, isMessagesPath, navigate, openOutside } from "./nav";
import { AssetPage, AssetsPage } from "./AssetsPage";
import { AssetImportPage, AssetImportReview } from "./AssetImport";
import { AssetTypesPage } from "./AssetTypes";
import { currentAssetPath, sourcesUrl } from "./assetLinks";
import { AttentionPage, PlatformHome } from "./PlatformHome";
import { DeskToday, WidgetGalleryPage } from "./Desk";
import { SetupPage } from "./SetupPage";
import { platformTour } from "./PlatformTour";
import SuiteHealthBanner from "./SuiteHealthBanner";
import { LANGUAGES, language, setLanguage, t, type Language } from "./i18n";
import { SessionContext, canSee, safeNext, useAccess, useCanOperate } from "./session";
import { suiteApi, TOKEN_RENEW_MS } from "./suiteApi";
import { syncPreferences } from "./preferencesApi";
import type { AccessInfo, HomeData, Installation, SessionInfo } from "./types";

const UsersPage = lazy(() => import("./UsersAdmin"));
const AppKeysPage = lazy(() => import("./AppKeys"));
const AppsPage = lazy(() => import("./AppsPage"));
const PersonPage = lazy(() => import("./People"));
const HealthPage = lazy(() => import("./OperationsPage").then((module) => ({ default: module.HealthPage })));
const BackupsPage = lazy(() => import("./OperationsPage").then((module) => ({ default: module.BackupsPage })));
const UpdatesPage = lazy(() => import("./OperationsPage").then((module) => ({ default: module.UpdatesPage })));
const LogsPage = lazy(() => import("./OperationsLogs").then((module) => ({ default: module.LogsPage })));
const LoadAlertsPage = lazy(() => import("./OperationsLimits").then((module) => ({ default: module.LoadAlertsPage })));
const RequestsPage = lazy(() => import("./OperationsRequests").then((module) => ({ default: module.RequestsPage })));
const PartnersPage = lazy(() => import("./OperationsPartners").then((module) => ({ default: module.PartnersPage })));
const SupportPage = lazy(() => import("./OperationsSupport").then((module) => ({ default: module.SupportPage })));
const LanguageModelPage = lazy(() => import("./LanguageModel"));
const AssistantAccessPage = lazy(() => import("./AssistantAccess"));
const ExecutionsPage = lazy(() => import("./Executions"));
const MessagesPage = lazy(() => import("./Messages"));
const ActionsPage = lazy(() => import("./Actions"));
const GroupsPage = lazy(() => import("./Groups"));
const GroupPage = lazy(() => import("./Groups").then((module) => ({ default: module.GroupPage })));
const MailSettingsPage = lazy(() => import("./MailSettings"));
const CorporateLoginPage = lazy(() => import("./CorporateLogin"));
const CalendarSettingsPage = lazy(() => import("./DeskSettings"));
const SpecialistsPage = lazy(() => import("./Specialists"));
const AssistantPage = lazy(() => import("./Assistant"));
const CalendarPage = lazy(() => import("./CalendarPage").then((module) => ({ default: module.CalendarPage })));
const TodoPage = lazy(() => import("./TodoPage").then((module) => ({ default: module.TodoPage })));
const NotesPage = lazy(() => import("./NotesPage").then((module) => ({ default: module.NotesPage })));
const TeamPage = lazy(() => import("./TeamPage").then((module) => ({ default: module.TeamPage })));
const AuditLogPage = lazy(() => import("./AuditLog"));
const NotebooksPage = lazy(() => import("./Notebooks"));
const PreferencesPage = lazy(() => import("./Preferences").then((module) => ({ default: module.PreferencesPage })));
const InstallationSettingsPage = lazy(() => import("./Preferences").then((module) => ({ default: module.InstallationSettingsPage })));
const ComputeSettingsPage = lazy(() => import("./ComputeSettings"));
const NotebookSettingsPage = lazy(() => import("./Notebooks").then((module) => ({ default: module.NotebookSettingsPage })));
const SetupAppsPage = lazy(() => import("./SetupApps").then((module) => ({ default: module.SetupAppsPage })));
const PAGE_LOADING = <div className="module-state"><span>{t("Loading…")}</span></div>;

function Login({ onLogin, publicDemo, demoEnded, installation }: { onLogin: (username: string) => void; publicDemo?: PublicDemoInfo | null; demoEnded?: boolean; installation?: Installation | null }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [methods, setMethods] = useState<SignInMethods | null>(null);
  // A public demo hides the account form behind its button (show there is a
  // sign-in without scaring visitors); `?account` opens it at once.
  const [accountOpen, setAccountOpen] = useState(() => new URLSearchParams(window.location.search).has("account"));
  const showForm = !publicDemo || accountOpen;
  useEffect(() => {
    // Corporate sign-in: single sign-on's button, and why the last one failed (said once).
    directoryApi.methods().then((value) => { setMethods(value); if (value.error) setError(value.error); }).catch(() => undefined);
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(username, password);
      onLogin(result.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't sign in."));
    } finally {
      setLoading(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-form-wrap">
        <form className="login-card" onSubmit={submit}>
          <BrandMark className="login-mark" size={48} />
          {/* A public demo: two buttons, the demo first; "Sign in" opens the
              team's form, which also shows a working installation. */}
          {publicDemo && <>
            <h1>{t("Demo")}</h1>
            <DemoEntry ended={demoEnded ?? false} contactUrl={publicDemo.contact_url} onEntered={onLogin} />
            {!accountOpen && <button type="button" className="button button-secondary button-wide" onClick={() => setAccountOpen(true)}>{t("Sign in")}</button>}
            {accountOpen && <div className="login-divider"><span>{t("or sign in with an account")}</span></div>}
          </>}
          {!publicDemo && <h1>{t("Sign in to PlantCraft")}</h1>}
          {installation && !publicDemo && <p className="login-installation">
            <span>{installation.name}</span>
            <span>{t("Version {version}", { version: installation.version })}</span>
            <span>{publicDemo ? t("Public demo") : t("Internal network")}</span>
          </p>}
          {error && <div className="form-error"><AlertTriangle size={16} />{error}</div>}
          {showForm && <>
          {methods?.oidc && <>
            <a className="button button-primary button-wide" href={ssoStartUrl(safeNext(window.location.search, window.location.origin))}><Building2 size={18} /> {t("Sign in with {label}", { label: methods.oidc_label ?? t("company account") })}</a>
            <div className="login-divider"><span>{t("or")}</span></div>
          </>}
          <label>{t("Username")}<div className="input-shell"><UserRound size={17} /><input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus={Boolean(publicDemo) && accountOpen} /></div></label>
          <label>{t("Password")}<div className="input-shell"><LockKeyhole size={17} /><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus={!publicDemo} /></div></label>
          {methods?.ldap && <small className="login-hint">{t("Use your company username and password.")}</small>}
          <button className="button button-primary button-wide" disabled={loading}>{loading ? <LoaderCircle className="spin" size={18} /> : <>{t("Sign in")} <ArrowRight size={18} /></>}</button>
          <small className="secure-note"><ShieldCheck size={13} /> {t("Protected by an encrypted session")}</small>
          </>}
          {LANGUAGES.length > 1 && <LanguageSelect />}
        </form>
      </section>
    </main>
  );
}

/** Interface language; changing it reloads the page. Styled per context (sign-in card, sidebar) in styles.css. */
function LanguageSelect() {
  return (
    <label className="language-select">
      <Languages size={14} aria-hidden="true" />
      <span className="language-select-field">
        <select aria-label={t("Language")} value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
          {LANGUAGES.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
        </select>
        <ChevronDown size={13} aria-hidden="true" />
      </span>
    </label>
  );
}

// Old addresses that moved (2026-10-20): Settings left, Users and App keys split.
const MOVED: Record<string, string> = { "/settings": "/admin", "/settings/users": "/users", "/app-keys": "/apps/keys", "/data/import": "/asset-import", "/operations": "/health", "/setup/backups": "/backups", "/inbox": "/messages/notifications", "/routines": "/todo" };
const EXACT_PATHS = ["/", "/widgets", "/admin", "/attention", "/calendar", "/todo", "/notes", "/team", "/assets", "/data", "/asset-import", "/asset-import/review", "/executions", "/users", "/users/groups", "/users/specialists", "/apps/keys", "/apps", "/setup", "/setup/language-model", "/setup/assistant-access", "/setup/email", "/setup/calendars", "/setup/corporate-login", "/health", "/ops/logs", "/ops/alerts", "/ops/requests", "/ops/partners", "/ops/support", "/backups", "/updates", "/help", "/messages", "/actions", "/setup/audit", "/setup/notebooks", "/setup/compute", "/setup/installation", "/setup/apps", "/preferences", "/notebooks", "/assistant", "/assistant/new"];
/** The id after a prefix ("/messages/12" -> "12"), or null. */
function idAfter(path: string, prefix: string) {
  return path.startsWith(prefix) && path.length > prefix.length ? decodeURIComponent(path.slice(prefix.length)) : null;
}
/** The pages that are Desk's, the person's own work; the rest are PlantCraft's. */
export function isDeskPath(path: string) {
  return ["/", "/widgets", "/calendar", "/notebooks", "/todo", "/notes", "/team", "/attention", "/messages", "/actions", "/assistant"].includes(path) || ["/messages/", "/actions/", "/people/", "/groups/", "/assistant/"].some((prefix) => path.startsWith(prefix));
}
/** Operations, built in like Desk: the suite's status, load and logs, its backups and updates
 * (docs/operations.md, section 4). Its pages keep the addresses they had in PlantCraft. */
export const OPERATIONS_PATHS = ["/health", "/ops/logs", "/ops/requests", "/ops/partners", "/ops/support", "/ops/alerts", "/backups", "/updates"];
/** What a sponsor at the plant opens in Operations without its role. */
const SPONSOR_PATHS = ["/ops/requests", "/ops/partners"];
export function isOperationsPath(path: string) {
  return OPERATIONS_PATHS.includes(path);
}
function isKnownPath(path: string) {
  return EXACT_PATHS.includes(path) || (path.startsWith("/assets/") && path.length > 8) || path === "/asset-types" || path.startsWith("/asset-types/") || idAfter(path, "/people/") !== null || idAfter(path, "/groups/") !== null || idAfter(path, "/messages/") !== null || idAfter(path, "/actions/") !== null || /^\/assistant\/\d+$/.test(path);
}

function useHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setLoading(true);
    api.home().then((value) => { setData(value); setError(""); }).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load."))).finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  return { data, error, loading, load };
}

function Page({ path, data, username, onInboxChange }: { path: string; data: HomeData; username: string; onInboxChange: () => void }) {
  const access = useAccess();
  const operate = useCanOperate();
  const demoVisitor = Boolean(access.admin_view) && !access.is_admin && !access.can_operate;
  if (path === "/") return <DeskToday data={data} me={data.users.find((item) => item.username === username) ?? null} />;
  if (path === "/widgets") return <WidgetGalleryPage data={data} me={data.users.find((item) => item.username === username) ?? null} />;
  if (path === "/calendar") return <Suspense fallback={PAGE_LOADING}><CalendarPage /></Suspense>;
  if (path === "/todo") return <Suspense fallback={PAGE_LOADING}><TodoPage /></Suspense>;
  if (path === "/notes") return <Suspense fallback={PAGE_LOADING}><NotesPage /></Suspense>;
  if (path === "/assistant" || path.startsWith("/assistant/")) {
    const opened = idAfter(path, "/assistant/");
    return <Suspense fallback={PAGE_LOADING}><AssistantPage chatId={opened === null ? null : opened === "new" ? "new" : Number(opened)} /></Suspense>;
  }
  if (path === "/team") return <Suspense fallback={PAGE_LOADING}><TeamPage /></Suspense>;
  if (path === "/admin") return <PlatformHome data={data} admin={canSee(access, "users")} />;
  if (path === "/attention") return <AttentionPage data={data} />;
  if (path === "/setup") return canSee(access, "users") ? <SetupPage /> : <NoAccess />;
  if (path === "/setup/calendars") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><CalendarSettingsPage /></Suspense> : <NoAccess />;
  if (path === "/setup/audit") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><AuditLogPage /></Suspense> : <NoAccess />;
  if (path === "/setup/email") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><MailSettingsPage /></Suspense> : <NoAccess />;
  if (path === "/setup/corporate-login") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><CorporateLoginPage /></Suspense> : <NoAccess />;
  if (path === "/setup/assistant-access") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><AssistantAccessPage /></Suspense> : <NoAccess />;
  if (path === "/setup/language-model") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><LanguageModelPage /></Suspense> : <NoAccess />;
  if (path === "/assets") return <AssetsPage />;
  if (path.startsWith("/assets/")) return <AssetPage key={path} assetId={decodeURIComponent(path.slice(8))} apps={data.apps} />;
  if (path === "/asset-types" || path.startsWith("/asset-types/")) return <AssetTypesPage selected={path.length > 13 ? decodeURIComponent(path.slice(13)) : null} />;
  if (path === "/data") return <SourcesPage data={data} />;
  if (path === "/asset-import") return <AssetImportPage />;
  if (path === "/asset-import/review") return <AssetImportReview />;
  // Hidden from the menu: each app shows its own runs; kept for a later return.
  if (path === "/executions") return access.can_edit ? <Suspense fallback={PAGE_LOADING}><ExecutionsPage /></Suspense> : <NoAccess />;
  if (path === "/users") return canSee(access, "administration") ? <Suspense fallback={PAGE_LOADING}><UsersPage /></Suspense> : <NoAccess />;
  if (path === "/users/groups") return canSee(access, "administration") ? <Suspense fallback={PAGE_LOADING}><GroupsPage /></Suspense> : <NoAccess />;
  if (path.startsWith("/groups/")) return <Suspense fallback={PAGE_LOADING}><GroupPage key={path} groupId={idAfter(path, "/groups/") ?? ""} /></Suspense>;
  if (path === "/users/specialists") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><SpecialistsPage /></Suspense> : <NoAccess />;
  if (path === "/messages" || path.startsWith("/messages/")) return <Suspense fallback={PAGE_LOADING}><MessagesPage me={username} conversationId={idAfter(path, "/messages/")} onRead={onInboxChange} /></Suspense>;
  if (path.startsWith("/people/")) return <Suspense fallback={PAGE_LOADING}><PersonPage key={path} username={idAfter(path, "/people/") ?? "me"} /></Suspense>;
  if (path === "/actions" || path.startsWith("/actions/")) return <Suspense fallback={PAGE_LOADING}><ActionsPage actionId={idAfter(path, "/actions/")} /></Suspense>;
  if (path === "/apps/keys") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><AppKeysPage /></Suspense> : <NoAccess />;
  if (path === "/apps") return canSee(access, "administration") ? <Suspense fallback={PAGE_LOADING}><AppsPage /></Suspense> : <NoAccess />;
  if (path === "/health") return <Suspense fallback={PAGE_LOADING}><HealthPage /></Suspense>;
  // The public demo's visitor opens Operations but not the server logs (they name its visitors).
  if (path === "/ops/logs") return operate && !demoVisitor ? <Suspense fallback={PAGE_LOADING}><LogsPage /></Suspense> : <NoAccess />;
  // Everyone asks for help and follows their own requests; Operations sees them all.
  if (path === "/ops/requests") return <Suspense fallback={PAGE_LOADING}><RequestsPage /></Suspense>;
  if (path === "/ops/partners") return operate || (access.sponsor_of ?? []).length > 0 ? <Suspense fallback={PAGE_LOADING}><PartnersPage /></Suspense> : <NoAccess />;
  if (path === "/ops/support") return operate ? <Suspense fallback={PAGE_LOADING}><SupportPage people={data.users.filter((item) => item.username !== username)} /></Suspense> : <NoAccess />;
  if (path === "/ops/alerts") return operate ? <Suspense fallback={PAGE_LOADING}><LoadAlertsPage /></Suspense> : <NoAccess />;
  if (path === "/backups") return canSee(access, "administration") ? <Suspense fallback={PAGE_LOADING}><BackupsPage /></Suspense> : <NoAccess />;
  if (path === "/updates") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><UpdatesPage /></Suspense> : <NoAccess />;
  if (path === "/help") return <HelpPage apps={data.apps} />;
  if (path === "/notebooks") return access.level !== "dashboards" ? <Suspense fallback={PAGE_LOADING}><NotebooksPage /></Suspense> : <NoAccess />;
  if (path === "/preferences") return <Suspense fallback={PAGE_LOADING}><PreferencesPage /></Suspense>;
  if (path === "/setup/installation") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><InstallationSettingsPage /></Suspense> : <NoAccess />;
  if (path === "/setup/apps") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><SetupAppsPage /></Suspense> : <NoAccess />;
  if (path === "/setup/compute") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><ComputeSettingsPage /></Suspense> : <NoAccess />;
  if (path === "/setup/notebooks") return canSee(access, "users") ? <Suspense fallback={PAGE_LOADING}><NotebookSettingsPage /></Suspense> : <NoAccess />;
  return <NotFound />;
}

/** Sources and signals belong to the Historian: /data opens its pages, or says to install it. */
function SourcesPage({ data }: { data: HomeData }) {
  const url = sourcesUrl(data);
  const query = window.location.search;
  useEffect(() => { if (url) window.location.replace(`${url}${query}`); }, [url, query]);
  if (url) return <LoadingScreen />;
  return <div className="not-found panel">
    <span className="eyebrow">{t("Historian")}</span>
    <h1>{t("Sources and signals are in the Historian")}</h1>
    <p>{t("The plant's sources, signals and their history are kept by the Historian app. Install it from Apps to connect OPC UA, PI or CSV sources and read their signals.")}</p>
  </div>;
}

/** An icon an app sent to the frame (frame.ts), drawn once it is cleaned. */
const ICONS = new Map<string, string>();
function FrameIcon({ markup }: { markup: string }) {
  let clean = ICONS.get(markup);
  if (clean === undefined) { clean = sanitizeIcon(markup); ICONS.set(markup, clean); }
  return <span className="pcs-frame-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: clean }} />;
}

/** The visible app of the frame. */
function visibleApp(): Window | null {
  return document.querySelector<HTMLIFrameElement>(`iframe[${FRAME_ATTR}]:not([hidden])`)?.contentWindow ?? null;
}

/** The app's address went somewhere in itself: the window's address follows, with no new entry. */
function followApp(url: string) {
  window.history.replaceState(window.history.state, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** A shortcut pressed inside the app, answered by the frame's sidebar. */
function frameKey(key: "[" | "k") {
  window.dispatchEvent(new KeyboardEvent("keydown", key === "k" ? { key: "k", ctrlKey: true } : { key: "[" }));
}

function Shell({ username, canSwitch, onLogout, path }: { username: string; canSwitch: boolean; onLogout: () => void; path: string }) {
  const { data, loading, error, load } = useHome();
  // The suite's frame (round 8): an app's address is drawn here, beside this
  // sidebar, in an iframe; the apps opened stay loaded while the person is on PlantCraft's pages.
  const [frame, setFrame] = useState<FrameState | null>(null);
  const [lastApp, setLastApp] = useState<{ prefix: string; url: string } | null>(null);
  const offFrame = window.location.search.includes(FRAME_OFF);
  const access = useAccess();
  const operate = useCanOperate();
  const demoVisitor = Boolean(access.admin_view) && !access.is_admin && !access.can_operate;
  // Bumped after a conversation was read so the messages button's badge updates at once.
  const [inboxRefresh, setInboxRefresh] = useState(0);
  const bumpInbox = useCallback(() => setInboxRefresh((value) => value + 1), []);
  const admin = canSee(access, "users");
  const adminView = canSee(access, "administration");
  // Notebooks are in everyone's Desk once an administrator turned them on (always for admins,
  // who find there how to turn them on); the switch is in Setup › Notebooks.
  const [notebooksOn, setNotebooksOn] = useState(false);
  useEffect(() => {
    if (access.level === "dashboards") return;
    requestJson<{ enabled: boolean; built: boolean }>("/api/notebooks").then((value) => setNotebooksOn(value.enabled && value.built), () => setNotebooksOn(false));
  }, [access.level]);
  const [teamOn, setTeamOn] = useState(false);
  useEffect(() => {
    if (access.level === "dashboards") return;
    requestJson<{ enabled: boolean }>("/api/desk/team-page").then((value) => setTeamOn(value.enabled), () => setTeamOn(false));
  }, [access.level]);
  // Where this person shows times (Preferences), on a browser that does not know it yet.
  useEffect(() => { if (username) void syncPreferences(); }, [username]);
  const readOnly = !access.can_edit;
  const tour = useMemo(() => (data ? () => platformTour(data, adminView, readOnly, notebooksOn) : undefined), [data, adminView, readOnly, notebooksOn]);
  if (loading && !data) return <LoadingScreen />;
  if (!data) return <ErrorState message={error} retry={load} />;
  const me = data.users.find((item) => item.username === username) ?? null;
  if (EMBEDDED) return <EmbeddedMessages path={path} data={data} username={username} onRead={bumpInbox} />;
  const desk = isDeskPath(path);
  // Operations is an app of its own for the people who may open it; for everyone else /health
  // stays PlantCraft's read-only "System health".
  // A sponsor at the plant who is not in Operations opens its Requests and Partners only.
  const sponsorOnly = !operate && (access.sponsor_of ?? []).length > 0;
  const operating = operate ? isOperationsPath(path) : sponsorOnly && SPONSOR_PATHS.includes(path);
  // Desk: the person's day. PlantCraft: the plant's assets for everyone; the rest is administration.
  // Messages and the Assistant are not Desk pages any more: their buttons above the
  // person's name open them over any screen; /messages and /assistant stay as their full pages.
  // PlantCraft: what everyone uses on top, with no section name; the rest is
  // administration, with Setup last (the suite's rule: an app's settings close its menu).
  const administration = t("Administration");
  const deskNav: ShellNavItem[] = [
    { to: "/", label: t("Today"), icon: <Sun />, match: (current) => current === "/" || current === "/attention" },
    { to: "/actions", label: t("Actions"), icon: <ClipboardCheck /> },
    { to: "/calendar", label: t("Calendar"), icon: <CalendarDays /> },
    { to: "/todo", label: t("To-do"), icon: <ListTodo /> },
    { to: "/notes", label: t("Notes"), icon: <StickyNote /> },
    // Team is hidden until an administrator shows it in Setup › Desk.
    ...(teamOn ? [{ to: "/team", label: t("Team"), icon: <Users /> }] : []),
    // Notebooks last, the most complex; the Python logo says what they are.
    ...(admin || notebooksOn ? [{ to: "/notebooks", label: t("Notebooks"), icon: <PythonMark /> }] : []),
  ];
  const opsNav: ShellNavItem[] = sponsorOnly ? [
    { to: "/ops/requests", label: t("Requests"), icon: <LifeBuoy /> },
    { to: "/ops/partners", label: t("Partners"), icon: <Building2 /> },
  ] : [
    { to: "/health", label: t("Status"), icon: <Activity /> },
    ...(demoVisitor ? [] : [{ to: "/ops/logs", label: t("Logs"), icon: <ScrollText /> }]),
    { to: "/ops/requests", label: t("Requests"), icon: <LifeBuoy /> },
    { to: "/ops/partners", label: t("Partners"), icon: <Building2 /> },
    { to: "/ops/support", label: t("Support access"), icon: <KeyRound /> },
    { to: "/ops/alerts", label: t("Load alerts"), icon: <Gauge /> },
    ...(adminView ? [{ to: "/backups", label: t("Backups"), icon: <DatabaseBackup />, section: administration }] : []),
    ...(admin ? [{ to: "/updates", label: t("Updates"), icon: <CloudDownload />, section: administration }] : []),
  ];
  const nav: ShellNavItem[] = desk ? deskNav : operating ? opsNav : [
    { to: "/admin", label: t("Overview"), icon: <LayoutDashboard /> },
    { to: "/assets", label: t("Assets"), icon: <Network />, match: (current) => current === "/assets" || current.startsWith("/assets/") || current.startsWith("/asset-import") || current.startsWith("/asset-types") },
    // Who opens Operations finds the suite's status there; everyone else reads it here.
    ...(operate ? [] : [{ to: "/health", label: t("System health"), icon: <Activity /> }]),
    { to: "/preferences", label: t("Preferences"), icon: <SlidersHorizontal /> },
    // A public demo's visitor reads People, Apps and Backups too.
    ...(adminView ? [
      { to: "/users", label: t("People"), icon: <Users />, section: administration },
      { to: "/apps", label: t("Apps"), icon: <Package />, section: administration },
    ] : []),
    ...(admin ? [
      { to: "/setup", label: t("Settings"), icon: <Settings2 />, section: administration, match: (current: string) => current.startsWith("/setup") },
    ] : []),
  ];
  // Desk first, PlantCraft last (the shell orders them); both are pages of this one front end.
  const apps: SuiteApp[] = [
    { id: "desk", name: "Desk", url: "/" },
    { id: "processcraft", name: "PlantCraft", url: "/" },
    ...(operate || sponsorOnly ? [{ id: "operations", name: "Operations", url: sponsorOnly ? "/ops/partners" : "/health" }] : []),
    ...data.apps.filter((app) => app.access).map((app) => ({ id: app.id, name: app.name, url: app.url, version: app.version })),
  ];
  // Only the apps in frames have an address prefix: Desk, PlantCraft and Operations are pages of
  // this front end (Operations at /health must not open the platform again in a frame).
  const LOCAL: ("desk" | "processcraft" | "operations")[] = ["desk", "processcraft", "operations"];
  const framedApps = apps.filter((app) => !(LOCAL as string[]).includes(app.id));
  const prefix = offFrame ? null : appPrefix(path, framedApps.map((app) => app.url));
  const entry = prefix ? framedApps.find((app) => appPrefix(app.url, [prefix]) === prefix) ?? null : null;
  const address = `${path}${window.location.search}${window.location.hash}`;
  if (prefix && (lastApp?.prefix !== prefix || lastApp.url !== address)) setLastApp({ prefix, url: address });
  const shown = prefix ? frame : null;
  const frameNav: ShellNavItem[] = (shown?.nav ?? []).map((item) => ({
    to: item.to, label: item.label, section: item.section, icon: <FrameIcon markup={item.icon} />, match: () => item.active,
    children: item.children?.map((child) => ({ to: child.to, label: child.label, match: () => child.active })),
  }));
  const frameBase = shown?.base ?? prefix ?? "/";
  const send = (message: Parameters<typeof toApp>[1]) => toApp(visibleApp(), message);
  const frames = lastApp && <AppFrames active={Boolean(prefix)} url={lastApp.url} prefix={lastApp.prefix} onState={setFrame} onAddress={followApp} onOpen={navigate} onKey={frameKey} />;
  const framed = Boolean(prefix && entry);
  // A panel of the frame was open: the app's assistant takes its place without sliding in.
  const assistantControl = { active: shown?.assistantOpen ?? false, toggle: () => { const still = otherPanelOpen("assistant"); claimPanel("assistant"); send({ type: "pc-frame:assistant", still }); } };
  // One shell for PlantCraft's pages and the apps' (the sidebar stays, only its entries change);
  // the frames keep their place among its children so the apps stay loaded.
  return (
    <SuiteShell
      app={framed ? shown?.app ?? entry!.id : desk ? "desk" : operating ? "operations" : "processcraft"}
      appName={framed ? shown?.appName ?? entry!.name : undefined}
      home={framed ? shown?.home ?? "/" : desk ? "/" : operating ? (sponsorOnly ? "/ops/partners" : "/health") : "/admin"}
      localApps={LOCAL}
      assistant={framed ? shown?.assistant ?? false : path !== "/assistant" && !path.startsWith("/assistant/")}
      assistantControl={framed ? assistantControl : undefined}
      tourId={framed ? undefined : "processcraft"}
      subtitle={framed ? shown?.subtitle : desk ? t("Your day") : operating ? t("Status and logs") : t("Platform")}
      nav={framed ? frameNav : nav}
      path={framed ? shown?.path ?? "/" : path}
      href={framed ? (to) => `${frameBase}${to.replace(/^\//, "")}` : (to) => to}
      navigate={framed ? (to) => send({ type: "pc-frame:go", to }) : navigate}
      onOpenApp={navigate}
      pageTitle={framed ? shown?.heading : undefined}
      fill={framed}
      user={{ name: me?.display_name ?? username, role: me?.role || access.label }}
      onSignOut={onLogout}
      version={framed ? shown?.version ?? null : data.version}
      userMenuExtra={canSwitch ? <DemoUsers username={username} users={data.users} /> : undefined}
      onOpenProfile={() => navigate("/people/me")}
      onOpenPreferences={() => navigate("/preferences")}
      apps={apps}
      inboxRefresh={inboxRefresh}
      tour={framed ? undefined : tour}
      onTour={framed ? (shown?.tour ? () => send({ type: "pc-frame:tour" }) : undefined) : undefined}
    >
      {!framed && admin && <SuiteHealthBanner />}
      {!framed && error && <div className="inline-error">{error}</div>}
      {!framed && (isKnownPath(path) ? <Page path={path} data={data} username={username} onInboxChange={bumpInbox} /> : <NotFound />)}
      {frames}
    </SuiteShell>
  );
}

/** Messages alone, inside the panel another screen opened over itself (`?embed=1`): no sidebar,
 * links outside Messages open in the whole window, and reading tells the panel to update its badge. */
function EmbeddedMessages({ path, data, username, onRead }: { path: string; data: HomeData; username: string; onRead: () => void }) {
  useEffect(() => {
    document.documentElement.classList.add("pc-embedded");
    // A link to anything but Messages leaves the panel (before the page's own click handlers).
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin === window.location.origin && isMessagesPath(url.pathname)) return;
      event.preventDefault();
      event.stopPropagation();
      openOutside(url.href);
    };
    document.addEventListener("click", click, true);
    return () => { document.removeEventListener("click", click, true); document.documentElement.classList.remove("pc-embedded"); };
  }, []);
  const read = useCallback(() => { onRead(); announceMessagesChanged(); }, [onRead]);
  const target = isMessagesPath(path) ? path : "/messages";
  return <main className="pc-embedded-page">
    <Page path={target} data={data} username={username} onInboxChange={read} />
  </main>;
}

function LoadingScreen() {
  return <div className="loading-screen"><BrandMark size={44} title="PlantCraft" className="pc-logo-mark" /><LoaderCircle className="spin" /><p>{t("Loading…")}</p></div>;
}

function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <main className="error-page"><XCircle /><h1>{t("Couldn't load")}</h1><p>{message}</p>{retry && <button className="button button-primary" onClick={retry}>{t("Try again")}</button>}</main>;
}

/** A person with dashboards-only access: PlantCraft has no page for them; the dashboards app will. */
function DashboardsOnly({ onLogout }: { onLogout: () => void }) {
  return <main className="error-page"><LockKeyhole /><NoAccess text={t("Your access is limited to dashboards. Open them from the dashboards app of the suite.")} /><button className="button button-secondary" onClick={onLogout}>{t("Sign out")}</button></main>;
}

type AuthState = { loading: boolean; authenticated: boolean; username: string; canSwitch?: boolean; isAdmin?: boolean; access?: AccessInfo; publicDemo?: PublicDemoInfo | null; demoVisit?: DemoVisitInfo | null; demoEnded?: boolean; installation?: Installation | null };
const SIGNED_OUT: AuthState = { loading: false, authenticated: false, username: "" };

function authFrom(result: SessionInfo): AuthState {
  return { loading: false, authenticated: result.authenticated, username: result.username ?? "", canSwitch: result.can_switch_user ?? false, isAdmin: result.is_admin ?? false, access: result.access ?? undefined, publicDemo: result.public_demo ?? null, demoVisit: result.demo_visit ?? null, installation: result.installation ?? null };
}

/** The current page's path; an old address (/plant/<id>) is replaced by the current one (/assets/<id>). */
function currentPath() {
  const renamed = MOVED[window.location.pathname];
  if (renamed) window.history.replaceState(window.history.state, "", renamed);
  const moved = currentAssetPath(window.location.pathname);
  if (moved !== null) window.history.replaceState(window.history.state, "", `${moved}${window.location.search}${window.location.hash}`);
  return window.location.pathname;
}

/** PlantCraft's own page loaded inside the frame (a link out of an app): the frame opens it itself. */
const FRAMED = isFramed();
function FramedPlatform() {
  useEffect(() => { toFrame({ type: "pc-frame:open", url: `${window.location.pathname}${window.location.search}${window.location.hash}` }); }, []);
  return null;
}

function App() {
  if (FRAMED) return <FramedPlatform />;
  return <PlatformApp />;
}

function PlatformApp() {
  const [auth, setAuth] = useState<AuthState>({ loading: true, authenticated: false, username: "" });
  const [path, setPath] = useState(currentPath);
  const [logoutError, setLogoutError] = useState("");
  const loadSession = useCallback(() => {
    api.session().then((result) => setAuth(authFrom(result))).catch(() => setAuth(SIGNED_OUT));
  }, []);
  useEffect(loadSession, [loadSession]);
  useEffect(() => {
    // Any 401 means the session ended: show the login screen.
    const signedOut = () => setAuth((current) => (current.authenticated ? { ...SIGNED_OUT, publicDemo: current.publicDemo, demoEnded: Boolean(current.demoVisit), installation: current.installation } : current));
    window.addEventListener(UNAUTHORIZED_EVENT, signedOut);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, signedOut);
  }, []);
  useEffect(() => {
    const updatePath = () => setPath(currentPath());
    window.addEventListener("popstate", updatePath);
    return () => window.removeEventListener("popstate", updatePath);
  }, []);
  useEffect(() => {
    // An app of the suite sent the browser here (/login?next=...): once signed in, go back to it.
    if (!auth.authenticated || path !== "/login") return;
    const next = safeNext(window.location.search, window.location.origin);
    if (next) window.location.replace(next);
    else { window.history.replaceState({}, "", "/"); setPath("/"); }
  }, [auth.authenticated, path]);
  useEffect(() => {
    // The apps of the suite read a short-lived token cookie; keep it fresh while PlantCraft is open.
    if (!auth.authenticated) return;
    const timer = window.setInterval(() => { suiteApi.renewToken().catch(() => undefined); }, TOKEN_RENEW_MS);
    return () => window.clearInterval(timer);
  }, [auth.authenticated]);
  async function logout() {
    try {
      setLogoutError("");
      await api.logout();
    } catch (err) {
      setLogoutError(err instanceof Error ? err.message : t("Couldn't end the session."));
      return;
    }
    startGuide(null);
    setAuth((current) => ({ ...SIGNED_OUT, publicDemo: current.publicDemo, installation: current.installation }));
    window.history.replaceState({}, "", "/");
    setPath("/");
  }
  const demoEnded = useCallback(() => {
    // The visit's minutes are over (or its place went to someone waiting): back to the sign-in page.
    void api.logout().catch(() => undefined);
    startGuide(null);
    setAuth((current) => ({ ...SIGNED_OUT, publicDemo: current.publicDemo, demoEnded: true, installation: current.installation }));
    window.history.replaceState({}, "", "/");
    setPath("/");
  }, []);
  if (auth.loading) return <LoadingScreen />;
  // Signed in at /login: the effect above is on its way to ?next= (or home).
  if (auth.authenticated && path === "/login") return <LoadingScreen />;
  if (!auth.authenticated)
    return <Login publicDemo={auth.publicDemo} demoEnded={auth.demoEnded} installation={auth.installation} onLogin={(username) => { setAuth({ loading: true, authenticated: true, username }); loadSession(); }} />;
  return (
    <SessionContext.Provider value={{ isAdmin: auth.isAdmin ?? false, access: auth.access, username: auth.username }}>
      {logoutError && <div className="inline-error">{logoutError}</div>}
      {auth.demoVisit && <DemoVisitBar visit={auth.demoVisit} onEnded={demoEnded} onLeave={() => void logout()} />}
      {auth.demoVisit && auth.publicDemo?.contact_url && <DemoContact url={auth.publicDemo.contact_url} />}
      {auth.access?.level === "dashboards" ? <DashboardsOnly onLogout={logout} /> : <><Shell username={auth.username} canSwitch={auth.canSwitch ?? false} onLogout={logout} path={path} /><DemoGuide /><NoticeFollowUp path={path} /></>}
    </SessionContext.Provider>
  );
}

/** Last line of defence: a render error shows a message, not a white page. */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error(error); }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="error-page">
        <XCircle />
        <h1>{t("Something went wrong on this screen")}</h1>
        <p>{t("An unexpected error occurred while showing the page. Reload to continue.")}</p>
        <button className="button button-primary" onClick={() => window.location.reload()}>{t("Reload")}</button>
      </main>
    );
  }
}

export default App;
