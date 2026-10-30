/**
 * The frame every app of the suite draws (docs/app-standard.md, "Interface"): one left
 * sidebar with the app's name at the top, which opens the app switcher (every app the person
 * may open, PlantCraft last, so there is always a way back), the app's own pages ending with
 * its Help, and at the bottom four quick buttons that cross every app, all alike (owner,
 * 2026-10-24, round 8): Messages and Notifications with their unread counts, the Assistant and the
 * work queues, each opening a panel from the left over the page without leaving the app
 * (SidePanel.tsx; the button of the open panel closes it, and so does going to another page), then
 * the fold button, last in the row so it stays put when clicked (round 8, owner 2026-10-25; the [ key
 * folds it too); under them the person's menu, a floating window beside the sidebar (theme, Preferences,
 * tour, about, sign out). It folds to icons on a wide screen and becomes a drawer on a phone. An app that hands it
 * a `tour` gets the guided tour: it opens by itself the first time the person opens the app, and
 * from the user menu ("Take the tour") or `startTour()` after that.
 */
import { BookOpen, Check, ChevronDown, ChevronRight, Compass, LogOut, Menu, MessagesSquare, Monitor, Moon, PanelLeft, SlidersHorizontal, Sun, UserRound, X } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { appDisplayName, appIdFor, appLabel, type AnyAppId, type AppId } from "./appMarks.js";
import { AssistantHost, AssistantTopButton, pageContext, useOpenAssistant } from "./AssistantDrawer.js";
import { AppLockup, AppMark } from "./Brand.js";
import { InboxButton, inboxBadge, messagesUrl, platformUrl, unreadCount, useInbox } from "./Inbox.js";
import { closeMessages, MessagesHost, NOTIFICATIONS, openMessages, openNotifications, useOpenMessages } from "./MessagesDrawer.js";
import { SearchButton, SuiteSearch, useSearchKey } from "./Search.js";
import { SuiteQueueButton, SuiteQueueHost, useQueuesOpen, useSuiteJobs, useSuiteQueues } from "./SuiteQueue.js";
import { t } from "./i18n.js";
import { setTheme, themeChoice, type ThemeChoice } from "./theme.js";
import { GuidedTour, useTour, type TourStep } from "./Tour.js";
import { FramedShell } from "./FramedShell.js";
import { useClosePanelsOnMove } from "./SidePanel.js";
import { useDismiss } from "./dismiss.js";
import { isFramed } from "./frame.js";
import { UrgentToast, urgentDue } from "./UrgentNotice.js";
import { useTourLanguage } from "./tourLanguage.js";
import { useTabTitle } from "./tabTitle.js";

export type ShellNavItem = {
  /** App path, e.g. "/" or "/runs". */
  to: string;
  /** Already translated. */
  label: string;
  icon: ReactNode;
  /** Active test; default: the path is `to` or below it ("/" only matches itself). */
  match?: (path: string) => boolean;
  /** Group heading (already translated) drawn above the first item of each group, e.g. "Administration". */
  section?: string;
  /** Entries under this one, indented and without icons (an app's pinned and recent projects,
   * then "View all"); hidden while the sidebar is folded. */
  children?: ShellNavChild[];
};

/** One entry under a page of the sidebar. */
export type ShellNavChild = {
  to: string;
  /** Already translated. */
  label: string;
  /** Active test; default: the path is `to` or below it. */
  match?: (path: string) => boolean;
};

/** One entry of GET /api/v1/apps. */
export type SuiteApp = { id: string; name: string; url: string; access?: string; version?: string | null };

export type ShellUser = { name: string; role?: string };

