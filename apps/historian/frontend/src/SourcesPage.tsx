import { appLabel, DataTable, TimeZoneSelect, useAssistantPage, confirmAction, Dialog } from "@plantcraft/ui";
import { Activity, AppWindow, Calculator, ChevronRight, Cpu, Database, Radio, ArrowRight, Download, FileSpreadsheet, FolderSearch, History, Network, Pencil, PlugZap, Plus, Search, Server, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, askCollector, type BrowseResult, type SourceIn } from "./api";
import { GatewayFields, isGateway } from "./GatewaySource";
import { navigate } from "./nav";
import { MODE_LABELS } from "./PointsPage";
import { ago } from "./format";
import { formatNumber, t } from "./i18n";
import { override } from "./levels";
import { isWritten, type Me, type Settings, type Source, type SourceSettings, type Variable } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";

// The plant types an admin adds; derived sources appear when an app first writes, the system
// source when PlantCraft first writes the suite's health.
export const KINDS: Record<string, string> = {
  opcua: "OPC UA server", pi_web_api: "PI Web API", csv: "CSV files", mqtt: "MQTT broker", modbus: "Modbus TCP device", sql: "SQL database", derived: "Written by an app", system: "The suite's health", calc: "Calculated signals", import: "CSV import",
};

/** What each type of source is, in a sentence, and its icon (the type picker and a source's page). */
export const KIND_ABOUT: Record<string, { icon: ReactNode; about: string }> = {
  opcua: { icon: <Network />, about: "A DCS, PLC or SCADA server that speaks OPC UA. Read live every scan, and its own history when it keeps one (Historical Access)." },
  pi_web_api: { icon: <Server />, about: "An AVEVA PI System through PI Web API. Its history is read where it is, on request; nothing is copied unless you ask." },
  csv: { icon: <FileSpreadsheet />, about: "CSV files another application keeps writing: one file, or every file matching a pattern in one folder. Checked every few minutes; new rows are archived. For a file loaded once, use Imports." },
  import: { icon: <FileSpreadsheet />, about: "CSV files loaded from Imports, once or repeated from a folder. Its values are kept until the import is deleted." },
  mqtt: { icon: <Radio />, about: "Values published on an MQTT broker (IIoT sensors, edge gateways, Sparkplug-free topics). The gateway subscribes and Historian archives each topic." },
  modbus: { icon: <Cpu />, about: "A PLC, meter or drive that speaks Modbus TCP. The gateway reads the registers and coils you list every scan period; it never writes them." },
  sql: { icon: <Database />, about: "A database table: LIMS results, MES or ERP figures, another system's values. The gateway runs one SELECT every scan period, with a user that can only read." },
  derived: { icon: <AppWindow />, about: "The series an app of the suite calculates (health of a loop, a model's prediction, an alarm count) and writes here, so every other app and every trend can read them." },
  calc: { icon: <Calculator />, about: "Signals Historian calculates from others with a formula: a conversion, a sum, a condition, a totalizer. Added from the Signals page; the collector evaluates them on every scan." },
  system: { icon: <Activity />, about: "The suite watching itself: every service up or down, its response time, CPU, memory and errors; the free disk; the age of the last backup. PlantCraft writes them every minute and they are kept 90 days." },
};
const PLANT_KINDS = ["opcua", "pi_web_api", "csv", "mqtt", "modbus", "sql"] as const;
/** The page of a source. */
export const sourcePath = (sourceId: string) => `/sources/${encodeURIComponent(sourceId)}`;
/** The app that writes a derived source (`app-cpmcraft` -> `cpmcraft`). */
export const appOfSource = (sourceId: string) => (sourceId.startsWith("app-") ? sourceId.slice(4) : sourceId);
/** A source's name as the suite shows it: a derived source by its app's name ("Link"). */
export const sourceName = (source: Pick<Source, "id" | "kind" | "name">) => (source.kind === "derived" ? appLabel(appOfSource(source.id), source.name) : source.kind === "system" ? t("System") : source.name);
const PI_AUTH = ["kerberos", "ntlm", "basic"];
// OPC UA secure channel (G2): the modes and policies Historian speaks.
const SECURITY_MODES: Record<string, string> = { None: "None (no signing)", Sign: "Sign", SignAndEncrypt: "Sign and encrypt" };
const SECURITY_POLICIES = ["Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss"];
/** A server certificate as the collector found it (a secure source's Test before it is trusted). */
type Certificate = { thumbprint: string; subject: string; issuer: string; not_before: string; not_after: string };
// What a new source of each kind starts with (the server fills the other options).
const START: Record<string, Pick<Source, "endpoint" | "options">> = {
  opcua: { endpoint: "opc.tcp://", options: { security_mode: "None", security_policy: "Basic256Sha256", server_thumbprint: "" } },
  pi_web_api: { endpoint: "https://", options: { server: "", auth_type: "kerberos", verify_ssl: true } },
  csv: { endpoint: "", options: { timezone: "UTC", check_minutes: 5 } },
  mqtt: { endpoint: "tcp://", options: { topics: [], qos: 0, data_format: "value" } },
  modbus: { endpoint: "tcp://", options: { slave_id: 1, timeout_seconds: 5, registers: [{ name: "", type: "holding_register", address: 0, data_type: "INT16", byte_order: "AB", scale: 1 }] } },
  sql: { endpoint: "", options: { driver: "postgres", query: "", measurement: "sql", time_column: "", tag_columns: [] } },
};
const EMPTY: Source = {
  id: "", name: "", kind: "opcua", ...START.opcua, namespace_uri: "", username: "", password_env: "", has_password: false,
  mode: "archive", default_mode: "archive", enabled: true, points: 0, state: null,
  retention_days: null, default_scan_seconds: null, default_deviation_percent: null, default_max_seconds: null,
};

