/** Apps page (administrators): install from a signed file, the online catalog, or register an external app. */
import { AlertTriangle, Ban, CheckCircle2, CloudDownload, FileUp, KeyRound, Link2, LoaderCircle, Package, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { DataTable, SUITE_ORDER, type DataColumn, confirmAction, Heading } from "@plantcraft/ui";
import { AppTabs } from "./AppTabs";
import { appFullName, appIdFor } from "./appMarks";
import { appsApi, type Adds, type AppsOverview, type Catalog, type InstalledApp, type PackagePreview } from "./appsApi";
import { locale, t } from "./i18n";
import { useAdminView } from "./session";
import "./access.css";
import "./apps.css";

// The release key keeps the name it was made with (processcraft, before the rename): shown as PlantCraft.
const publisherLabel = (id: string) => (id === "processcraft" || id === "plantcraft" ? "PlantCraft" : id);

const PENDING = new Set(["installing", "updating", "rolling_back", "removing", "key"]);
const ORIGINS: Record<string, string> = {
  configured: t("Configured"),
  package: t("Package"),
  catalog: t("Catalog"),
  external: t("External"),
};
const STATUSES: Record<string, string> = {
  configured: t("Configured on the server"),
  running: t("Running"),
  failed: t("Failed"),
  external: t("External"),
  installing: t("Installing…"),
  updating: t("Updating…"),
  rolling_back: t("Rolling back…"),
  removing: t("Removing…"),
  key: t("Giving its key…"),
};

// What an app adds to PlantCraft, by kind ([contributes] and [[publishes.series]] of its app.toml).
const ADDS: Record<string, [string, string]> = {
  llm: [t("use of a language model"), t("uses of a language model")],
  widgets: [t("widget"), t("widgets")],
  search: [t("search"), t("search")],
  calendar: [t("calendar feed"), t("calendar feeds")],
  todo: [t("kind of to-do"), t("kinds of to-do")],
  refs: [t("kind of reference"), t("kinds of reference")],
  settings: [t("setting"), t("settings")],
  setup: [t("Settings page"), t("Settings pages")],
  queue: [t("work queue"), t("work queue")],
  series: [t("series in the Historian"), t("series in the Historian")],
};

/** "2 widgets · search · 1 use of a language model"; empty when the app adds nothing. */
function addsText(adds: Adds | null | undefined): string {
  return Object.entries(adds ?? {}).filter(([, count]) => count > 0).map(([key, count]) => {
    const [one, many] = ADDS[key] ?? [key, key];
    return key === "search" || key === "queue" ? one : `${count} ${count === 1 ? one : many}`;
  }).join(" · ");
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function size(bytes: number) {
  const format = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
  return bytes < 1024 * 1024 ? `${format(bytes / 1024)} KB` : `${format(bytes / 1024 / 1024)} MB`;
}

export default function AppsPage() {
  const isAdmin = useAdminView();
  const [data, setData] = useState<AppsOverview | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<PackagePreview | null>(null);
  const [busy, setBusy] = useState("");
  const [newKey, setNewKey] = useState<{ app: string; key: string } | null>(null);
  const load = useCallback(() => appsApi.overview().then((value) => { setData(value); setError(""); }).catch((err) => setError(message(err))), []);
  useEffect(() => { if (isAdmin) void load(); }, [isAdmin, load]);
  const pending = data?.apps.some((app) => PENDING.has(app.status)) ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins manage apps.")}</span></div>;

  async function act(label: string, run: () => Promise<unknown>, done?: string) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await run();
      if (done) setNotice(done);
      await load();
    } catch (err) { setError(message(err)); }
    setBusy("");
  }

  async function confirmInstall() {
    if (!preview) return;
    const target = preview;
    await act("install", async () => { await appsApi.install(target.upload_id); setPreview(null); }, t("{name} {version} was handed to the installer.", { name: target.app.name, version: target.app.version }));
  }

  return <div className="apps-page">
    <Heading title={t("Apps")} actions={<><button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => void load()}><RefreshCw /></button></>} />
    <AppTabs current="apps" />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {newKey && <div className="ac-key-reveal apps-key" role="status"><KeyRound size={15} /> <span>{t("App key for {name}, shown only now:", { name: newKey.app })}</span> <code>{newKey.key}</code> <button className="icon-button" onClick={() => setNewKey(null)} aria-label={t("Hide the key")}><X size={15} /></button></div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading apps…")}</span></div>}
    {data && <>
      <section className="apps-status" aria-label={t("App installs")}>
        <span className={`apps-chip ${data.install_enabled ? "apps-chip-on" : "apps-chip-off"}`}>{data.install_enabled ? t("Installs on") : t("Installs off (PLANTCRAFT_APP_INSTALL=off)")}</span>
        <span className={`apps-chip ${data.installer.online ? "apps-chip-on" : "apps-chip-warn"}`}>{data.installer.online ? t("Installer running") : t("Installer not running: requests wait until it starts")}</span>
        <span className="apps-chip">{data.trusted_publishers.length ? t("Trusted publishers: {list}", { list: data.trusted_publishers.map(publisherLabel).join(", ") }) : t("No trusted publishers: add their public keys to trusted-publishers/")}</span>
      </section>
      {preview ? <PreviewPanel preview={preview} busy={busy === "install"} onInstall={() => void confirmInstall()} onCancel={() => void act("discard", async () => { await appsApi.discard(preview.upload_id); setPreview(null); })} /> : <section className="pc-grid">
        <UploadCard disabled={!data.install_enabled} maxMb={data.max_mb} onPreview={setPreview} onError={setError} />
        <CatalogCard enabled={data.catalog.enabled} configured={data.catalog.configured} url={data.catalog.url} installEnabled={data.install_enabled} onSwitch={(on) => void act("catalog", () => appsApi.switchCatalog(on), on ? t("The online catalog is on.") : t("The online catalog is off."))} onPreview={setPreview} onError={setError} />
        <ExternalCard onDone={(app) => { setNotice(app.warning ?? t("{name} was registered.", { name: app.name })); setNewKey(app.app_key ? { app: app.name, key: app.app_key } : null); void load(); }} onError={setError} />
      </section>}
      <InstalledTable apps={data.apps} busy={busy} installEnabled={data.install_enabled} onAct={act} />
    </>}
  </div>;
}