export type SuiteShellProps = {
  /** The app drawing the shell: a family id, or the id of an app outside the family. */
  app: AnyAppId;
  /** The name of an app outside the family (its manifest's), shown beside its letter tile. */
  appName?: string;
  /** The app path of its first page (the brand and the app's entry open it); default "/". */
  home?: string;
  /** Other apps this same page serves (the platform serves Desk and PlantCraft): their entries
   * navigate inside the page, to `appEntryUrl`. */
  localApps?: AppId[];
  /** The key the tour is remembered by (seen or not); default `app`. A page that serves two apps
   * gives both the same key, so one tour covers them. */
  tourId?: string;
  /** Small line under the app name. */
  subtitle?: string;
  nav: ShellNavItem[];
  /** The current app path (without the app's base path). */
  path: string;
  /** Browser address of an app path, and client navigation to it. */
  href: (to: string) => string;
  navigate: (to: string) => void;
  user: ShellUser | null;
  onSignOut: () => void;
  /** Help page of this app, the last entry of its pages in the sidebar; null hides the entry. */
  helpTo?: string | null;
  /** Shown as a quiet line at the foot of the user menu. */
  version?: string | null;
  /** No longer drawn: the language is picked in the person's Preferences (kept so apps still build). */
  language?: { value: string; options: Array<{ code: string; label: string }>; onChange: (code: string) => void };
  /** Extra rows at the top of the user menu (PlantCraft's demo user switch). */
  userMenuExtra?: ReactNode;
  /** Right side of the top bar. */
  actions?: ReactNode;
  /** The suite's apps; fetched from PlantCraft (same host) when left out. */
  apps?: SuiteApp[];
  /** The messages button above the user menu (GET /api/v1/inbox for its badge; a 403 hides it); false hides it. */
  inbox?: boolean;
  /** No longer used: the messages button opens the Messages panel over the page in every app. */
  onOpenMessages?: () => void;
  /** Opens the person's profile inside the app (PlantCraft only); other apps follow the link to
   * PlantCraft's /people/me. */
  onOpenProfile?: () => void;
  /** Opens the person's Preferences (language, time zone) inside PlantCraft without a reload. */
  onOpenPreferences?: () => void;
  /** The suite's search at the top of the sidebar and on Ctrl+K (Search.tsx); false hides it. */
  search?: boolean;
  /** The assistant's button above the user menu and its side panel (AssistantDrawer.tsx); false hides them. */
  assistant?: boolean;
  /** The suite's work queues above the messages button (SuiteQueue.tsx); false hides them. */
  queues?: boolean;
  /** A counter: when it changes the inbox is read again at once (after a conversation was read). */
  inboxRefresh?: number;
  /** The app's guided tour (Tour.tsx); empty or left out, no tour. A function builds the steps
   * again when the person picks another tour language. */
  tour?: TourStep[] | (() => TourStep[]);
  /** The platform's frame (frame.ts): opens another app or a platform page in place, from the app
   * switcher and the search, instead of loading the page again. */
  onOpenApp?: (url: string) => void;
  /** The page's title for the tab, when the page is not drawn in this document (an app in the frame). */
  pageTitle?: string | null;
  /** The content fills the space beside the sidebar, without the page's margins (the frame's apps). */
  fill?: boolean;
  /** The assistant's button drives a panel drawn elsewhere (the app inside the frame): no panel here. */
  assistantControl?: { active: boolean; toggle: () => void } | null;
  /** "Take the tour" does this instead of this shell's own tour (the app inside the frame). */
  onTour?: () => void;
  children: ReactNode;
};

const START_TOUR_EVENT = "plantcraft-ui:start-tour";

/** Open the current app's tour (a "Take the tour" button on a help page). */
export function startTour() {
  window.dispatchEvent(new Event(START_TOUR_EVENT));
}

const COLLAPSED_KEY = "plantcraft-ui:sidebar";

function stored(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Remembered for this page only.
  }
}

function isActive(item: Pick<ShellNavItem, "to" | "match">, path: string): boolean {
  if (item.match) return item.match(path);
  if (item.to === "/") return path === "/";
  return path === item.to || path.startsWith(`${item.to}/`);
}

