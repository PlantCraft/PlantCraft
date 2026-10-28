/** Specialists: the robot users people message (docs/collaboration.md). Admins only; a tab of Users. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, Bot, FlaskConical, LoaderCircle, MessagesSquare, Pencil, Plus, ShieldCheck, Trash2, Users } from "lucide-react";
import { DataTable, PageTabs } from "@plantcraft/ui";
import { Avatar, errorText } from "./collab";
import { collabApi, type Choice, type Specialist, type SpecialistDraft, type SpecialistList, type SpecialistTest } from "./collabApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import { connectionState, ENDPOINT_HINTS, KeyField, modelChoices, splitChoice } from "./LanguageModel";
import "./access.css";
import { Modal } from "./Modal";

/** People and Specialists are two tabs of the Users page. */
export function UserTabs({ current }: { current: "people" | "groups" | "specialists" }) {
  // A public demo's visitor reads People and Groups only (owner, 2026-10-28).
  const admin = useIsAdmin();
  return <PageTabs label={t("People")} href={(to) => to} navigate={navigate} tabs={[
    { to: "/users", label: t("People"), active: current === "people" },
    { to: "/users/groups", label: t("Groups"), active: current === "groups" },
    ...(admin ? [{ to: "/users/specialists", label: t("Specialists"), active: current === "specialists" }] : []),
  ]} />;
}

const FALLBACK_PROVIDERS: Choice[] = [{ id: "anthropic", label: t("Claude (Anthropic)") }];

function providersOf(data: SpecialistList): Choice[] {
  return data.providers?.length ? data.providers : FALLBACK_PROVIDERS;
}

/** "Off — scripted answers", "The installation's model · <name>" or "<provider> · <model>". */
export function modelState(specialist: Specialist, data: Pick<SpecialistList, "model_allowed" | "defaults" | "providers" | "connection" | "language_providers">): string {
  const source = specialist.model.source ?? (specialist.model.enabled ? "own" : "off");
  if (source === "off" || !data.model_allowed) return t("Off — scripted answers");
  if (source === "provider") {
    const found = data.language_providers?.find((item) => item.provider_id === specialist.model.provider_id);
    return found ? `${found.name} · ${specialist.model.name}` : t("A removed provider — scripted answers");
  }
  if (source === "installation") {
    const connection = data.connection;
    return connection?.enabled && connection.ready ? t("The installation's model · {name}", { name: connection.name }) : t("The installation's model (not set up) — scripted answers");
  }
  const provider = (data.providers?.length ? data.providers : FALLBACK_PROVIDERS).find((item) => item.id === specialist.model.provider)?.label ?? specialist.model.provider;
  return `${t(provider)} · ${specialist.model.name || data.defaults.model}`;
}

export function SpecialistsPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<SpecialistList | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<Specialist | "new" | null>(null);
  const load = useCallback(() => collabApi.specialists().then((value) => { setData(value); setError(""); }).catch((err) => setError(errorText(err))), []);
  useEffect(() => { if (isAdmin) void load(); }, [isAdmin, load]);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins manage specialists.")}</span></div>;
  const appName = (id: string) => data?.apps.find((app) => app.application_id === id)?.name ?? id;

  async function remove(item: Specialist) {
    if (!window.confirm(t("Delete the specialist {name}? Its account is deactivated; the answers it gave stay in the conversations.", { name: item.display_name }))) return;
    try { await collabApi.deleteSpecialist(item.username); setNotice(t("{name} was deleted.", { name: item.display_name })); setEditing(null); await load(); } catch (err) { setError(errorText(err)); }
  }

  return <>
    <div className="page-heading">
      <div><span className="eyebrow"><Users size={14} /> {t("Administration")}</span><h1>{t("People")}</h1><p>{t("Specialists answer people in Messages from what the apps published. They only read; they never change anything.")}</p></div>
      <div className="heading-actions"><button className="button button-primary" onClick={() => setEditing("new")} disabled={!data}><Plus size={16} /> {t("New specialist")}</button></div>
    </div>
    <UserTabs current="specialists" />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {data && data.model_allowed && data.connection && <div className="ac-notice"><Bot size={15} /> {t("The installation's language model")}: {connectionState(data.connection)}. <a href="/setup/language-model" onClick={(event) => { event.preventDefault(); navigate("/setup/language-model"); }}>{t("Set it in Settings")}</a></div>}
    {data && !data.model_allowed && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("Language models are turned off in this installation by whoever installed it.")} {t("Every specialist answers from a script.")}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading specialists…")}</span></div>}
    {data && <section className="panel ac-users">
      {data.items.length ? <DataTable rows={data.items} rowKey={(item) => item.username} label={t("Specialists")} rowClassName={(item) => (item.active ? undefined : "ac-inactive")} initialSort={{ key: "name", descending: false }}
        columns={[
          { key: "name", label: t("Specialist"), sort: (item) => item.display_name, render: (item) => <span className="ac-person"><Avatar name={item.display_name} bot size="sm" /><span><strong>{item.display_name}</strong><small>@{item.username}</small></span></span> },
          { key: "subject", label: t("Subject"), sort: (item) => item.subject, render: (item) => item.subject || "—" },
          { key: "apps", label: t("Apps it reads"), render: (item) => (item.apps.length ? item.apps.map(appName).join(", ") : <span className="muted">{t("None")}</span>) },
          { key: "model", label: t("Language model"), sort: (item) => modelState(item, data), filter: { value: (item) => modelState(item, data) }, render: (item) => <span className={`sp-model${item.model.ready ? " sp-model-on" : ""}`}>{modelState(item, data)}</span> },
          { key: "answers", label: t("Answers"), numeric: true, sort: (item) => item.answers },
          { key: "active", label: t("Account status"), sort: (item) => (item.active ? 0 : 1), render: (item) => (item.active ? t("Active") : t("Deactivated")) },
          { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (item) => <>
            <button className="icon-button" title={t("Message")} aria-label={t("Message {name}", { name: item.display_name })} onClick={() => navigate(`/messages?to=${encodeURIComponent(item.username)}`)}><MessagesSquare size={15} /></button>
            <button className="icon-button" title={t("Edit")} aria-label={t("Edit {name}", { name: item.display_name })} onClick={() => setEditing(item)}><Pencil size={15} /></button>
            <button className="icon-button" title={t("Delete")} aria-label={t("Delete {name}", { name: item.display_name })} onClick={() => void remove(item)}><Trash2 size={15} /></button>
          </> },
        ]} /> : <div className="empty-state"><Bot /><strong>{t("No specialists yet")}</strong><p>{t("Create one, give it a subject and the apps it may read; people then message it.")}</p></div>}
    </section>}
    {editing && data && <SpecialistForm data={data} specialist={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDelete={remove} onSaved={(item, created) => { setEditing(null); setNotice(created ? t("{name} was created.", { name: item.display_name }) : t("{name} was updated.", { name: item.display_name })); void load(); }} />}
  </>;
}

