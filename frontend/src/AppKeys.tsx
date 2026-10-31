/** App keys: what an app of the suite uses to ask PlantCraft for a service token (admins only). */
import { AlertTriangle, Ban, Copy, KeyRound, LoaderCircle, Plus } from "lucide-react";
import { DataTable, confirmAction, Heading } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AppTabs } from "./AppTabs";
import { appLabel } from "./appMarks";
import { locale, t } from "./i18n";
import { suiteApi, type AppKeyList, type NewAppKey } from "./suiteApi";

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function when(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function AppKeysSection() {
  const [data, setData] = useState<AppKeyList | null>(null);
  const [error, setError] = useState("");
  const [appId, setAppId] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<NewAppKey | null>(null);
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => suiteApi.appKeys().then(setData).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setCreated(await suiteApi.createAppKey(appId.trim(), label.trim()));
      setCopied(false);
      setLabel("");
      await load();
    } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  async function revoke(keyId: string, app: string) {
    if (!(await confirmAction(t("Revoke this key of {app}? The app stops reaching PlantCraft until it gets a new key.", { app }), { confirm: t("Revoke"), danger: true }))) return;
    try {
      await suiteApi.revokeAppKey(keyId);
      if (created?.key_id === keyId) setCreated(null);
      await load();
    } catch (err) { setError(message(err)); }
  }
  async function copy(key: string) {
    try { await navigator.clipboard.writeText(key); setCopied(true); } catch { setCopied(false); }
  }
  const appName = (id: string) => appLabel(id, data?.apps.find((app) => app.id === id)?.name ?? id);

  return <section className="panel ac-users ac-keys" aria-labelledby="app-keys-title">
    <header className="ac-keys-head">
      <div><h2 id="app-keys-title"><KeyRound size={17} /> {t("App keys")}</h2><p>{t("An app key is the password an app of the suite (Analytics, View, Historian and others) uses to talk to the platform when no person is signed in: rounds, imports, background checks. Installing an app creates its key, so you rarely need this page. Create one by hand for an app installed on another machine (it goes in the app as PLANTCRAFT_APP_KEY), or to replace a key that may have leaked: create the new one, then revoke the old. The key is shown once; only its fingerprint is kept.")}</p></div>
    </header>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {created && <div className="ac-notice ac-key-reveal">
      <KeyRound size={15} />
      <span><strong>{t("New key for {app}. Copy it now: it will not be shown again.", { app: appName(created.app_id) })}</strong><code>{created.key}</code></span>
      <button type="button" className="button button-secondary" onClick={() => void copy(created.key)}><Copy size={15} /> {copied ? t("Copied") : t("Copy")}</button>
    </div>}
    <form className="ac-keys-form" onSubmit={create}>
      <label>{t("App")}<input required list="app-key-apps" value={appId} pattern="[a-z][a-z0-9_\-]*" maxLength={40} placeholder="linkcraft" onChange={(event) => setAppId(event.target.value.toLowerCase())} /></label>
      <datalist id="app-key-apps">{(data?.apps ?? []).map((app) => <option key={app.id} value={app.id}>{app.name}</option>)}</datalist>
      <label>{t("Label")}<input value={label} maxLength={120} placeholder={t("E.g. production server")} onChange={(event) => setLabel(event.target.value)} /></label>
      <button className="button button-primary" disabled={busy || !appId.trim()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {t("Create key")}</button>
    </form>
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading keys…")}</span></div>}
    {data && !data.keys.length && <p className="muted ac-keys-empty">{t("No app keys yet.")}</p>}
    {data && data.keys.length > 0 && <DataTable rows={data.keys} rowKey={(key) => key.key_id} label={t("App keys")} rowClassName={(key) => (key.active ? undefined : "ac-inactive")} initialSort={{ key: "created", descending: true }}
      columns={[
        { key: "app", label: t("App"), sort: (key) => appName(key.app_id), filter: { value: (key) => appName(key.app_id) }, render: (key) => <strong>{appName(key.app_id)}</strong> },
        { key: "label", label: t("Label"), sort: (key) => key.label, render: (key) => key.label || "—" },
        { key: "key", label: t("Key"), render: (key) => <code>pck_{key.key_id}…</code> },
        { key: "created", label: t("Created"), sort: (key) => key.created_at, render: (key) => `${when(key.created_at)}${key.created_by ? ` · ${key.created_by}` : ""}` },
        { key: "used", label: t("Last used"), sort: (key) => key.last_used_at, render: (key) => when(key.last_used_at) },
        { key: "status", label: t("Status"), sort: (key) => (key.active ? 0 : 1), filter: { value: (key) => (key.active ? t("Active") : t("Revoked")) }, render: (key) => (key.active ? t("Active") : t("Revoked {date}", { date: when(key.revoked_at) })) },
        { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (key) => key.active && <button className="icon-button" title={t("Revoke")} aria-label={t("Revoke key {key}", { key: key.key_id })} onClick={() => void revoke(key.key_id, appName(key.app_id))}><Ban size={15} /></button> },
      ]} />}
  </section>;
}

/** The App keys page (admins). */
export default function AppKeysPage() {
  return <>
    <Heading title={t("Apps")} />
    <AppTabs current="keys" />
    <AppKeysSection />
  </>;
}