/** The apps the person may open, from PlantCraft's API v1 (the token cookie travels on the shared host). */
export function useSuiteApps(given?: SuiteApp[]): SuiteApp[] {
  const [apps, setApps] = useState<SuiteApp[]>(given ?? []);
  useEffect(() => {
    if (given) {
      setApps(given);
      return;
    }
    let live = true;
    fetch("/api/v1/apps", { credentials: "same-origin" })
      .then((response) => (response.ok ? response.json() : []))
      .then((rows: unknown) => {
        if (live && Array.isArray(rows)) setApps(rows as SuiteApp[]);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [given]);
  return apps;
}

/** PlantCraft's own entry: the platform is always in the Apps list, so every app links back to
 * it. Its `url` is where its pages are served ("/"); its own first page is ADMIN_PATH. */
export const PLATFORM_APP: SuiteApp = { id: "processcraft", name: "PlantCraft", url: "/" };

/** Desk, each person's day, is served by the platform at its root: the suite's first page. */
export const DESK_APP: SuiteApp = { id: "desk", name: "Desk", url: "/" };

/** The first page of PlantCraft itself (configuration and administration), under the platform's url. */
export const ADMIN_PATH = "admin";

/**
 * The suite's apps in the order they are used: Desk first (the day's work),
 * the Historian that collects, the apps that analyse, model and run, View where results are
 * seen, and PlantCraft last (configuration, seldom opened).
 */
export const SUITE_ORDER = ["desk", "histcraft", "linkcraft", "modelcraft", "alarmcraft", "doccraft", "simcraft", "dashcraft", "processcraft"];

function suiteRank(entry: SuiteApp): number {
  const at = SUITE_ORDER.indexOf(appIdFor(entry.id) ?? "");
  return at < 0 ? SUITE_ORDER.length : at;
}

/** The Apps list as drawn: Desk first and PlantCraft last (both added when the list lacks them,
 * at the platform's url), the others in the suite's order between them (apps it does not know
 * after the known ones, as listed). */
export function appsWithPlatform(apps: SuiteApp[]): SuiteApp[] {
  const platform = apps.find((entry) => appIdFor(entry.id) === "processcraft") ?? PLATFORM_APP;
  const desk = apps.find((entry) => appIdFor(entry.id) === "desk") ?? { ...DESK_APP, url: platform.url };
  const others = apps.filter((entry) => entry !== platform && entry !== desk && appIdFor(entry.id) !== "processcraft" && appIdFor(entry.id) !== "desk");
  const known = (entry: SuiteApp) => appIdFor(entry.id) !== null;
  const sorted = others.map((entry, index) => ({ entry, index })).sort((a, b) => Number(!known(a.entry)) - Number(!known(b.entry)) || suiteRank(a.entry) - suiteRank(b.entry) || a.index - b.index).map((item) => item.entry);
  return [desk, ...sorted, platform];
}

/** Where an entry of the Apps list opens: PlantCraft's own first page is under the platform's url. */
export function appEntryUrl(entry: SuiteApp): string {
  if (appIdFor(entry.id) !== "processcraft") return entry.url;
  return `${entry.url.endsWith("/") ? entry.url : `${entry.url}/`}${ADMIN_PATH}`;
}

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

function NavLink({ item, path, href, navigate, collapsed, className }: { item: ShellNavItem; path: string; href: (to: string) => string; navigate: (to: string) => void; collapsed: boolean; className?: string }) {
  const active = isActive(item, path);
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(item.to);
  }
  return (
    <a href={href(item.to)} onClick={follow} className={`pcs-nav-item${active ? " pcs-active" : ""}${className ? ` ${className}` : ""}`} aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined}>
      {item.icon}
      <span>{item.label}</span>
    </a>
  );
}

function NavChildren({ items, path, href, navigate, label }: { items: ShellNavChild[]; path: string; href: (to: string) => string; navigate: (to: string) => void; label: string }) {
  return (
    <ul className="pcs-nav-children" aria-label={label}>
      {items.map((child) => {
        const active = isActive(child, path);
        const follow = (event: MouseEvent<HTMLAnchorElement>) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
          event.preventDefault();
          navigate(child.to);
        };
        return <li key={child.to}>
          <a href={href(child.to)} onClick={follow} className={`pcs-nav-child${active ? " pcs-active" : ""}`} aria-current={active ? "page" : undefined} title={child.label}>{child.label}</a>
        </li>;
      })}
    </ul>
  );
}

