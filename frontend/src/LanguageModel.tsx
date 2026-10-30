/** Setup › Language models, in the order an administrator sets them up:
 * first the providers (the same vendor may come more than once, each with its own key), then
 * the model each use writes with: the default, and each part of the suite that uses a model,
 * the apps' own included. Choosing a default is what turns models on; the first model that
 * answers its test becomes the default. */
import { FormSection, Heading } from "@plantcraft/ui";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, Bot, CheckCircle2, FlaskConical, LoaderCircle, Pencil, Plus, Server, ShieldCheck, Trash2, X } from "lucide-react";
import { AssistantEvaluation } from "./AssistantEval";
import { errorText } from "./collab";
import { collabApi, type LanguageModel, type LanguageModels, type LanguageProvider, type ProviderDraft, type SpecialistTest, type UseChoice } from "./collabApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import "./access.css";
import "./collab.css";
import { Modal } from "./Modal";

function Link({ to, children }: { to: string; children: ReactNode }) {
  return <a href={to} onClick={(event) => { event.preventDefault(); navigate(to); }}>{children}</a>;
}

/** Where each provider is usually found: the placeholder of the address field. */
export const ENDPOINT_HINTS: Record<string, string> = {
  openai: "http://llm.company.local:8000/v1",
  anthropic: "https://api.anthropic.com",
};

/** "Off", "Not set up" or "<model> at <address>", for Setup and the Specialists page. */
export function connectionState(connection: Pick<LanguageModel, "enabled" | "ready" | "allowed" | "name" | "endpoint"> & { provider_name?: string }): string {
  if (!connection.allowed) return t("Turned off in this installation by whoever installed it");
  if (!connection.enabled) return t("Off: no default model yet");
  if (!connection.ready) return t("Not set up: the default provider has no key");
  if (connection.provider_name) return `${connection.provider_name} · ${connection.name}`;
  return connection.endpoint ? t("{model} at {address}", { model: connection.name, address: connection.endpoint }) : connection.name;
}

/** A write-only key: keep the saved one, replace it or remove it. */
export function KeyField({ set, hint, mode, onMode, value, onValue, optional }: { set: boolean; hint: string | null; mode: "keep" | "replace" | "remove"; onMode: (mode: "keep" | "replace" | "remove") => void; value: string; onValue: (value: string) => void; optional?: boolean }) {
  return <div className="field-span sp-key">
    <span className="act-label">{t("API key")}{optional ? ` ${t("(optional)")}` : ""}</span>
    {set && mode === "keep" ? <div className="sp-key-saved"><span>{hint ? t("Saved key ending in …{hint}", { hint: hint.replace("…", "") }) : t("A key is saved")}</span><button type="button" className="button button-secondary" onClick={() => onMode("replace")}>{t("Replace")}</button><button type="button" className="button button-secondary" onClick={() => onMode("remove")}>{t("Remove")}</button></div>:
      mode === "remove" ? <div className="sp-key-saved"><span>{t("The saved key will be removed when you save.")}</span><button type="button" className="button button-secondary" onClick={() => onMode("keep")}>{t("Keep it")}</button></div>:
      <div className="sp-key-saved"><input type="password" autoComplete="new-password" value={value} onChange={(event) => onValue(event.target.value)} placeholder={set ? t("New key") : t("Paste the key")} aria-label={t("API key")} />{set && <button type="button" className="button button-secondary" onClick={() => { onValue(""); onMode("keep"); }}>{t("Cancel")}</button>}</div>}
    <small className="muted">{t("Stored beside the database, never shown again.")}</small>
  </div>;
}

/** "<provider> · <model>" choices for a select: the value is "<provider_id>|<model>". */
export function modelChoices(providers: Array<Pick<LanguageProvider, "provider_id" | "name" | "models">>): Array<{ value: string; label: string }> {
  return providers.flatMap((provider) => provider.models.map((model) => ({ value: `${provider.provider_id}|${model}`, label: `${provider.name} · ${model}` })));
}

export function splitChoice(value: string): { provider_id: string; model: string } {
  const at = value.indexOf("|");
  return at < 0 ? { provider_id: "", model: "" } : { provider_id: value.slice(0, at), model: value.slice(at + 1) };
}

function TestResult({ test }: { test: SpecialistTest }) {
  return <div className={`sp-test-result${test.ok ? " ok" : ""}`}><strong>{test.ok ? t("It answered") : t("It did not answer")}{test.writer ? ` · ${test.writer === "script" ? t("script") : test.writer}` : ""}</strong><p>{test.text}</p></div>;
}

/** A use's choice as one select value: "default", "off" or "<provider_id>|<model>". */
export function useValue(choice: UseChoice): string {
  return choice.source === "provider" ? `${choice.provider_id}|${choice.model}` : choice.source;
}

