/** Setup › Apps (administrators): each app's installation settings and its own Setup pages, as
 * the apps declare them ([[contributes.settings]], [[contributes.setup]], docs/app-standard.md
 * 4b). PlantCraft draws them without knowing the app; a secret is never shown again. */
import { FormFooter, FormSection, Heading } from "@plantcraft/ui";
import { AlertTriangle, ExternalLink, LoaderCircle, Puzzle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { setupAppsApi, type AppSetting, type SetupApp } from "./appsApi";
import { errorText } from "./collab";
import { t } from "./i18n";
import { navigate } from "./nav";

type Draft = Record<string, string | boolean>;

function draftOf(app: SetupApp): Draft {
  return Object.fromEntries(app.settings.map((setting) => [setting.key, setting.type === "boolean" ? Boolean(setting.value) : setting.value === null || setting.value === undefined ? "" : String(setting.value)]));
}

/** What to send for one field: a typed value, null for the default, undefined for no change. */
function valueOf(setting: AppSetting, entry: string | boolean): unknown {
  if (setting.type === "boolean") return entry;
  const text = String(entry).trim();
  if (setting.secret) return text ? text : undefined;
  if (!text) return null;
  return setting.type === "number" || setting.type === "integer" ? Number(text) : text;
}

function Field({ setting, value, onChange }: { setting: AppSetting; value: string | boolean; onChange: (value: string | boolean) => void }) {
  const id = `sa-${setting.key}`;
  const hint = [setting.help, setting.unit && t("In {unit}.", { unit: setting.unit })].filter(Boolean).join(" ");
  if (setting.type === "boolean") {
    return <label className="check field-span" htmlFor={id}><input id={id} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /> {setting.title}{hint && <small className="muted"> {hint}</small>}</label>;
  }
  const input = setting.type === "choice"
    ? <select id={id} value={String(value)} onChange={(event) => onChange(event.target.value)}>
      {setting.options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
    : <input id={id} type={setting.secret ? "password" : setting.type === "text" ? "text" : "number"} autoComplete="off"
      step={setting.type === "integer" ? 1 : "any"} min={setting.min ?? undefined} max={setting.max ?? undefined}
      placeholder={setting.secret ? (setting.set ? t("Set: type to replace it") : t("Not set")) : setting.default !== undefined && setting.default !== null ? String(setting.default) : ""}
      value={String(value)} onChange={(event) => onChange(event.target.value)} />;
  return <label htmlFor={id}>{setting.title}{input}{hint && <small className="muted">{hint}</small>}</label>;
}

function AppSettings({ app, onSaved }: { app: SetupApp; onSaved: (app: SetupApp) => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(app));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const initial = draftOf(app);
  const changed = app.settings.filter((setting) => draft[setting.key] !== initial[setting.key]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const values: Record<string, unknown> = {};
    for (const setting of changed) {
      const value = valueOf(setting, draft[setting.key]);
      if (value !== undefined) values[setting.key] = value;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await setupAppsApi.save(app.app, values);
      onSaved(saved); setDraft(draftOf(saved));
      setNotice(t("Saved. {app} reads it the next time it asks.", { app: app.name }));
    } catch (err) { setError(errorText(err)); }
    setBusy(false);
  }
  return <form className="panel form-panel" onSubmit={(event) => void submit(event)} aria-label={app.name}>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice" role="status">{notice}</div>}
    <FormSection id={`sa-${app.app}`} icon={<Puzzle size={16} />} title={app.name} detail={app.version ? t("Version {version}", { version: app.version }) : undefined}>
      {app.settings.length > 0 && <div className="form-grid">
        {app.settings.map((setting) => <Field key={setting.key} setting={setting} value={draft[setting.key]} onChange={(value) => setDraft({ ...draft, [setting.key]: value })} />)}
      </div>}
      {app.pages.length > 0 && <ul>
        {app.pages.map((page) => <li key={page.path}><a href={page.path}><ExternalLink size={13} aria-hidden="true" /> {page.title}</a>{page.description && <small className="muted"> {page.description}</small>}</li>)}
      </ul>}
    </FormSection>
    {app.settings.length > 0 && <FormFooter note={t("Empty puts the app's default back. Every change is in the audit log.")}>
      {changed.length > 0 && <button type="button" className="button button-secondary" onClick={() => setDraft(initial)}>{t("Cancel")}</button>}
      <button className="button button-primary" disabled={busy || !changed.length}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button>
    </FormFooter>}
  </form>;
}

export function SetupAppsPage() {
  const [apps, setApps] = useState<SetupApp[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { setupAppsApi.list().then((value) => setApps(value.apps)).catch((err) => setError(errorText(err))); }, []);
  return <>
    <Heading eyebrow={<><Puzzle size={14} /> {t("Administration")} · <a href="/setup" onClick={(event) => { event.preventDefault(); navigate("/setup"); }}>{t("Settings")}</a></>} title={t("Apps")}
      detail={t("What each app lets you set for this installation, and its own setup pages. Each app declares them; its daily work settings stay in the app.")} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!apps && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {apps && !apps.length && <p className="muted">{t("No app declares installation settings yet.")}</p>}
    {apps?.map((app) => <AppSettings key={app.app} app={app} onSaved={(saved) => setApps(apps.map((item) => (item.app === saved.app ? saved : item)))} />)}
  </>;
}