function AppLink({ entry, current, local, home, open, onDone }: { entry: SuiteApp; current: boolean; local: boolean; home: () => void; open: (to: string) => void; onDone: () => void }) {
  const family = appIdFor(entry.id);
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onDone();
    // The app the person is in (or one this page also serves): no reload.
    if ((!current && !local) || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    if (current) home();
    else open(appEntryUrl(entry));
  }
  return (
    <a href={appEntryUrl(entry)} onClick={follow} role="menuitem" className={`pcs-app-item${current ? " pcs-active" : ""}`} aria-current={current ? "page" : undefined}>
      {family ? <AppMark app={family} size={22} /> : <span className="pcs-app-fallback">{entry.name.slice(0, 1)}</span>}
      <span>{appLabel(entry.id, entry.name)}</span>
      {current && <Check size={15} className="pcs-app-check" aria-hidden="true" />}
    </a>
  );
}

/** Where the floating list of apps opens: just under the button, from its left edge. */
export function switcherPlace(button: HTMLElement | null): { top: number; left: number } | undefined {
  if (!button || typeof button.getBoundingClientRect !== "function") return undefined;
  const box = button.getBoundingClientRect();
  return { top: Math.round(box.bottom + 6), left: Math.round(box.left) };
}

/**
 * The app's name at the top of the sidebar, a button that opens the suite's apps (owner,
 * 2026-10-23: the list left the bottom of the sidebar so it no longer crowds the app's own
 * pages). The apps in the order they are used, then PlantCraft apart, last.
 */