function UploadCard({ disabled, maxMb, onPreview, onError }: { disabled: boolean; maxMb: number; onPreview: (preview: PackagePreview) => void; onError: (text: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  async function choose(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    onError("");
    try { onPreview(await appsApi.upload(file)); } catch (err) { onError(message(err)); }
    setBusy(false);
    if (input.current) input.current.value = "";
  }
  return <article className="panel apps-way">
    <h2><FileUp size={17} /> {t("Install from file")}</h2>
    <p>{t("A signed app package (.pcapp), for servers without internet. You see its publisher, permissions and SBOM before anything is installed. Up to {mb} MB.", { mb: maxMb })}</p>
    <label className={`button button-primary apps-file ${disabled || busy ? "apps-disabled" : ""}`}>
      {busy ? <LoaderCircle className="spin" size={15} /> : <FileUp size={15} />} {busy ? t("Checking the package…") : t("Choose a package")}
      <input ref={input} type="file" accept=".pcapp,.tar,.tar.gz,application/x-tar" disabled={disabled || busy} aria-label={t("App package file")} onChange={(event) => void choose(event.target.files?.[0])} />
    </label>
    {disabled && <small className="muted">{t("Installs are switched off on this server.")}</small>}
  </article>;
}

function CatalogCard({ enabled, configured, url, installEnabled, onSwitch, onPreview, onError }: { enabled: boolean; configured: boolean; url: string | null; installEnabled: boolean; onSwitch: (on: boolean) => void; onPreview: (preview: PackagePreview) => void; onError: (text: string) => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [busy, setBusy] = useState("");
  useEffect(() => { void appsApi.catalog().then(setCatalog).catch((err) => setCatalog({ enabled: true, apps: [], how: message(err) })); }, [enabled]);
  async function download(appId: string) {
    setBusy(appId);
    onError("");
    try { onPreview(await appsApi.download(appId)); } catch (err) { onError(message(err)); }
    setBusy("");
  }
  return <article className="panel apps-way">
    <h2><CloudDownload size={17} /> {t("Catalog")}</h2>
    {!enabled ? <>
      <p><strong>{t("The online catalog is off.")}</strong> {t("This server does not reach the internet for apps, which is right for isolated plants.")}</p>
      <p className="muted">{catalog?.how ?? t("Set PLANTCRAFT_APP_CATALOG_URL to the address of a signed catalog and restart PlantCraft.")}</p>
      {configured && <button className="button button-secondary" onClick={() => onSwitch(true)}><CloudDownload size={15} /> {t("Turn the catalog on")}</button>}
    </> : <>
      <p>{t("Signed packages from {url}. Downloads are checked like a file you upload.", { url: url ?? "" })}</p>
      {catalog?.how && <small className="form-error">{catalog.how}</small>}
      {catalog && !catalog.apps.length && !catalog.how && <small className="muted">{t("The catalog lists no apps.")}</small>}
      <ul className="apps-catalog">{(catalog?.apps ?? []).map((entry) => <li key={`${entry.id}-${entry.version}`}>
        <span><strong>{entry.name}</strong> <code>{entry.version}</code><small>{entry.summary || entry.description || entry.publisher.name || entry.publisher.id}{entry.installed_version ? ` · ${t("installed {version}", { version: entry.installed_version })}` : ""}</small></span>
        <button className="button button-secondary" disabled={!installEnabled || !!busy} onClick={() => void download(entry.id)}>{busy === entry.id ? <LoaderCircle className="spin" size={15} /> : <CloudDownload size={15} />} {t("Get")}</button>
      </li>)}</ul>
      <button className="button button-secondary" onClick={() => onSwitch(false)}><Ban size={15} /> {t("Turn the catalog off")}</button>
    </>}
  </article>;
}

function ExternalCard({ onDone, onError }: { onDone: (app: InstalledApp) => void; onError: (text: string) => void }) {
  const [form, setForm] = useState({ id: "", name: "", url: "", version: "" });
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    onError("");
    try {
      onDone(await appsApi.registerExternal({ id: form.id.trim(), name: form.name.trim(), url: form.url.trim(), version: form.version.trim() || null }));
      setForm({ id: "", name: "", url: "", version: "" });
    } catch (err) { onError(message(err)); }
    setBusy(false);
  }
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm({ ...form, [key]: event.target.value });
  return <article className="panel apps-way pc-span-2">
    <h2><Link2 size={17} /> {t("Register external app")}</h2>
    <p className="apps-warn"><ShieldAlert size={15} /> {t("For an app already running elsewhere. It appears in the launcher and gets an app key, but PlantCraft does not verify its code.")}</p>
    <form className="apps-form" onSubmit={submit}>
      <label>{t("Id")}<input required value={form.id} pattern="[a-z][a-z0-9]{2,30}" maxLength={31} placeholder="historian" onChange={set("id")} /></label>
      <label>{t("Name")}<input required value={form.name} maxLength={60} placeholder={t("E.g. Historian viewer")} onChange={set("name")} /></label>
      <label>{t("Address")}<input required value={form.url} maxLength={300} placeholder="https://host/path/ or /path/" onChange={set("url")} /></label>
      <label>{t("Version (optional)")}<input value={form.version} maxLength={40} placeholder="1.0.0" onChange={set("version")} /></label>
      <button className="button button-secondary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Link2 size={15} />} {t("Register")}</button>
    </form>
  </article>;
}

function PreviewPanel({ preview, busy, onInstall, onCancel }: { preview: PackagePreview; busy: boolean; onInstall: () => void; onCancel: () => void }) {
  const { app, sbom } = preview;
  return <section className="panel apps-preview" aria-labelledby="apps-preview-title">
    <header>
      <div><span className="eyebrow"><ShieldCheck size={13} /> {t("Signature and SHA-256 checked")}</span><h2 id="apps-preview-title">{app.name} <code>{app.version}</code></h2><p className="apps-summary">{app.summary}</p>{app.description && app.description !== app.summary && <p>{app.description}</p>}</div>
      <button className="icon-button" onClick={onCancel} aria-label={t("Cancel")}><X /></button>
    </header>
    <dl className="apps-facts">
      <dt>{t("Publisher")}</dt><dd>{app.publisher.name} <code>{app.publisher.id}</code> · {t("key {key}", { key: app.publisher.key_id ?? "" })}</dd>
      {app.category && <><dt>{t("Category")}</dt><dd>{app.category}</dd></>}
      <dt>{t("Address")}</dt><dd><code>{app.prefix}</code> → {t("port {port} inside its container, user {uid}", { port: app.port, uid: app.uid })}</dd>
      {app.license && <><dt>{t("Licence")}</dt><dd>{app.license}</dd></>}
      <dt>{t("Image")}</dt><dd><code>{app.image}</code></dd>
      <dt>{t("Package")}</dt><dd>{size(app.size)} · <code title={app.sha256}>sha256 {app.sha256.slice(0, 16)}…</code></dd>
      <dt>{t("Origin")}</dt><dd>{ORIGINS[preview.origin] ?? preview.origin}{preview.replaces ? ` · ${t("replaces {version}", { version: preview.replaces })}` : ""}</dd>
    </dl>
    <h3>{t("Permissions it asks for")}</h3>
    <ul className="apps-perms">
      {app.permissions.map((item) => <li key={item.id}><KeyRound size={13} /> {item.label} <code>{item.id}</code></li>)}
      <li><ShieldCheck size={13} /> {t("Never writes to the plant")} <code>plant_write = false</code></li>
      <li><ShieldCheck size={13} /> {t("Contacts no outside host")} <code>outbound = []</code></li>
    </ul>
    <h3>{t("What it adds to PlantCraft")}</h3>
    <p>{addsText(app.adds) || t("Nothing: it adds no widgets, search, uses of a language model or series.")}</p>
    <h3>{t("Software bill of materials")}</h3>
    <p>{t("{format}, {count} components.", { format: sbom.format, count: sbom.packages })} <a href={appsApi.packageSbomUrl(preview.upload_id)} target="_blank" rel="noreferrer">{t("Open the SBOM")}</a></p>
    {sbom.components.length > 0 && <DataTable rows={sbom.components} columns={SBOM_COLUMNS} rowKey={(item) => `${item.name}@${item.version}`} searchText={(item) => `${item.name} ${item.version} ${item.license}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "name", descending: false }} label={t("Software bill of materials")} className="apps-sbom" />}
    {preview.warnings.map((text) => <div key={text} className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {text}</div>)}
    {!preview.installer.online && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("The installer is not running: the install starts when it does.")}</div>}
    <footer className="apps-preview-actions">
      <button className="button button-secondary" onClick={onCancel} disabled={busy}>{t("Cancel")}</button>
      <button className="button button-primary" onClick={onInstall} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />} {preview.replaces ? t("Update to {version}", { version: app.version }) : t("Install {name}", { name: app.name })}</button>
    </footer>
  </section>;
}

/** The suite's order, as the menu draws it; apps it does not know after, as listed. */
type SbomComponent = PackagePreview["sbom"]["components"][number];
const SBOM_COLUMNS: DataColumn<SbomComponent>[] = [
  { key: "name", label: t("Component"), sort: (item) => item.name },
  { key: "version", label: t("Version"), sort: (item) => item.version },
  { key: "license", label: t("License"), sort: (item) => item.license, filter: true },
];

/** A suite app by the name the suite gives it today ("PlantCraft Analytics"), whatever its
 * manifest still says ("PlantCraft Analytics"); another app by its own name. */
export function suiteName(app: Pick<InstalledApp, "id" | "name">): string {
  const family = appIdFor(app.id);
  return family ? appFullName(family) : app.name;
}

function suiteRank(app: InstalledApp): number {
  const at = SUITE_ORDER.indexOf(appIdFor(app.id) ?? "");
  return at < 0 ? SUITE_ORDER.length : at;
}

function InstalledTable({ apps, busy, installEnabled, onAct }: { apps: InstalledApp[]; busy: string; installEnabled: boolean; onAct: (label: string, run: () => Promise<unknown>, done?: string) => Promise<void> }) {
  const labelled = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }));
  const columns: DataColumn<InstalledApp>[] = [
    { key: "name", label: t("App"), sort: (app) => suiteRank(app), render: (app) => <><strong>{suiteName(app)}</strong><small className="apps-sub"><code>{app.url}</code></small></> },
    { key: "version", label: t("Version"), sort: (app) => app.version, render: (app) => <>{app.version ?? "—"}{app.previous_version ? <small className="apps-sub">{t("previous {version}", { version: app.previous_version })}</small> : null}</> },
    { key: "publisher", label: t("Publisher"), sort: (app) => app.publisher.name || app.publisher.id, render: (app) => app.publisher.name || app.publisher.id || "—", filter: { value: (app) => app.publisher.name || app.publisher.id || "" } },
    { key: "origin", label: t("Origin"), sort: (app) => ORIGINS[app.origin] ?? app.origin, filter: { options: labelled(ORIGINS), value: (app) => app.origin }, render: (app) => <><span className={`apps-origin apps-origin-${app.origin}`}>{ORIGINS[app.origin] ?? app.origin}</span>{app.origin === "external" && <small className="apps-sub apps-warn-text">{t("Code not verified by PlantCraft")}</small>}</> },
    { key: "adds", label: t("Adds"), sort: (app) => addsText(app.adds), render: (app) => app.adds === null || app.adds === undefined
      ? <small className="muted">{t("Not told yet")}</small>
      : <>{addsText(app.adds) || <span className="muted">—</span>}{app.adds_unknown?.length ? <small className="apps-sub apps-warn-text">{t("Newer than this PlantCraft: {list}", { list: app.adds_unknown.join(", ") })}</small> : null}</> },
    { key: "status", label: t("Status"), sort: (app) => STATUSES[app.status] ?? app.status, filter: { options: labelled(STATUSES), value: (app) => app.status }, render: (app) => <><span className={`apps-state apps-state-${app.status}`}>{PENDING.has(app.status) && <LoaderCircle className="spin" size={13} />}{STATUSES[app.status] ?? app.status}</span>
      {app.message && <small className="apps-sub">{app.message}</small>}
      {app.health && <small className="apps-sub">{app.health.detail}</small>}</> },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions apps-actions", render: (app) => {
      const pending = PENDING.has(app.status);
      const managed = app.origin === "package" || app.origin === "catalog";
      return <>
        {app.has_sbom && <a className="icon-button" href={appsApi.sbomUrl(app.id)} target="_blank" rel="noreferrer" title={t("SBOM")} aria-label={t("SBOM of {name}", { name: app.name })}><Package size={15} /></a>}
        {managed && app.needs_key && <button className="icon-button" disabled={pending || !installEnabled || !!busy} title={t("Give it an app key")} onClick={() => void onAct(`key-${app.id}`, () => appsApi.giveKey(app.id))}><KeyRound size={15} /></button>}
        {managed && app.previous_version && <button className="icon-button" disabled={pending || !installEnabled || !!busy} title={t("Roll back to {version}", { version: app.previous_version })} aria-label={t("Roll back {name}", { name: app.name })} onClick={async () => { if ((await confirmAction(t("Return {name} to version {version}?", { name: app.name, version: app.previous_version ?? "" }), { confirm: t("Roll back"), danger: false }))) void onAct(`rollback-${app.id}`, () => appsApi.rollback(app.id)); }}><RotateCcw size={15} /></button>}
        {app.origin === "external" && <button className="icon-button" disabled={!!busy} title={t("Check its address")} onClick={() => void onAct(`check-${app.id}`, () => appsApi.check(app.id))}><RefreshCw size={15} /></button>}
        {(managed || app.origin === "external") && <button className="icon-button" disabled={pending || (managed && !installEnabled) || !!busy} title={managed ? t("Uninstall") : t("Remove")} aria-label={t("Uninstall {name}", { name: app.name })} onClick={async () => { if ((await confirmAction(managed ? t("Uninstall {name}? Its data on the server is kept.", { name: app.name }) : t("Remove {name} from the launcher?", { name: app.name }), { confirm: managed ? t("Uninstall") : t("Remove"), danger: true }))) void onAct(`remove-${app.id}`, () => appsApi.uninstall(app.id)); }}>{managed ? <Trash2 size={15} /> : <Ban size={15} />}</button>}
      </>;
    } },
  ];
  return <section className="apps-installed" aria-labelledby="apps-installed-title">
    <h2 id="apps-installed-title" className="section-title">{t("Installed apps")}</h2>
    {!apps.length ? <p className="muted">{t("No apps yet. Install one from a file or the catalog.")}</p>
      : <DataTable rows={apps} columns={columns} rowKey={(app) => app.id} searchText={(app) => `${app.name} ${app.id} ${app.url} ${app.version ?? ""}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "name", descending: false }} label={t("Installed apps")} />}
  </section>;
}
