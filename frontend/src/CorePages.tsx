/** The pages every installation has: help, not found, no access, and the demo user switch. */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { api } from "./api";
import { HelpTip } from "./HelpTip";
import { t } from "./i18n";
import { AppMark, appLabel, HelpBrowser, useAssistantPage, type HelpDoc } from "@plantcraft/ui";
import { navigate } from "./nav";
import type { SuiteAppCard, WorkspaceUser } from "./types";
import "./access.css";

export function To({ to, className, children, ariaLabel }: { to: string; className?: string; children: ReactNode; ariaLabel?: string }) {
  return <a href={to} className={className} aria-label={ariaLabel} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(to); }}>{children}</a>;
}

export function Heading({ eyebrow, title, description, action, help }: { eyebrow: string; title: string; description: string; action?: ReactNode; help?: string }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><span className="title-with-help page-title-with-help"><h1>{title}</h1>{help && <HelpTip text={help} label={t("Help about {title}", { title })} />}</span><p>{description}</p></div>{action && <div className="heading-actions">{action}</div>}</div>;
}

function Loading() { return <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>; }
function Failure({ message }: { message: string }) { return <div className="module-state module-error"><AlertTriangle /><span>{message}</span></div>; }

export function initials(value: string) {
  return value.split(/[\s.]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

/** Where an app's help is read: its index and one page as Markdown. Apps follow the app standard
 * (`/api/help` lists `[{id, title, category}]`, `/api/help/<id>` is `{markdown}`); Link lists
 * `{pages}` with each page's `api`. */
type HelpSource = { docs: HelpDoc[]; load: (id: string) => Promise<string> };

async function appHelp(url: string): Promise<HelpSource> {
  const base = url.endsWith("/") ? url : `${url}/`;
  const read = async <T,>(path: string): Promise<T> => {
    const response = await fetch(`${base}${path}`, { credentials: "same-origin" });
    if (!response.ok) throw new Error(t("This app's help could not be read."));
    return response.json() as Promise<T>;
  };
  const index = await read<Array<{ id: string; title: string; category?: string }> | { pages: Array<{ id: string; title: string; category?: string; api?: string }> }>("api/help");
  if (Array.isArray(index)) {
    return { docs: index.map((page) => ({ id: page.id, title: page.title, category: page.category })), load: (id) => read<{ markdown: string }>(`api/help/${id.split("/").map(encodeURIComponent).join("/")}`).then((page) => page.markdown) };
  }
  return {
    docs: index.pages.map((page) => ({ id: page.id, title: page.title, category: page.category })),
    load: (id) => read<{ markdown: string }>(`api/help/docs/${id.split("/").map(encodeURIComponent).join("/")}`).then((page) => page.markdown),
  };
}

/** One Help for the whole suite: reached from the person's menu in every app,
 * it opens at that app's guides; the person picks another app at the top. */
export function HelpPage({ apps = [] }: { apps?: SuiteAppCard[] }) {
  const query = new URLSearchParams(window.location.search);
  const shown = apps.filter((app) => app.access);
  const asked = query.get("app") ?? "processcraft";
  const [app, setApp] = useState(shown.some((item) => item.id === asked) ? asked : "processcraft");
  const [source, setSource] = useState<HelpSource | null>(null);
  const [error, setError] = useState("");
  // The assistant's work here (assistant_works/platform.py): find it in the help.
  useAssistantPage({ place: t("Help"), page: "processcraft:help", view: { app } });
  const platform = useCallback((id: string) => api.helpDocument(id).then((doc) => doc.content), []);
  useEffect(() => {
    let alive = true;
    setSource(null); setError("");
    const found = shown.find((item) => item.id === app);
    const loading: Promise<HelpSource> = found
      ? appHelp(found.url)
      : api.help().then((rows) => ({ docs: rows.map((row) => ({ id: row.document_id, title: row.title, category: row.category })), load: platform }));
    loading.then((value) => alive && setSource(value)).catch((err) => alive && setError(err instanceof Error ? err.message : t("Couldn't load help.")));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app]);
  const where = (next: string, doc?: string) => `/help?app=${encodeURIComponent(next)}${doc ? `&doc=${encodeURIComponent(doc)}` : ""}`;
  function pick(next: string) { setApp(next); window.history.replaceState(window.history.state, "", where(next)); }
  const choices = [{ id: "processcraft", name: "PlantCraft" }, ...shown.map((item) => ({ id: item.id, name: appLabel(item.id, item.name) }))];
  return <>
    <div className="page-heading"><div><h1>{t("Help")}</h1><p>{t("The guides of every app of the suite. The assistant reads them too: ask it from the button at the top of any page.")}</p></div></div>
    <div className="help-apps" role="tablist" aria-label={t("App")}>
      {choices.map((item) => <button key={item.id} type="button" role="tab" aria-selected={item.id === app} className={item.id === app ? "active" : undefined} onClick={() => pick(item.id)}>
        <AppMark app={item.id} name={item.name} size={18} />{item.name}
      </button>)}
    </div>
    {error ? <Failure message={error} /> : !source ? <Loading /> : source.docs.length === 0 ? <p className="muted">{t("This app has no guides yet.")}</p>
      : <HelpBrowser key={app} docs={source.docs} load={source.load} initial={query.get("doc") ?? undefined} onOpen={(id) => window.history.replaceState(window.history.state, "", where(app, id))} />}
  </>;
}

export function NotFound() {
  return <div className="not-found panel">
    <span className="eyebrow">{t("Page not found")}</span>
    <h1>{t("This address does not exist")}</h1>
    <p>{t("The link may be out of date, or the page belongs to an app of the suite: open it from the home page.")}</p>
    <To to="/" className="button button-primary">{t("Go to the home page")}</To>
  </div>;
}

/** A page this person's access level does not open. */
export function NoAccess({ title, text }: { title?: string; text?: string }) {
  return <div className="not-found panel">
    <span className="eyebrow">{t("No access")}</span>
    <h1>{title ?? t("You don't have access to this page")}</h1>
    <p>{text ?? t("The admin decides what each person can open. Ask them to grant it if you need it.")}</p>
  </div>;
}

/** The demo's user switch, at the top of the user menu (installations without sign-in). */
export function DemoUsers({ username, users }: { username: string; users: WorkspaceUser[] }) {
  const [error, setError] = useState("");
  async function become(next: string) {
    try { setError(""); await api.switchUser(next); window.location.reload(); } catch (err) { setError(err instanceof Error ? err.message : t("Failed to switch user.")); }
  }
  return <>
    {error && <div className="form-error">{error}</div>}
    <span className="pcs-pop-label">{t("Sign in as (demo)")}</span>
    {users.map((user) => <button key={user.username} className={user.username === username ? "active" : ""} onClick={() => void become(user.username)}><span className="pcs-avatar">{initials(user.display_name)}</span><span><strong>{user.display_name}</strong><br /><small>{user.role}</small></span></button>)}
    <hr />
  </>;
}