function AppSwitcher({ app, appName, entries, localApps, subtitle, collapsed, home, navigate, openApp }: { app: AnyAppId; appName?: string; entries: SuiteApp[]; localApps: AppId[]; subtitle?: string; collapsed: boolean; home: () => void; navigate: (to: string) => void; openApp?: (url: string) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  useDismiss(open, () => setOpen(false), root);
  const label = t("Switch app");
  // The list floats over the sidebar and the page, under the app's name: it
  // is as wide as its names, never the sidebar's width, so the sidebar never scrolls sideways.
  const at = open ? switcherPlace(button.current) : undefined;
  const link = (entry: SuiteApp) => <AppLink key={entry.id} entry={entry} current={appIdFor(entry.id) === app || entry.id === app} local={Boolean(openApp) || localApps.includes(appIdFor(entry.id) as AppId)} home={home} open={openApp ?? navigate} onDone={() => setOpen(false)} />;
  const platform = entries.filter((entry) => appIdFor(entry.id) === "processcraft");
  const others = entries.filter((entry) => appIdFor(entry.id) !== "processcraft");
  return (
    <div className="pcs-switcher" ref={root}>
      <button ref={button} className="pcs-brand" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" aria-label={label} title={collapsed ? label : undefined}>
        {collapsed ? <AppMark app={app} name={appName} size={34} className="pc-logo-mark" /> : <AppLockup app={app} name={appName} size={34} subtitle={subtitle} />}
        {!collapsed && <ChevronDown size={16} className={`pcs-switcher-chevron${open ? " pcs-turned-up" : ""}`} aria-hidden="true" />}
      </button>
      {open && (
        <nav className="pcs-switcher-pop pcs-apps" role="menu" aria-label={t("Apps")} style={at}>
          {others.map(link)}
          {platform.length > 0 && <hr />}
          {platform.map(link)}
        </nav>
      )}
    </div>
  );
}

const THEMES: Array<{ value: ThemeChoice; label: string; icon: ReactNode }> = [
  { value: "light", label: "Light", icon: <Sun size={15} /> },
  { value: "dark", label: "Dark", icon: <Moon size={15} /> },
  { value: "system", label: "System", icon: <Monitor size={15} /> },
];

function UserMenu({ user, version, extra, profileHref, onProfile, preferencesHref, onPreferences, helpHref, onHelp, onSignOut, onTour, collapsed }: { user: ShellUser | null; version?: string | null; extra?: ReactNode; profileHref?: string; onProfile?: () => void; preferencesHref?: string; onPreferences?: () => void; helpHref?: string | null; onHelp?: () => void; onSignOut: () => void; onTour?: () => void; collapsed: boolean }) {
  const [open, setOpen] = useState(false);
  const [theme, setChoice] = useState<ThemeChoice>(themeChoice);
  const root = useRef<HTMLDivElement | null>(null);
  // A click anywhere else closes the menu (it stayed open).
  useDismiss(open, () => setOpen(false), root);
  function pick(choice: ThemeChoice) {
    setTheme(choice);
    setChoice(choice);
  }
  const name = user?.name ?? "";
  return (
    <div className="pcs-user" ref={root}>
      {open && (
        <div className="pcs-user-pop" role="menu">
          {/* Theme first, then the person's pages, help and sign out. The
              version is a quiet line at the foot; each app's version and license are on Updates. */}
          <span className="pcs-pop-label">{t("Theme")}</span>
          <div className="pcs-theme" role="radiogroup" aria-label={t("Theme")}>
            {THEMES.map((item) => (
              <button key={item.value} role="radio" aria-checked={theme === item.value} className={theme === item.value ? "pcs-on" : ""} onClick={() => pick(item.value)}>
                {item.icon}
                <span>{t(item.label)}</span>
              </button>
            ))}
          </div>
          <hr />
          {profileHref && user && (
            <a role="menuitem" className="pcs-menu-link" href={profileHref} onClick={(event) => { if (!onProfile) return; event.preventDefault(); setOpen(false); onProfile(); }}>
              <UserRound size={15} />
              <span>{t("My profile")}</span>
            </a>
          )}
          {preferencesHref && user && (
            <a role="menuitem" className="pcs-menu-link" href={preferencesHref} onClick={(event) => { if (!onPreferences || event.metaKey || event.ctrlKey) return; event.preventDefault(); setOpen(false); onPreferences(); }}>
              <SlidersHorizontal size={15} />
              <span>{t("Preferences")}</span>
            </a>
          )}
          {helpHref && (
            <a role="menuitem" className="pcs-menu-link" href={helpHref} onClick={(event) => { if (!onHelp || event.metaKey || event.ctrlKey) return; event.preventDefault(); setOpen(false); onHelp(); }}>
              <BookOpen size={15} />
              <span>{t("Help")}</span>
            </a>
          )}
          {onTour && (
            <button role="menuitem" onClick={() => { setOpen(false); onTour(); }}>
              <Compass size={15} />
              <span>{t("Take the tour")}</span>
            </button>
          )}
          {extra}
          <hr />
          <button role="menuitem" onClick={onSignOut}>
            <LogOut size={15} />
            <span>{t("Sign out")}</span>
          </button>
          {version && <p className="pcs-version">{t("Version {version}", { version })}</p>}
        </div>
      )}
      <button className="pcs-profile" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" title={collapsed ? name : undefined}>
        <span className="pcs-avatar">{initials(name)}</span>
        <span className="pcs-profile-text">
          <strong>{name}</strong>
          {user?.role && <small>{user.role}</small>}
        </span>
        {/* The menu opens beside the sidebar: the arrow points there, and back while it is open. */}
        <ChevronRight size={15} className={`pcs-profile-chevron${open ? " pcs-turned-back" : ""}`} aria-hidden="true" />
      </button>
    </div>
  );
}

/** The [ key folds and unfolds the sidebar, as in other work tools; not while typing. */
function useFoldKey(fold: () => void) {
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      if (event.key !== "[" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName))) return;
      event.preventDefault();
      fold();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [fold]);
}