export function useChoice(value: string): UseChoice {
  if (value === "default" || value === "off") return { source: value };
  return { source: "provider", ...splitChoice(value) };
}

/** What the providers' tests said, in one line: "gpt-5 answered; gpt-5-mini: wrong name". */
export function testsSummary(tests: Record<string, SpecialistTest>): string {
  return Object.entries(tests).map(([model, test]) => test.ok ? t("{model} answered", { model }) : `${model}: ${test.text}`).join("; ");
}

export function LanguageModelPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<LanguageModels | null>(null);
  const [choice, setChoice] = useState("");
  const [uses, setUses] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<LanguageProvider | "new" | null>(null);

  const take = (value: LanguageModels) => {
    setData(value);
    setChoice(value.settings.provider_id ? `${value.settings.provider_id}|${value.settings.model}` : "");
    setUses(Object.fromEntries(value.uses.map((item) => [item.use, useValue(item.choice)])));
  };
  const reload = () => collabApi.languageModels().then(take).catch((err) => setError(errorText(err)));
  useEffect(() => { if (isAdmin) void reload(); }, [isAdmin]);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins set the language model.")}</span></div>;

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      take(await collabApi.saveModelSettings({ ...splitChoice(choice), uses: Object.fromEntries(Object.entries(uses).map(([use, value]) => [use, useChoice(value)])) }));
      setNotice(choice ? t("Saved.") : t("Saved. Language models are off: nothing is sent to them."));
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function remove(provider: LanguageProvider) {
    const who = provider.used_by.length ? ` ${t("Used by: {names}. They will answer from scripts until you choose another model for them.", { names: provider.used_by.join(", ") })}` : "";
    if (!window.confirm(`${t("Remove the provider {name} and its key?", { name: provider.name })}${who}`)) return;
    setError(""); setNotice("");
    try { take(await collabApi.removeProvider(provider.provider_id)); setNotice(t("{name} was removed.", { name: provider.name })); } catch (err) { setError(errorText(err)); }
  }
  function saved(value: LanguageModels, name: string) {
    const wasOn = data?.settings.enabled ?? false;
    take(value); setEditing(null);
    const tests = value.tests ? ` ${testsSummary(value.tests)}.` : "";
    const on = !wasOn && value.settings.enabled ? ` ${t("{model} is now the default: language models are on.", { model: value.settings.model })}` : "";
    setNotice(`${t("{name} was saved.", { name })}${tests}${on}`);
  }

  const choices = data ? modelChoices(data.providers.filter((item) => item.ready)) : [];
  const allowed = data?.settings.allowed ?? true;
  const defaultLabel = data?.settings.enabled ? choices.find((item) => item.value === choice)?.label ?? data.settings.model : "";
  const addButton = <button type="button" className="button button-primary" onClick={() => setEditing("new")} disabled={!data || data.providers.length >= data.max_providers}><Plus /> {t("Add provider")}</button>;
  return <>
    <Heading eyebrow={<><Bot size={14} /> {t("Administration")} · <Link to="/setup">{t("Settings")}</Link></>} title={t("Language models")}
      detail={t("First add a provider: the server the models run on, with its key. Then choose the model each part of the suite writes with. Nothing is sent to a model until a default is chosen.")}
      actions={data?.providers.length ? addButton : undefined} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {data && !allowed && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("Language models are turned off in this installation by whoever installed it.")} {t("The security guide says how to allow them.")}</div>}
    {data && allowed && data.providers.length > 0 && !data.settings.enabled && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("Language models are off: no default model yet. Test a model and it becomes the default, or choose one in Models by use.")}</div>}
    {data && allowed && data.settings.enabled && <div className="ac-notice"><CheckCircle2 size={15} /> {t("Language models are on: the default is {model}.", { model: defaultLabel })}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {data && <section className="panel form-panel">
      <FormSection id="lm-providers" title={t("1. Providers")} detail={<><p>{t("Where the models run, each with its address, its key and the models it serves. The same vendor may come more than once, for example OpenAI with two keys, or a local server beside a company gateway.")}</p><p>{t("The models only read: they never change anything in the plant or the suite.")}</p></>}>
        {data.providers.length ? <div className="lm-providers">{data.providers.map((provider) => <ProviderCard key={provider.provider_id} provider={provider} isDefault={provider.provider_id === data.settings.provider_id} defaultModel={data.settings.model} allowed={allowed} onTested={() => void reload()} onEdit={() => setEditing(provider)} onRemove={() => void remove(provider)} />)}</div>:
          <div className="empty-state lm-empty"><Server /><strong>{t("Add the first provider")}</strong><p>{t("Nothing works with a language model until a provider is added: a name, its address, its key if it needs one and the models it serves. Each model is tested when you save, and the first that answers becomes the default.")}</p>{addButton}</div>}
      </FormSection>
      {data.providers.length > 0 && <form onSubmit={saveSettings}>
        <FormSection id="lm-uses" title={t("2. Models by use")} detail={t("The default, and what each part of the suite writes with: the default, another model or off. Apps that write with a model add their own lines here when they are installed.")}>
          <div className="lm-uses">
            <label className="lm-use lm-use-default">
              <span><strong>{t("Default")}</strong><small className="muted">{t("Every use set to the default writes with it. None: language models are off.")}</small></span>
              <select value={choice} disabled={!allowed} onChange={(event) => setChoice(event.target.value)} aria-label={t("Default provider and model")}>
                <option value="">{t("None (models off)")}</option>
                {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            {data.uses.map((item) => <label key={item.use} className="lm-use">
              <span><strong>{item.label}</strong>{item.app && <small className="lm-use-app">{item.app}</small>}<small className="muted">{item.description}</small>{item.reads && <small className="muted">{t("Sends: {what}", { what: item.reads })}</small>}</span>
              <select value={uses[item.use] ?? "default"} disabled={!allowed} onChange={(event) => setUses({ ...uses, [item.use]: event.target.value })} aria-label={item.label}>
                <option value="default">{choice ? t("Default ({model})", { model: splitChoice(choice).model }) : t("Default (none)")}</option>
                <option value="off">{t("Off")}</option>
                {choices.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>)}
            <div className="lm-use">
              <span><strong>{t("Specialists")}</strong><small className="muted">{t("Each specialist uses the default or a model of its own, chosen on its page.")}</small></span>
              <Link to="/users/specialists">{t("People, Specialists")}</Link>
            </div>
          </div>
          <div><button className="button button-primary" disabled={busy || !allowed}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button></div>
        </FormSection>
      </form>}
      {data.settings.enabled && <AssistantEvaluation allowed={allowed} />}
    </section>}
    {editing && data && <ProviderForm kinds={data.kinds} provider={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={saved} />}
  </>;
}

function ProviderCard({ provider, isDefault, defaultModel, allowed, onTested, onEdit, onRemove }: { provider: LanguageProvider; isDefault: boolean; defaultModel: string; allowed: boolean; onTested: () => void; onEdit: () => void; onRemove: () => void }) {
  const [model, setModel] = useState(provider.models[0] ?? "");
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<SpecialistTest | null>(null);
  useEffect(() => { if (!provider.models.includes(model)) setModel(provider.models[0] ?? ""); }, [provider.models, model]);
  async function run() {
    setTesting(true); setTest(null);
    // A model that answers may have become the default: read the page again.
    try { const answer = await collabApi.testProvider(provider.provider_id, model); setTest(answer); if (answer.ok) onTested(); } catch (err) { setTest({ ok: false, writer: "error", text: errorText(err) }); } finally { setTesting(false); }
  }
  return <article className="lm-provider">
    <header>
      <div><h3>{provider.name}{isDefault && <span className="lm-default">{t("Default")}</span>}</h3><small className="muted">{provider.kind_label}</small></div>
      <span className={`sp-model${provider.ready ? " sp-model-on" : ""}`}>{provider.ready ? <><CheckCircle2 size={13} /> {t("Ready")}</> : t("Missing the key")}</span>
      <div className="heading-actions">
        <button type="button" className="button button-ghost button-icon" title={t("Edit")} aria-label={t("Edit {name}", { name: provider.name })} onClick={onEdit}><Pencil /></button>
        <button type="button" className="button button-ghost button-icon" title={t("Remove")} aria-label={t("Remove {name}", { name: provider.name })} onClick={onRemove}><Trash2 /></button>
      </div>
    </header>
    <dl className="lm-facts">
      <div><dt>{t("Address")}</dt><dd>{provider.endpoint || (provider.kind === "anthropic" ? t("Anthropic's own") : t("OpenAI's own"))}</dd></div>
      <div><dt>{t("API key")}</dt><dd>{provider.api_key_set ? t("Saved key ending in …{hint}", { hint: (provider.api_key_hint ?? "").replace("…", "") }) : t("None")}</dd></div>
      {provider.kind === "openai" && <div><dt>{t("Reasoning effort")}</dt><dd>{provider.reasoning ? reasoningLabel(provider.reasoning) : t("The service's default")}</dd></div>}
      <div><dt>{t("Models")}</dt><dd className="lm-models">{provider.models.map((item) => <span key={item} className={`lm-model${isDefault && item === defaultModel ? " lm-model-default" : ""}`}>{item}</span>)}</dd></div>
      <div><dt>{t("Used by")}</dt><dd>{provider.used_by.length ? provider.used_by.join(", ") : isDefault ? t("The specialists on the default") : t("No specialist")}</dd></div>
    </dl>
    <div className="sp-test lm-test">
      <select value={model} onChange={(event) => setModel(event.target.value)} aria-label={t("Model to test")}>{provider.models.map((item) => <option key={item} value={item}>{item}</option>)}</select>
      <button type="button" className="button button-secondary" onClick={() => void run()} disabled={testing || !allowed}>{testing ? <LoaderCircle className="spin" /> : <FlaskConical />} {t("Test")}</button>
      {test && <TestResult test={test} />}
    </div>
  </article>;
}

const REASONING = ["none", "minimal", "low", "medium", "high"];

function reasoningLabel(effort: string): string {
  return ({ none: t("None"), minimal: t("Minimal"), low: t("Low"), medium: t("Medium"), high: t("High") } as Record<string, string>)[effort] ?? effort;
}

function ProviderForm({ kinds, provider, onClose, onSaved }: { kinds: Array<{ id: string; label: string }>; provider: LanguageProvider | null; onClose: () => void; onSaved: (value: LanguageModels, name: string) => void }) {
  const [draft, setDraft] = useState({ name: provider?.name ?? "", kind: provider?.kind ?? "openai", endpoint: provider?.endpoint ?? "", reasoning: provider?.reasoning ?? "" });
  const [models, setModels] = useState<string[]>(provider?.models.length ? provider.models : [""]);
  const [keyMode, setKeyMode] = useState<"keep" | "replace" | "remove">(provider?.api_key_set ? "keep" : "replace");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const payload: ProviderDraft = { name: draft.name.trim(), kind: draft.kind, endpoint: draft.endpoint.trim(), models: models.map((item) => item.trim()).filter(Boolean), api_key: keyMode === "keep" ? null : keyMode === "remove" ? "" : apiKey.trim() || null, reasoning: draft.kind === "openai" ? draft.reasoning : "" };
    try { onSaved(provider ? await collabApi.saveProvider(provider.provider_id, payload) : await collabApi.addProvider(payload), payload.name); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  const title = provider ? provider.name : t("New provider");
  return <Modal label={title} eyebrow={<><Server size={13} /> {t("Language model provider")}</>} title={title} description={t("A server the suite may send prompts to, and the models it serves. Each model is tested when you save.")} onClose={onClose} className="ac-form">
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        <label>{t("Name")}<input required maxLength={80} value={draft.name} placeholder={t("e.g. Local server, Company gateway")} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>{t("Format")}<select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}>{kinds.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label className="field-span">{t("Address")}<input value={draft.endpoint} maxLength={300} placeholder={ENDPOINT_HINTS[draft.kind] ?? ""} onChange={(event) => setDraft({ ...draft, endpoint: event.target.value })} />
          <small>{draft.kind === "openai" ? t("The base address with its /v1, as the server documents it: Ollama http://host:11434/v1, vLLM or LM Studio http://host:8000/v1, a company gateway or Azure OpenAI. Empty: OpenAI's own.") : t("Empty: Anthropic's own. Or the address of a gateway in front of it.")}</small>
        </label>
        {draft.kind === "openai" && <label className="field-span">{t("Reasoning effort")}<select value={draft.reasoning} onChange={(event) => setDraft({ ...draft, reasoning: event.target.value })}><option value="">{t("The service's default")}</option>{REASONING.map((item) => <option key={item} value={item}>{reasoningLabel(item)}</option>)}</select>
          <small>{t("How long a reasoning model (OpenAI's gpt-5 and later, o-series) thinks before it answers. Lower is faster and cheaper. Leave the default for models that do not reason: they refuse the setting.")}</small>
        </label>}
        <KeyField set={Boolean(provider?.api_key_set)} hint={provider?.api_key_hint ?? null} mode={keyMode} onMode={setKeyMode} value={apiKey} onValue={setApiKey} optional={draft.kind === "openai"} />
        <fieldset className="field-span ac-fieldset lm-model-list">
          <legend>{t("Models")}</legend>
          <small className="muted">{t("The names exactly as the server knows them. Specialists choose among these.")}</small>
          {models.map((item, index) => <div key={index} className="lm-model-row">
            <input value={item} maxLength={100} aria-label={t("Model {number}", { number: index + 1 })} placeholder={draft.kind === "openai" ? "llama3.1:70b" : "claude-sonnet-5-5"} onChange={(event) => setModels(models.map((value, at) => at === index ? event.target.value : value))} />
            <button type="button" className="icon-button" aria-label={t("Remove")} disabled={models.length === 1} onClick={() => setModels(models.filter((_value, at) => at !== index))}><X size={15} /></button>
          </div>)}
          <button type="button" className="as-link-button" onClick={() => setModels([...models, ""])} disabled={models.length >= 30}><Plus size={14} /> {t("Add model")}</button>
        </fieldset>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button></footer>
    </form>
  </Modal>;
}

export default LanguageModelPage;