// What a source may override of the general settings for its points (empty: the general value).
const SOURCE_SETTINGS: { key: keyof SourceSettings; label: string; unit: string; step: string }[] = [
  { key: "retention_days", label: "Retention (days)", unit: "days", step: "1" },
  { key: "default_scan_seconds", label: "Scan period (s)", unit: "s", step: "0.1" },
  { key: "default_deviation_percent", label: "Deviation (% of span)", unit: "%", step: "0.01" },
  { key: "default_max_seconds", label: "Longest interval between archived values (s)", unit: "s", step: "1" },
];

/** What a successful connection test found, in a sentence. */
function tested(source: Source, result: Record<string, unknown> | undefined): string {
  if (source.kind === "pi_web_api") return t("{name} answered: PI server {server}.", { name: source.name, server: String(result?.server ?? "—") });
  if (isGateway(source.kind)) return t("{name}: the gateway sent {count} series.", { name: source.name, count: Number(result?.series ?? 0) });
  if (source.kind === "csv") return result?.files ? t("{name}: {files} files, {tags} tags in the newest.", { name: source.name, files: Number(result.files), tags: Number(result?.tags ?? 0) }) : String(result?.detail ?? t("{name}: no file yet.", { name: source.name }));
  const namespaces = result?.namespaces;
  return t("{name} answered: {count} namespaces.", { name: source.name, count: Array.isArray(namespaces) ? namespaces.length : 0 });
}