/** Shown for this long when new messages arrive. */
export const ARRIVAL_NOTICE_MS = 6000;

/**
 * How many messages arrived since the last reading of the inbox, for a short notice: 0 at
 * first (what was already unread is not news), while nothing grew, and after the notice times out.
 */
export function useArrivals(unread: number | null): number {
  const last = useRef<number | null>(null);
  const [arrived, setArrived] = useState(0);
  useEffect(() => {
    if (unread === null) return;
    const before = last.current;
    last.current = unread;
    if (before === null || unread <= before) return;
    setArrived(unread - before);
    const timer = window.setTimeout(() => setArrived(0), ARRIVAL_NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [unread]);
  return arrived;
}

export function SuiteShell(props: SuiteShellProps) {
  // Inside the platform's frame the frame draws the sidebar: the app draws only its pages.
  if (isFramed()) return <FramedApp {...props} />;
  return <FullShell {...props} />;
}

function FramedApp(props: SuiteShellProps) {
  useTourLanguage();
  const tourSteps = typeof props.tour === "function" ? props.tour() : props.tour;
  return <FramedShell app={props.app} appName={props.appName} subtitle={props.subtitle} home={props.home ?? "/"} tourId={props.tourId} nav={props.nav} path={props.path} href={props.href} navigate={props.navigate} version={props.version} assistant={props.assistant ?? true} tour={tourSteps} isActive={isActive}>{props.children}</FramedShell>;
}

function FullShell(props: SuiteShellProps) {
  const { app, appName, home = "/", localApps = [], tourId, subtitle, nav, path, href, navigate, user, onSignOut, helpTo = "/help", version, userMenuExtra, actions, inbox = true, search = true, assistant = true, queues: showQueues = true, onOpenProfile, onOpenPreferences, inboxRefresh = 0, tour: tourInput, onOpenApp, pageTitle, fill = false, assistantControl, onTour, children } = props;
  useTourLanguage();
  const tourSteps = typeof tourInput === "function" ? tourInput() : tourInput;
  const tour = useTour(tourId ?? app, tourSteps);
  const startOwnTour = tour.start;
  useEffect(() => {
    window.addEventListener(START_TOUR_EVENT, startOwnTour);
    return () => window.removeEventListener(START_TOUR_EVENT, startOwnTour);
  }, [startOwnTour]);
  const apps = useSuiteApps(props.apps);
  // Bumped when the Messages panel read something, and when it closes.
  const [panelRead, setPanelRead] = useState(0);
  const messagesRead = useCallback(() => setPanelRead((value) => value + 1), []);
  const inboxState = useInbox({ enabled: inbox, refresh: inboxRefresh + panelRead });
  const panel = useOpenMessages();
  const messagesOpen = panel !== null && panel !== NOTIFICATIONS;
  const notificationsOpen = panel === NOTIFICATIONS;
  const [searching, setSearching] = useState(false);
  useSearchKey(setSearching, search);
  const [collapsed, setCollapsed] = useState(() => stored(COLLAPSED_KEY, "") === "collapsed");
  const [drawer, setDrawer] = useState(false);
  useEffect(() => setDrawer(false), [path]);
  // On a phone a quick panel takes the screen: the sidebar's drawer closes under it.
  const assistantOpen = useOpenAssistant() !== null;
  const queuesOpen = useQueuesOpen();
  const anyPanel = panel !== null || assistantOpen || queuesOpen;
  useEffect(() => { if (anyPanel) setDrawer(false); }, [anyPanel]);
  useClosePanelsOnMove(`${app} ${path}`);
  const fold = useCallback(() => {
    setCollapsed((was) => {
      store(COLLAPSED_KEY, was ? "" : "collapsed");
      return !was;
    });
  }, []);
  useFoldKey(fold);
  const unread = unreadCount(inboxState.counts);
  const unreadChats = inboxState.counts?.unread_messages ?? 0;
  const unreadNotices = inboxState.counts?.unread_notifications ?? 0;
  const arrived = useArrivals(inboxState.counts ? unread : null);
  const urgent = inboxState.counts?.urgent_notification ?? null;
  const entries = useMemo(() => appsWithPlatform(apps), [apps]);
  // Desk is served by the platform's own server: its search and queue are PlantCraft's, asked once.
  const servers = useMemo(() => entries.filter((entry) => appIdFor(entry.id) !== "desk"), [entries]);
  const queues = useSuiteQueues(servers, { enabled: showQueues });
  // What the person started and what runs now, read from PlantCraft (docs/quick-access.md).
  const [jobs, readJobs] = useSuiteJobs(showQueues && Boolean(user), queuesOpen);
  // One Help for the whole suite: in the person's menu, at PlantCraft's Help
  // with this app's guides open; the assistant answers most questions now. `helpTo` stays the
  // app's own page for old links.
  const help: ShellNavItem | null = null;
  const suiteHelp = helpTo === null ? null : platformUrl(entries, `help?app=${encodeURIComponent(appIdFor(app) ?? app)}`);
  const local = localApps.includes("processcraft") || localApps.includes("desk");
  const contentRef = useRef<HTMLElement | null>(null);
  const content = useCallback(() => contentRef.current, []);
  const activeItem = [...nav, ...(help ? [help] : [])].find((item) => isActive(item, path));
  useTabTitle(app, path, pageTitle || activeItem?.label || null, content, unread, appName);
  const foldLabel = collapsed ? t("Expand the menu") : t("Collapse the menu");
  // The page as the assistant's context, read at the click: where it is and what it shows.
  const assistantPage = () => {
    const heading = contentRef.current?.querySelector("h1");
    const where = (heading?.textContent ?? "").trim() || activeItem?.label || "";
    return { place: [appDisplayName(app, appName), where].filter(Boolean).join(" › "), context: pageContext(contentRef.current) };
  };
  return (
    <div className={`pcs-shell${collapsed ? " pcs-collapsed" : ""}`}>
      <aside className={`pcs-sidebar${drawer ? " pcs-drawer-open" : ""}`}>
        <div className="pcs-sidebar-top">
          <AppSwitcher app={app} appName={appName} entries={entries} localApps={localApps} subtitle={subtitle} collapsed={collapsed} home={() => navigate(home)} navigate={navigate} openApp={onOpenApp} />
          <button className="pcs-icon-button pcs-mobile-only" onClick={() => setDrawer(false)} aria-label={t("Close menu")}><X /></button>
        </div>
        {search && <SearchButton onOpen={() => setSearching(true)} collapsed={collapsed} />}
        <nav className="pcs-nav" aria-label={t("Pages")}>
          {nav.map((item, index) => {
            const heading = item.section && item.section !== nav[index - 1]?.section ? item.section : null;
            return <Fragment key={item.to}>
              {heading && <div className="pcs-nav-heading" role="presentation"><span>{heading}</span></div>}
              <NavLink item={item} path={path} href={href} navigate={navigate} collapsed={collapsed} />
              {!collapsed && item.children?.length ? <NavChildren items={item.children} path={path} href={href} navigate={navigate} label={item.label} /> : null}
            </Fragment>;
          })}
          {help && <NavLink item={help} path={path} href={href} navigate={navigate} collapsed={collapsed} className="pcs-nav-help" />}
        </nav>
        <div className="pcs-sidebar-bottom">
          <div className="pcs-quick" role="group" aria-label={t("Quick panels")}>
            {inbox && !inboxState.forbidden && <InboxButton href={messagesUrl(entries)} unread={unreadChats} collapsed={collapsed} active={messagesOpen} onOpen={() => (messagesOpen ? closeMessages() : openMessages())} />}
            {inbox && !inboxState.forbidden && <InboxButton kind="notifications" href={platformUrl(entries, "messages/notifications")} unread={unreadNotices} collapsed={collapsed} active={notificationsOpen} onOpen={() => (notificationsOpen ? closeMessages() : openNotifications())} />}
            {assistant && <AssistantTopButton variant="sidebar" collapsed={collapsed} platformUrl={platformUrl(entries, "")} page={assistantPage} control={assistantControl ?? undefined} />}
            {showQueues && <SuiteQueueButton queues={queues} collapsed={collapsed} />}
            <button type="button" className="pcs-quick-button pcs-fold" onClick={fold} aria-label={foldLabel} title={`${foldLabel} ( [ )`} aria-expanded={!collapsed}>
              <PanelLeft size={18} aria-hidden="true" />
            </button>
          </div>
          <div className="pcs-account">
            <UserMenu user={user} version={version} extra={userMenuExtra} profileHref={platformUrl(entries, "people/me")} onProfile={onOpenProfile} preferencesHref={platformUrl(entries, "preferences")} onPreferences={onOpenPreferences} helpHref={suiteHelp} onHelp={local ? () => navigate(`/help?app=${encodeURIComponent(appIdFor(app) ?? app)}`) : undefined} onSignOut={onSignOut} onTour={onTour ?? (tourSteps?.length ? tour.start : undefined)} collapsed={collapsed} />
          </div>
        </div>
      </aside>
      {drawer && <div className="pcs-scrim" onClick={() => setDrawer(false)} />}
      <div className="pcs-main">
        <header className="pcs-topbar">
          <button className="pcs-icon-button pcs-mobile-only" onClick={() => setDrawer(true)} aria-label={t("Open menu")} data-tour="menu-button"><Menu /></button>
          <span className="pcs-mobile-only pcs-top-app"><AppLockup app={app} name={appName} size={26} /></span>
          <div className="pcs-top-actions">{actions}</div>
        </header>
        <main className={`pcs-content${fill ? " pcs-content-fill" : ""}`} ref={contentRef}>{children}</main>
      </div>
      {inbox && !inboxState.forbidden && urgentDue(urgent) && <UrgentToast key={urgent.key} notice={urgent} onOpen={openNotifications} onChanged={messagesRead} />}
      {arrived > 0 && inbox && !inboxState.forbidden && !urgentDue(urgent) && (
        <div className="pcs-toast" role="status">
          <MessagesSquare size={17} aria-hidden="true" />
          <span>{arrived === 1 ? t("You have a new message") : t("You have {count} new messages", { count: inboxBadge(arrived) })}</span>
          <a href={messagesUrl(entries)} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); openMessages(); }}>{t("Open")}</a>
        </div>
      )}
      {assistant && !assistantControl && <AssistantHost platformUrl={platformUrl(entries, "")} page={assistantPage} />}
      {inbox && !inboxState.forbidden && <MessagesHost messagesHref={messagesUrl(entries)} onChanged={messagesRead} />}
      {showQueues && <SuiteQueueHost queues={queues} jobs={jobs} onChanged={readJobs} fullHref={platformUrl(entries, "executions")} />}
      {searching && <SuiteSearch apps={servers} current={app === "desk" ? "processcraft" : app} navigate={navigate} openUrl={onOpenApp} onClose={() => setSearching(false)} />}
      {tour.open && tourSteps && <GuidedTour app={app} steps={tourSteps} path={path} navigate={navigate} onClose={tour.close} />}
    </div>
  );
}