function draftOf(item: Specialist | null, data: SpecialistList): SpecialistDraft {
  return {
    display_name: item?.display_name ?? "", subject: item?.subject ?? "", instructions: item?.instructions ?? "", apps: item?.apps ?? [], active: item?.active ?? true,
    model: { source: item?.model.source ?? "installation", provider: item?.model.provider || data.defaults.provider || "anthropic", provider_id: item?.model.provider_id ?? "", name: item?.model.name ?? "", endpoint: item?.model.endpoint ?? "", api_key: null },
  };
}

function SpecialistForm({ data, specialist, onClose, onSaved, onDelete }: { data: SpecialistList; specialist: Specialist | null; onClose: () => void; onSaved: (item: Specialist, created: boolean) => void; onDelete: (item: Specialist) => void }) {
  const [username, setUsername] = useState("");
  const [draft, setDraft] = useState<SpecialistDraft>(() => draftOf(specialist, data));
  /** "keep" the saved key, "replace" it with the typed one, or "remove" it. */
  const [keyMode, setKeyMode] = useState<"keep" | "replace" | "remove">(specialist?.model.api_key_set ? "keep" : "replace");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<SpecialistTest | null>(null);
  const model = draft.model;
  const setModel = (patch: Partial<SpecialistDraft["model"]>) => setDraft({ ...draft, model: { ...model, ...patch } });
  const toggleApp = (id: string) => setDraft({ ...draft, apps: draft.apps.includes(id) ? draft.apps.filter((item) => item !== id) : [...draft.apps, id] });
  const choices = modelChoices(data.language_providers ?? []);
  const keyValue = keyMode === "keep" ? null : keyMode === "remove" ? "" : apiKey.trim() || null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const payload: SpecialistDraft = { ...draft, display_name: draft.display_name.trim(), model: { ...model, name: model.name.trim(), endpoint: model.endpoint.trim(), api_key: keyValue } };
    try { onSaved(specialist ? await collabApi.updateSpecialist(specialist.username, payload) : await collabApi.createSpecialist({ ...payload, username }), !specialist); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  async function runTest() {
    if (!specialist) return;
    setTesting(true); setTest(null);
    try { setTest(await collabApi.testSpecialist(specialist.username)); } catch (err) { setTest({ ok: false, writer: "error", text: errorText(err) }); } finally { setTesting(false); }
  }
  const title = specialist ? specialist.display_name : t("New specialist");
  const hint = specialist?.model.api_key_hint;
  return <Modal label={title} eyebrow={<><Bot size={13} /> {t("Specialist")}</>} title={title} description={<>{specialist ? `@${specialist.username}` : t("People message it by name, or call it in a group with @username.")}</>} onClose={onClose} className="ac-form sp-form">
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        {!specialist && <label>{t("Username")}<input required value={username} autoComplete="off" placeholder={t("e.g. loops")} pattern="[a-z0-9][a-z0-9._-]*" title={t("Lower-case letters, digits, dot, dash and underscore")} onChange={(event) => setUsername(event.target.value.toLowerCase())} /></label>}
        <label className={specialist ? "field-span" : ""}>{t("Display name")}<input required maxLength={120} value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} placeholder={t("e.g. Loop specialist")} /></label>
        <label className="field-span">{t("Subject")}<input maxLength={160} value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} placeholder={t("e.g. Control loop performance")} /></label>
        <label className="field-span">{t("Instructions")}<textarea rows={5} maxLength={8000} value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} placeholder={t("How it answers and what it pays attention to. With a language model this is its prompt.")} /></label>
        <fieldset className="field-span ac-fieldset">
          <legend>{t("Apps it may read")}</legend>
          {data.apps.length ? data.apps.map((app) => <label key={app.application_id} className="ac-check"><input type="checkbox" checked={draft.apps.includes(app.application_id)} onChange={() => toggleApp(app.application_id)} /> {app.name}</label>) : <p className="muted">{t("No apps are installed.")}</p>}
        </fieldset>
        <label className="ac-check field-span"><input type="checkbox" checked={draft.active} onChange={(event) => setDraft({ ...draft, active: event.target.checked })} /> {t("Active (answers when messaged)")}</label>
        <fieldset className="field-span ac-fieldset sp-model-section">
          <legend>{t("Language model")}</legend>
          <label>{t("It answers with")}<select value={model.source} disabled={!data.model_allowed} onChange={(event) => setModel({ source: event.target.value as SpecialistDraft["model"]["source"] })}>
            <option value="installation">{t("The installation's default")}</option>
            <option value="provider">{t("A provider and model chosen here")}</option>
            {specialist?.model.source === "own" && <option value="own">{t("A model of its own (older setting)")}</option>}
            <option value="off">{t("Scripted answers only")}</option>
          </select></label>
          {model.source === "provider" && data.model_allowed && <label>{t("Provider and model")}<select required value={model.provider_id ? `${model.provider_id}|${model.name}` : ""} onChange={(event) => { const choice = splitChoice(event.target.value); setModel({ provider_id: choice.provider_id, name: choice.model }); }}>
            <option value="">{choices.length ? t("Choose…") : t("No provider saved yet")}</option>
            {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select></label>}
          <p className="muted">{!data.model_allowed ? t("Language models are turned off in this installation by whoever installed it.")
            : model.source === "installation" ? `${t("The installation's language model")}: ${data.connection ? connectionState(data.connection) : "—"}.`
            : model.source === "off" ? t("It answers from a script with what the apps published.")
            : model.source === "provider" ? <>{t("Providers and their models are saved in")} <a href="/setup/language-model" onClick={(event) => { event.preventDefault(); navigate("/setup/language-model"); }}>{t("Settings, Language models")}</a>.</>
            : t("The model writes the answer from the same data, following the instructions.")}</p>
          {model.source === "own" && data.model_allowed && <div className="sp-model-grid">
            <label>{t("Format")}<select value={model.provider} onChange={(event) => setModel({ provider: event.target.value })}>{providersOf(data).map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}</select></label>
            <label>{t("Model")}<input value={model.name} placeholder={data.defaults.model} onChange={(event) => setModel({ name: event.target.value })} /></label>
            <label className="field-span">{t("Address (optional)")}<input value={model.endpoint} placeholder={ENDPOINT_HINTS[model.provider] ?? ""} onChange={(event) => setModel({ endpoint: event.target.value })} /></label>
            <KeyField set={Boolean(specialist?.model.api_key_set)} hint={hint ?? null} mode={keyMode} onMode={setKeyMode} value={apiKey} onValue={setApiKey} />
          </div>}
        </fieldset>
        {specialist && <div className="field-span sp-test">
          <button type="button" className="button button-secondary" onClick={() => void runTest()} disabled={testing}>{testing ? <LoaderCircle className="spin" size={15} /> : <FlaskConical size={15} />} {t("Test")}</button>
          <small className="muted">{t("Tests the saved settings: save first if you changed them.")}</small>
          {test && <div className={`sp-test-result${test.ok ? " ok" : ""}`}><strong>{test.ok ? t("It answered") : t("It did not answer")}{test.writer ? ` · ${test.writer === "script" ? t("script") : test.writer}` : ""}</strong><p>{test.text}</p></div>}
        </div>}
      </div>
      <footer>
        {specialist && <button type="button" className="button button-danger sp-delete" onClick={() => onDelete(specialist)}><Trash2 size={15} /> {t("Delete")}</button>}
        <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />} {specialist ? t("Save") : t("Create specialist")}</button>
      </footer>
    </form>
  </Modal>;
}

export default SpecialistsPage;