/** Test, backfill, edit, browse and remove a source: the Sources list and a source's page share them. */
export function useSourceActions(reload: () => unknown, afterRemove?: () => void) {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<{ source: Source; create: boolean } | null>(null);
  const [browsing, setBrowsing] = useState<Source | null>(null);
  const [testing, setTesting] = useState("");
  // A secure OPC UA server whose certificate waits for an admin's trust.
  const [trusting, setTrusting] = useState<{ source: Source; certificate: Certificate } | null>(null);

  async function test(source: Source) {
    setTesting(source.id); setMessage(""); setError(""); setTrusting(null);
    try {
      const answer = await askCollector<Record<string, unknown>>(() => api.testSource(source.id), 60_000);
      if (answer.status === "ok") setMessage(tested(source, answer.result));
      else {
        const certificate = answer.result?.certificate as Certificate | undefined;
        if (certificate) setTrusting({ source, certificate });
        setError(t("{name} did not answer: {detail}", { name: source.name, detail: answer.result?.detail ?? "" }));
      }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setTesting(""); }
  }

  async function trust() {
    if (!trusting) return;
    try {
      await api.trustServer(trusting.source.id, trusting.certificate.thumbprint);
      setTrusting(null); setError("");
      setMessage(t("{name}'s certificate is trusted. The collector connects within seconds.", { name: trusting.source.name }));
      await reload();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  async function backfill(source: Source) {
    const answer = window.prompt(t("Copy {name}'s own history into the archive, up to where archiving began. How many hours back?", { name: source.name }), "48");
    const hours = Number(answer);
    if (answer === null || !Number.isFinite(hours) || hours <= 0) return;
    setTesting(source.id); setError("");
    setMessage(t("Backfilling {name}: the collector reads its history in the background.", { name: source.name }));
    try {
      const done = await askCollector<{ signals: number; values: number; failed: number }>(() => api.backfillSource(source.id, hours), 30 * 60_000);
      if (done.status === "ok") setMessage(t("Backfill of {name}: {values} values of {signals} signals archived ({failed} failed).", { name: source.name, values: formatNumber(done.result?.values ?? 0, 0), signals: done.result?.signals ?? 0, failed: done.result?.failed ?? 0 }));
      else { setMessage(""); setError(t("{name} did not answer: {detail}", { name: source.name, detail: (done.result as { detail?: string } | undefined)?.detail ?? "" })); }
    } catch (err) { setMessage(""); setError(err instanceof Error ? err.message : String(err)); } finally { setTesting(""); }
  }

  async function remove(source: Source) {
    // A retired app's source goes with its points and their history (nothing else writes them).
    const retired = !!source.retired_into;
    const question = retired
      ? t("Remove {name} with its {count} signals and their history? This cannot be undone.", { name: sourceName(source), count: source.points })
      : t("Remove the source {name}?", { name: source.name });
    if (!(await confirmAction(question, { confirm: t("Remove"), danger: true }))) return;
    try { await api.deleteSource(source.id, retired); afterRemove?.(); await reload(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  const dialogs = <>
    {editing && <SourceForm initial={editing.source} create={editing.create} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} />}
    {browsing && <BrowseDialog source={browsing} onClose={() => setBrowsing(null)} onAdded={(count) => { setBrowsing(null); setMessage(t("{count} signals added. The collector starts reading them within seconds.", { count })); void reload(); }} />}
  </>;
  const notices = <>
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    {trusting && <div className="panel trust-card" role="region" aria-label={t("Server certificate")}>
      <h3>{t("Trust this server certificate?")}</h3>
      <p className="muted">{t("Compare the thumbprint with the one the server's administrator sees. Once trusted, a server presenting another certificate is refused.")}</p>
      <dl className="facts">
        <dt>{t("SHA-256")}</dt><dd className="pc-mono">{trusting.certificate.thumbprint}</dd>
        <dt>{t("Subject")}</dt><dd>{trusting.certificate.subject}</dd>
        <dt>{t("Issuer")}</dt><dd>{trusting.certificate.issuer}</dd>
        <dt>{t("Valid")}</dt><dd>{trusting.certificate.not_before.slice(0, 10)} – {trusting.certificate.not_after.slice(0, 10)}</dd>
      </dl>
      <div className="row-actions"><button className="button button-primary" onClick={() => void trust()}><ShieldCheck size={15} />{t("Trust")}</button>
        <button className="button button-secondary" onClick={() => setTrusting(null)}>{t("Not now")}</button></div>
    </div>}
  </>;
  return { error, setError, notices, dialogs, setEditing, setBrowsing, testing, test, backfill, remove };
}

/** The buttons of a source: browse, test, backfill (OPC UA), edit, remove; a derived source has none
 * but Remove when its app was merged into another. `compact` (the sources table) draws them as
 * icons, so a row with every button still fits beside the columns. */
export function SourceActions({ source, me, actions, open, compact = false }: { source: Source; me: Me; actions: ReturnType<typeof useSourceActions>; open?: boolean; compact?: boolean }) {
  // Calculated points have no connection to browse, test or set up: only their settings.
  // An import (listed while it repeats from a folder) is set up and deleted in Imports.
  const plant = !isWritten(source.kind) && source.kind !== "calc" && source.kind !== "import";
  const tool = (label: string, title: string, icon: ReactNode, onClick: () => void, disabled = false) => compact
    ? <button className="icon-button" aria-label={label} title={title} disabled={disabled} onClick={onClick}>{icon}</button>
    : <button className="button button-secondary" title={title} disabled={disabled} onClick={onClick}>{icon}{label}</button>;
  return <div className="row-actions">
    {plant && me.can_edit && tool(t("Browse"), t("Browse the source's variables"), <FolderSearch size={compact ? 16 : 15} />, () => actions.setBrowsing(source))}
    {plant && me.can_edit && tool(t("Test"), t("Test the connection"), <PlugZap size={compact ? 16 : 15} className={actions.testing === source.id ? "spin" : ""} />, () => void actions.test(source), !!actions.testing)}
    {source.kind === "opcua" && me.is_admin && tool(t("Backfill"), t("Copy the source's own history into the archive"), <History size={compact ? 16 : 15} />, () => void actions.backfill(source), !!actions.testing)}
    {plant && me.is_admin && <button className="icon-button" aria-label={t("Edit")} title={t("Edit")} onClick={() => actions.setEditing({ source, create: false })}><Pencil size={16} /></button>}
    {(plant || source.kind === "calc" || !!source.retired_into) && me.is_admin && <button className="icon-button danger" aria-label={t("Remove")} title={t("Remove")} onClick={() => void actions.remove(source)}><Trash2 size={16} /></button>}
    {source.kind === "import" && <Link to="/imports" className="button button-secondary">{t("Imports")}<ArrowRight size={15} /></Link>}
    {open && <Link to={sourcePath(source.id)} className="button button-secondary">{t("Open")}<ArrowRight size={15} /></Link>}
  </div>;
}

/** The folder an import repeats from (Imports): such an import is listed
 * with the sources, as it keeps bringing data in; '' for any other source. */
export function repeatsFrom(source: Source): string {
  const repeat = source.options?.repeat as { pattern?: string } | undefined;
  return source.kind === "import" && repeat?.pattern ? repeat.pattern : "";
}

/** How the collector reaches a source now. */
export function Connection({ source }: { source: Source }) {
  if (!source.enabled) return <Pill status="disabled" label={t("Disabled")} />;
  if (source.kind === "derived" && source.retired_into) return <><Pill status="disabled" label={t("App retired")} /><small>{t("Its work moved to {app}; nothing writes here any more.", { app: appLabel(source.retired_into, source.retired_into) })}</small></>;
  if (source.kind === "derived") return <span className="muted">{t("Written by its app")}</span>;
  if (source.kind === "system") return <span className="muted">{t("Written by PlantCraft")}</span>;
  if (source.kind === "import" && repeatsFrom(source)) return <><Pill status="connected" label={t("Repeats")} /><small className="pc-mono">{repeatsFrom(source)}</small></>;
  if (source.kind === "import") return <span className="muted">{t("Imported once")}</span>;
  if (!source.state) return <Pill status="waiting" label={t("Waiting")} />;
  if (source.kind === "calc") return <><Pill status={source.state.status} label={t(source.state.status === "connected" ? "Calculating" : "Stopped")} /><small>{source.state.detail || ago(source.state.since)}</small></>;
  if (source.kind === "csv" && source.state.status === "connected") return <><Pill status="connected" label={t("Watching")} /><small>{source.state.detail || t("Checked {ago}", { ago: ago(source.state.checked ?? source.state.since) })}</small></>;
  return <><Pill status={source.state.status} label={t(source.state.status === "connected" ? "Connected" : "Disconnected")} /><small>{source.state.detail || ago(source.state.since)}</small></>;
}

/** In a few words, what each plant type connects to (the type picker's list). */
const KIND_HINT: Record<typeof PLANT_KINDS[number], string> = {
  opcua: "DCS, PLC or SCADA",
  pi_web_api: "AVEVA PI System",
  csv: "Files another application keeps writing",
  mqtt: "IIoT sensors, edge gateways",
  modbus: "PLC, meter or drive",
  sql: "LIMS, MES or ERP table",
};

/** Add source, first step: which type of source (the type first, then its
 * form), as a plain list (whoever adds a source knows what it is). */
function TypePicker({ onPick, onClose }: { onPick: (kind: typeof PLANT_KINDS[number]) => void; onClose: () => void }) {
  return <Dialog title={t("Add source: which type?")} onClose={onClose}>
      <ul className="type-list" aria-label={t("Source types")}>
        {PLANT_KINDS.map((kind) => <li key={kind}><button type="button" onClick={() => onPick(kind)}>
          <span className="type-icon" aria-hidden="true">{KIND_ABOUT[kind].icon}</span>
          <span className="type-name"><b>{t(KINDS[kind])}</b><small>{t(KIND_HINT[kind])}</small></span>
          <ChevronRight size={16} aria-hidden="true" />
        </button></li>)}
      </ul>
      <p className="muted small">{t("Series the apps calculate appear as sources by themselves, the first time each app writes.")}</p>
      <footer><button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button></footer>
  </Dialog>;
}

export function SourcesPage({ me }: { me: Me }) {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState("");
  const [choosing, setChoosing] = useState(false);
  // Imports have their own page.
  const load = () => api.sources().then((answer) => { setSources(answer.filter((source) => source.kind !== "import" || !!repeatsFrom(source))); }).catch((err: Error) => setError(err.message));
  const actions = useSourceActions(load);
  // The Historian's works here (app.toml): ask about the sources.
  useAssistantPage({ place: t("Historian › Sources"), page: "histcraft:sources",
    view: { sources: (sources ?? []).map((item) => `${item.id} (${item.kind}${item.enabled ? "" : ", off"}): ${item.points} points, ${item.state?.status ?? "unknown"}${item.state?.detail ? ` ${item.state.detail.slice(0, 80)}` : ""}`) } });
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 10_000); return () => window.clearInterval(timer); }, []);
  if (!sources && error) return <ErrorBox text={error} />;
  if (!sources) return <Loading />;
  return <>
    <Heading
      eyebrow={t("Historian")}
      title={t("Sources")}
      detail={t("Connections to plant systems, and the series apps write. Historian only reads from plant systems; it never writes to them.")}
      actions={me.is_admin && <button className="button button-primary" onClick={() => setChoosing(true)}><Plus size={16} />{t("Add source")}</button>}
    />
    {actions.notices}
    {error && <ErrorBox text={error} />}
    {sources.length === 0
      ? <div className="panel empty"><h2>{t("No source yet")}</h2><p>{me.is_admin ? t("Add a source, then browse it to choose the signals to archive.") : t("An administrator adds the sources.")}</p></div>
      : <DataTable
        rows={sources}
        rowKey={(source) => source.id}
        label={t("Sources")}
        searchText={(source) => `${source.id} ${source.name} ${t(KINDS[source.kind] ?? source.kind)} ${source.endpoint}`}
        searchPlaceholder={t("Filter sources")}
        onRowClick={(source) => navigate(sourcePath(source.id))}
        columns={[
          { key: "name", label: t("Source"), sort: (source) => sourceName(source), render: (source) => <><Link to={sourcePath(source.id)} className="strong">{sourceName(source)}</Link><small className="pc-mono">{source.id}</small></> },
          { key: "kind", label: t("Type"), sort: (source) => t(KINDS[source.kind] ?? source.kind), filter: { value: (source) => t(KINDS[source.kind] ?? source.kind) }, render: (source) => <>{t(KINDS[source.kind] ?? source.kind)}{!isWritten(source.kind) && <small className="pc-mono">{source.endpoint}</small>}{source.username && <small>{t("as {user}", { user: source.username })}</small>}</> },
          { key: "mode", label: t("Mode"), sort: (source) => t(MODE_LABELS[source.mode] ?? source.mode), filter: { value: (source) => t(MODE_LABELS[source.mode] ?? source.mode) }, render: (source) => <>{t(MODE_LABELS[source.mode] ?? source.mode)}<small>{source.mode === source.default_mode ? t("default for this type") : t("set on the source")}</small></> },
          { key: "settings", label: t("Signal settings"), render: (source) => (!isWritten(source.kind) ? <SettingsSummary source={source} /> : <span className="muted">—</span>) },
          { key: "state", label: t("Connection"), render: (source) => <Connection source={source} /> },
          { key: "points", label: t("Signals"), numeric: true, sort: (source) => source.points },
          { key: "actions", label: "", render: (source) => <SourceActions source={source} me={me} actions={actions} open={isWritten(source.kind)} compact /> },
        ]}
      />}
    {choosing && <TypePicker onClose={() => setChoosing(false)} onPick={(kind) => { setChoosing(false); actions.setEditing({ source: { ...EMPTY, kind, ...START[kind] }, create: true }); }} />}
    {actions.dialogs}
  </>;
}

/** The general settings this source overrides for its points, or "General settings". */
function SettingsSummary({ source }: { source: Source }) {
  const own = SOURCE_SETTINGS.filter(({ key }) => source[key] !== null && source[key] !== undefined);
  if (!own.length) return <span className="muted">{t("General settings")}</span>;
  return <>{own.map(({ key, label, unit }) => <small key={key} className="setting-line">{t(label.replace(/ \(.*\)$/, ""))}: <b className="pc-num">{source[key]} {t(unit)}</b></small>)}</>;
}

function SourceForm({ initial, create, onClose, onSaved }: { initial: Source; create: boolean; onClose: () => void; onSaved: () => void }) {
  // The row carries the effective mode: the kind's default shows as "Source default".
  const [draft, setDraft] = useState<SourceIn>({
    id: initial.id, name: initial.name, kind: initial.kind, endpoint: initial.endpoint, namespace_uri: initial.namespace_uri,
    username: initial.username, password_env: initial.password_env, options: { ...initial.options }, enabled: initial.enabled,
    mode: initial.mode === initial.default_mode ? "" : initial.mode, password: null,
    retention_days: initial.retention_days, default_scan_seconds: initial.default_scan_seconds,
    default_deviation_percent: initial.default_deviation_percent, default_max_seconds: initial.default_max_seconds,
  });
  // Typed text of the overrides; empty takes the general setting.
  const [levels, setLevels] = useState<Record<string, string>>(() => Object.fromEntries(SOURCE_SETTINGS.map(({ key }) => [key, initial[key] === null || initial[key] === undefined ? "" : String(initial[key])])));
  const [general, setGeneral] = useState<Settings | null>(null);
  useEffect(() => { api.settings().then(setGeneral).catch(() => undefined); }, []);
  // Typed only; empty on edit keeps the stored password.
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const field = (key: "id" | "name" | "endpoint" | "namespace_uri" | "username" | "password_env") =>
    ({ value: draft[key], onChange: (event: { target: { value: string } }) => setDraft({ ...draft, [key]: event.target.value }) });
  const option = (key: string) => ({ value: String(draft.options[key] ?? ""), onChange: (event: { target: { value: string } }) => setDraft({ ...draft, options: { ...draft.options, [key]: event.target.value } }) });
  const csv = draft.kind === "csv";
  const secureMode = String(draft.options.security_mode ?? "None");
  async function save() {
    setError("");
    const payload: SourceIn = {
      ...draft, mode: csv ? "" : draft.mode, password: password || null,
      options: csv ? { ...draft.options, check_minutes: Number(draft.options.check_minutes ?? 5) } : draft.options,
      ...Object.fromEntries(SOURCE_SETTINGS.map(({ key }) => [key, override(levels[key])])) as SourceSettings,
    };
    try {
      if (create) await api.addSource(payload); else await api.updateSource(payload);
      onSaved();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  const passwordFields = <>
    <label>{t("User (optional)")}<input {...field("username")} autoComplete="off" /></label>
    <label>{t("Password")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" placeholder={!create && initial.has_password ? t("stored") : ""} />
      <small>{!create && initial.has_password ? t("A password is stored. Leave empty to keep it.") : t("Stored encrypted; never shown again.")}</small></label>
    <label>{t("Password variable (advanced)")}<input {...field("password_env")} placeholder="HISTCRAFT_SECRET_PLANT_A" /><small>{t("Or read the password from this environment variable of the collector.")}</small></label>
  </>;
  return <Dialog title={create ? t("Add source: {type}", { type: t(KINDS[draft.kind]) }) : t("Edit source")} onClose={onClose}>
      {error && <ErrorBox text={error} />}
      <p className="form-type"><span className="card-icon">{KIND_ABOUT[draft.kind].icon}</span><span>{t(KIND_ABOUT[draft.kind].about)}</span></p>
      <div className="form-grid">
        <label>{t("Id")}<input {...field("id")} disabled={!create} placeholder="plant-a" /><small>{t("Lowercase letters, digits, - and _.")}</small></label>
        <label>{t("Name")}<input {...field("name")} placeholder={t("Unit 100 controller")} /></label>
        <label>{t("Mode")}<select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as SourceIn["mode"] })}>
          <option value="">{t("Source default")}</option>
          {Object.keys(MODE_LABELS).filter((mode) => (csv || isGateway(draft.kind) ? mode === "archive" : true)).map((mode) => <option key={mode} value={mode}>{t(MODE_LABELS[mode])}</option>)}
        </select><small>{csv ? t("New rows are archived as the files change.") : isGateway(draft.kind) ? t("The gateway sends values as they are read; they exist only in the archive.") : t("Where the history of its signals comes from, unless a signal sets its own.")}</small></label>
        {draft.kind === "opcua" && <>
          <label>{t("Endpoint")}<input {...field("endpoint")} /><small>{t("opc.tcp://host:port/path")}</small></label>
          <label>{t("Namespace URI (optional)")}<input {...field("namespace_uri")} /><small>{t("Browse only this namespace.")}</small></label>
          {passwordFields}
          <label>{t("Security")}<select value={secureMode} onChange={(event) => setDraft({ ...draft, options: { ...draft.options, security_mode: event.target.value } })}>
            {Object.entries(SECURITY_MODES).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
          </select><small>{t("Sign or encrypt the channel. The server must trust Historian's certificate.")}{" "}
            <button type="button" className="link-button" onClick={() => void api.clientCertificate().catch((err: Error) => setError(err.message))}><Download size={13} />{t("Download Historian's certificate")}</button></small></label>
          {secureMode !== "None" && <>
            <label>{t("Security policy")}<select value={String(draft.options.security_policy ?? "Basic256Sha256")} onChange={(event) => setDraft({ ...draft, options: { ...draft.options, security_policy: event.target.value } })}>
              {SECURITY_POLICIES.map((name) => <option key={name} value={name}>{name}</option>)}
            </select></label>
            <label>{t("Trusted server certificate (SHA-256)")}<input {...option("server_thumbprint")} placeholder="AB:CD:…" className="pc-mono" />
              <small>{t("Empty: Test shows the server's certificate and an admin trusts it there.")}</small></label>
          </>}
        </>}
        {draft.kind === "pi_web_api" && <>
          <label>{t("Endpoint")}<input {...field("endpoint")} /><small>{t("The PI Web API base URL: https://host/piwebapi")}</small></label>
          <label>{t("PI Data Archive server")}<input {...option("server")} /></label>
          <label>{t("Authentication")}<select {...option("auth_type")}>{PI_AUTH.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select></label>
          {passwordFields}
          <label className="check"><input type="checkbox" checked={draft.options.verify_ssl !== false} onChange={(event) => setDraft({ ...draft, options: { ...draft.options, verify_ssl: event.target.checked } })} />{t("Verify the server certificate")}</label>
        </>}
        {isGateway(draft.kind) && <GatewayFields draft={draft} setDraft={setDraft} passwordFields={passwordFields} />}
        {csv && <>
          <label>{t("File or pattern")}<input {...field("endpoint")} placeholder="/csv/lims/*.csv" className="pc-mono" />
            <small>{t("One file, or a pattern in one folder (* and ? in the file name). Files are only read, never moved or changed. For a file loaded once, use Imports.")}</small></label>
          <label>{t("Check every (minutes)")}<input type="number" min="0.5" max="1440" step="0.5" {...option("check_minutes")} /><small>{t("How often the files are checked for new rows.")}</small></label>
          <label>{t("Time zone")}<TimeZoneSelect value={String(draft.options.timezone ?? "UTC")} withLocal={false} onChange={(zone) => setDraft({ ...draft, options: { ...draft.options, timezone: zone } })} /><small>{t("For times without an offset. Everything is stored in UTC.")}</small></label>
        </>}
        <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />{t("Collect from this source")}</label>
      </div>
      <section className="source-levels" aria-label={t("Signal defaults for this source")}>
        <h3>{t("Signal defaults for this source")}</h3>
        <p className="muted">{t("Empty fields take the general settings. A signal's own value wins over these.")}</p>
        <div className="form-grid">{SOURCE_SETTINGS.map(({ key, label, unit, step }) => <label key={key}>{t(label)}
          <input type="number" min="0" step={step} value={levels[key] ?? ""} placeholder={general ? String(general[key]) : ""} onChange={(event) => setLevels({ ...levels, [key]: event.target.value })} />
          <small>{(levels[key] ?? "").trim() !== "" ? t("Set on this source") : general ? t("{value} {unit}, from general settings", { value: general[key], unit: t(unit) }) : t("From general settings")}</small>
        </label>)}</div>
      </section>
      <footer><button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" onClick={() => void save()}>{t("Save")}</button></footer>
  </Dialog>;
}

function BrowseDialog({ source, onClose, onAdded }: { source: Source; onClose: () => void; onAdded: (count: number) => void }) {
  const [result, setResult] = useState<BrowseResult | null>(null);
  const [known, setKnown] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // Empty: the source's scan period, else the general one.
  const [scan, setScan] = useState("");
  // Empty: the default (a share of the range, or of the value when no range is known).
  const [deviation, setDeviation] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.points("", source.id).then((points) => setKnown(new Set(points.map((point) => point.address)))).catch(() => undefined);
    askCollector<BrowseResult>(() => api.browseSource(source.id))
      .then((answer) => answer.status === "ok" && answer.result ? setResult(answer.result) : setError(answer.result?.detail ?? t("Browsing failed.")))
      .catch((err: Error) => setError(err.message));
  }, [source.id]);
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (result?.variables ?? []).filter((item) => !needle || `${item.tag} ${item.path} ${item.description}`.toLowerCase().includes(needle));
  }, [result, query]);
  const fresh = shown.filter((item) => !known.has(item.address));
  const unranged = (result?.variables ?? []).filter((item) => picked.has(item.address) && item.kind !== "text" && !item.step && (item.low === null || item.high === null)).length;
  const toggle = (address: string) => setPicked((now) => { const next = new Set(now); if (next.has(address)) next.delete(address); else next.add(address); return next; });
  async function add() {
    setBusy(true); setError("");
    const chosen = (result?.variables ?? []).filter((item) => picked.has(item.address));
    try {
      const answer = await api.addPoints(chosen.map((item: Variable) => ({
        tag: item.tag, source_id: source.id, address: item.address, name: item.name === "PV" || item.name === "SP" ? item.tag : item.name,
        description: item.description, unit: item.unit, kind: item.kind, step: !!item.step, low: item.low, high: item.high, scan_seconds: Number(scan) || undefined,
        deviation: deviation.trim() !== "" && item.kind !== "text" && !item.step ? Math.max(0, Number(deviation)) : undefined,
      })));
      if (answer.skipped.length) setError(t("{count} skipped: {first}", { count: answer.skipped.length, first: `${answer.skipped[0].tag} (${answer.skipped[0].reason})` }));
      if (answer.added.length) onAdded(answer.added.length);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <Dialog title={t("Browse {name}", { name: source.name })} onClose={onClose} wide>
      {error && <ErrorBox text={error} />}
      {!result && !error && <Loading text={t("The collector is browsing the server…")} />}
      {result && <>
        {result.truncated && <div className="notice">{t("Only the first {limit} variables are listed.", { limit: result.limit })}</div>}
        <div className="toolbar">
          <label className="search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Filter by tag or path")} aria-label={t("Filter")} /></label>
          <button className="button button-secondary" onClick={() => setPicked(new Set(fresh.map((item) => item.address)))}>{t("Select {count} shown", { count: fresh.length })}</button>
          <button className="button button-secondary" onClick={() => setPicked(new Set())}>{t("Clear")}</button>
          <span className="muted">{t("{count} variables", { count: result.variables.length })}</span>
        </div>
        <div className="table-scroll"><table className="table">
          <thead><tr><th><span className="sr-only">{t("Select")}</span></th><th>{t("Tag")}</th><th>{t("Path")}</th><th>{t("Type")}</th><th>{t("Unit")}</th><th>{t("Range")}</th></tr></thead>
          <tbody>{shown.slice(0, 500).map((item) => {
            const archived = known.has(item.address);
            return <tr key={item.address} className={archived ? "" : "clickable"} onClick={() => !archived && toggle(item.address)}>
              <td><input type="checkbox" aria-label={item.tag} disabled={archived} checked={archived || picked.has(item.address)} onChange={() => toggle(item.address)} onClick={(event) => event.stopPropagation()} /></td>
              <td className="pc-mono strong">{item.tag}{archived && <small>{t("already archived")}</small>}</td>
              <td><small>{item.path}</small></td>
              <td>{item.kind === "text" ? t("text") : item.step ? t("on/off") : t("number")}</td>
              <td>{item.unit || "—"}</td>
              <td className="pc-num">{item.low !== null && item.high !== null ? `${item.low} – ${item.high}` : "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>
        {shown.length > 500 && <p className="muted">{t("Showing 500 of {count}; filter to narrow.", { count: shown.length })}</p>}
      </>}
      <footer>
        <label className="inline">{t("Scan every")} <input type="number" min="0.1" step="0.1" value={scan} placeholder={source.default_scan_seconds === null ? t("auto") : String(source.default_scan_seconds)} onChange={(event) => setScan(event.target.value)} className="narrow" /> s</label>
        <label className="inline" title={t("Compression: the archived series never strays more than this from a value read. Empty: the source's or the general share of the range when the server gives one, else of the value.")}>{t("Deviation")} <input type="number" min="0" step="any" value={deviation} placeholder={t("auto")} onChange={(event) => setDeviation(event.target.value)} className="narrow" /></label>
        {!deviation.trim() && unranged > 0 && <span className="muted">{t("{count} picked without a range: compressed to a share of the value", { count: unranged })}</span>}
        <button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button className="button button-primary" disabled={!picked.size || busy} onClick={() => void add()}><Plus size={16} />{t("Add {count} signals", { count: picked.size })}</button>
      </footer>
  </Dialog>;
}
