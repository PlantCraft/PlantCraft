import { DataTable, MultiSelect, PageTabs, Dialog, type DataColumn, useAssistantPage } from "@plantcraft/ui";
import { BellOff, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { useDirectory, whoLabel } from "./people";
import type { Alarm, AssetOption, Discipline, Me, Rule, Silence, SilenceDraft } from "./types";
import { DISCIPLINE_WORDS, ErrorBox, Heading, Link, Loading, Pill, PriorityPill, message } from "./ui";

export const EDITOR_WORDS: Record<string, string> = { simple: "Simple", blocks: "Blocks", python: "Python" };
const labelled = (words: Record<string, string>) => Object.entries(words).map(([value, label]) => ({ value, label: t(label) }));
const choices = (words: Record<string, string>) => Object.entries(words).map(([id, label]) => ({ id, label: t(label) }));

/** Rules | Silences | Philosophy: the pages that decide what becomes an alarm and who hears. */
export function RulesTabs() {
  const path = usePath();
  return <PageTabs label={t("Rules")} href={href} navigate={navigate} tabs={[
    { to: "/rules", label: t("Rules"), active: path === "/rules" },
    { to: "/silences", label: t("Silences"), active: path === "/silences" },
  ]} />;
}

/** On or off, at a click: an off rule evaluates nothing and its alarms are out of service. */
function RuleSwitch({ rule, me, onChanged }: { rule: Rule; me: Me; onChanged: (rule: Rule) => void }) {
  const [busy, setBusy] = useState(false);
  return <label className="al-switch" title={rule.enabled ? t("On: click to turn it off") : t("Off: click to turn it on")}>
    <input type="checkbox" role="switch" checked={rule.enabled} disabled={!me.can_edit || busy} aria-label={t("{name} on", { name: rule.name })}
      onChange={() => { setBusy(true); void api.enableRule(rule.rule_id, !rule.enabled).then(onChanged).finally(() => setBusy(false)); }} />
    <span>{rule.enabled ? t("On") : t("Off")}</span>
  </label>;
}

function ruleColumns(directory: ReturnType<typeof useDirectory>, me: Me, onChanged: (rule: Rule) => void): DataColumn<Rule>[] {
  const who = (rule: Rule) => (rule.notifies ? rule.recipients.map((ref) => whoLabel(ref, directory)).join(", ") : t("Alarms only"));
  return [
    { key: "on", label: t("On"), sort: (rule) => (rule.enabled ? 0 : 1), filter: { options: [{ value: "on", label: t("On") }, { value: "off", label: t("Off") }], value: (rule) => (rule.enabled ? "on" : "off") }, render: (rule) => <RuleSwitch rule={rule} me={me} onChanged={onChanged} /> },
    { key: "name", label: t("Rule"), sort: (rule) => rule.name, render: (rule) => <>
      <Link to={`/rules/${rule.rule_id}`} className="strong">{rule.name}</Link>{!rule.valid && <> <Pill status="alarm" label={t("Needs a fix")} /></>}
      <div className="small muted">{rule.where_words}</div>
    </> },
    { key: "when", label: t("When"), sort: (rule) => rule.sentence, filter: { options: labelled(EDITOR_WORDS), value: (rule) => rule.editor, label: t("Written as") }, render: (rule) => <>{rule.sentence}<div className="small muted">{t(EDITOR_WORDS[rule.editor] ?? rule.editor)}</div></> },
    { key: "creates", label: t("Makes"), className: "small", sort: (rule) => rule.creates, filter: { value: (rule) => t(rule.creates_label) }, render: (rule) => <><PriorityPill priority={rule.priority} /> {t(rule.creates_label)}</> },
    { key: "alarms", label: t("Alarms"), numeric: true, sort: (rule) => rule.alarms, render: (rule) => <>{rule.alarms}{rule.active > 0 && <div className="small"><Link to={`/alarms?rule=${encodeURIComponent(rule.rule_id)}`}>{t("{n} active", { n: rule.active })}</Link></div>}</> },
    { key: "who", label: t("Notifies"), className: "small", sort: who, render: who },
  ];
}

/** The heading of Rules and Silences: the same title and place, so the tabs never move. */
function RulesHeading({ me, adding }: { me: Me; adding?: () => void }) {
  return <>
    <Heading title={t("Rules")} actions={me.can_edit && (adding
      ? <button type="button" className="button button-primary" onClick={adding}><BellOff size={16} />{t("New silence")}</button>
      : <Link to="/rules/new" className="button button-primary"><Plus size={16} />{t("New rule")}</Link>)} />
    <RulesTabs />
  </>;
}

/** Every rule: on or off, what it watches, when it raises, what it makes, its alarms and who hears. */
export function RulesPage({ me }: { me: Me }) {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [error, setError] = useState("");
  const directory = useDirectory();
  const load = useCallback(() => api.rules().then(setRules).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);
  useAssistantPage(rules && { place: t("Alarms › Rules"), page: "alarmcraft:rules", platformUrl: me.processcraft_url, facts: { rules: rules.length },
    view: { rules: rules.slice(0, 40).map((rule) => `${rule.name} (${rule.rule_id}): ${rule.sentence} · ${rule.where_words}${rule.enabled ? "" : ", off"}`) } });
  const changed = (rule: Rule) => setRules((current) => current?.map((item) => (item.rule_id === rule.rule_id ? { ...item, ...rule } : item)) ?? null);
  return <>
    <RulesHeading me={me} />
    {error && <ErrorBox text={error} />}
    {!rules ? <Loading /> : <DataTable rows={rules} columns={ruleColumns(directory, me, changed)} rowKey={(rule) => rule.rule_id} label={t("Rules")}
      onRowClick={(rule) => navigate(`/rules/${rule.rule_id}`)} rowClassName={(rule) => (rule.enabled ? undefined : "al-row-off")}
      searchText={(rule) => `${rule.name} ${rule.where_words} ${rule.sentence}`} searchPlaceholder={t("Search rules, values or assets")}
      initialSort={{ key: "name", descending: false }}
      empty={<p className="muted al-pad">{t("No rules yet. Start from an event in Events (Create a rule), or write one with New rule.")}</p>} />}
  </>;
}

const SILENCE_CHOICES = [60, 240, 480, 1440, 4320, 10080];

function areaChoices(assets: AssetOption[]) {
  return assets.filter((asset) => asset.kind !== "loop").map((asset) => ({ id: asset.id, label: asset.parent ? `${asset.parent} › ${asset.name}` : asset.name }));
}

/** Which alarms a silence covers, in words. */
function scopeWords(silence: Silence, alarms: Alarm[]): string {
  if (silence.alarm_ids.length) return silence.alarm_ids.map((id) => alarms.find((alarm) => alarm.alarm_id === id)?.name ?? id).join(", ");
  return [
    silence.areas_named.length ? silence.areas_named.map((area) => area.name).join(", ") : t("every area"),
    silence.disciplines.length ? silence.disciplines.map((value) => t(DISCIPLINE_WORDS[value] ?? value)).join(", ") : t("every discipline"),
  ].join(" · ");
}

function SilenceDialog({ assets, alarms, onClose, onSaved }: { assets: AssetOption[]; alarms: Alarm[]; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<SilenceDraft>({ areas: [], disciplines: [], alarm_ids: [], minutes: 480, reason: "" });
  const [error, setError] = useState("");
  const update = (patch: Partial<SilenceDraft>) => setDraft({ ...draft, ...patch });
  async function save() {
    try { await api.addSilence(draft); onSaved(); } catch (err) { setError(message(err)); }
  }
  const chosen = draft.areas.length + draft.disciplines.length + draft.alarm_ids.length > 0;
  return <Dialog title={t("New silence")} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={!chosen || !draft.reason.trim()} onClick={() => void save()}><BellOff size={16} />{t("Silence")}</button>
  </>}>
      <p className="muted">{t("A silence holds back the messages of the alarms it covers (a planned shutdown, a turnaround). The alarms are still raised and shown in Active; to stop an alarm itself, shelve it.")}</p>
      <div className="form-grid">
        <div className="field-span"><MultiSelect label={t("Areas")} options={areaChoices(assets)} value={draft.areas} onChange={(areas) => update({ areas })} allLabel={t("Any area")} /></div>
        <div><MultiSelect label={t("Disciplines")} options={choices(DISCIPLINE_WORDS)} value={draft.disciplines} onChange={(value) => update({ disciplines: value as Discipline[] })} allLabel={t("Any discipline")} /></div>
        <div><MultiSelect label={t("Alarms")} options={alarms.map((alarm) => ({ id: alarm.alarm_id, label: alarm.name }))} value={draft.alarm_ids} onChange={(alarm_ids) => update({ alarm_ids })} allLabel={t("Any alarm")} /></div>
        <label>{t("For")}<select value={draft.minutes} onChange={(event) => update({ minutes: Number(event.target.value) })}>
          {SILENCE_CHOICES.map((value) => <option key={value} value={value}>{value < 1440 ? t("{n} h", { n: value / 60 }) : t("{n} days", { n: value / 1440 })}</option>)}
        </select></label>
        <label className="field-span">{t("Why")}<input value={draft.reason} maxLength={500} placeholder={t("U-200 planned shutdown")} onChange={(event) => update({ reason: event.target.value })} /></label>
      </div>
      {!chosen && <p className="muted small">{t("Choose the areas, disciplines or alarms to silence.")}</p>}
      {error && <ErrorBox text={error} />}
  </Dialog>;
}

/** Silences: messages held back during a planned shutdown, for some areas, disciplines or alarms. */
export function SilencesPage({ me }: { me: Me }) {
  const [silences, setSilences] = useState<Silence[] | null>(null);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const directory = useDirectory();
  const load = useCallback(() => api.silences().then(setSilences).catch((err) => setError(message(err))), []);
  useEffect(() => {
    void load();
    api.alarms().then(setAlarms).catch(() => setAlarms([]));
    if (me.can_edit) api.assets().then(setAssets).catch(() => setAssets([]));
  }, [load, me.can_edit]);
  const act = (run: () => Promise<unknown>) => void run().then(load).catch((err) => setError(message(err)));
  return <>
    <RulesHeading me={me} adding={() => setAdding(true)} />
    {error && <ErrorBox text={error} />}
    {!silences ? <Loading /> : silences.length ? <DataTable rows={silences} rowKey={(silence) => String(silence.silence_id)} label={t("Silences")} initialSort={{ key: "until", descending: true }} columns={[
      { key: "what", label: t("Silenced"), render: (silence) => <>{scopeWords(silence, alarms)}<div className="small muted">{silence.reason}</div></> },
      { key: "until", label: t("Until"), className: "small nowrap", sort: (silence) => silence.ends_at, render: (silence) => <>{silence.active ? <Pill status="warning" label={t("In force")} /> : <Pill status="unknown" label={t("Ended")} />} {formatDate(silence.ends_at)}</> },
      { key: "who", label: t("By"), className: "small", render: (silence) => whoLabel(`user:${silence.created_by}`, directory) },
      { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "row-actions", render: (silence) => me.can_edit && silence.active && <button type="button" className="button button-small button-secondary" onClick={() => act(() => api.endSilence(silence.silence_id))}>{t("End now")}</button> },
    ]} /> : <div className="panel al-empty"><h2>{t("No silence in the last week")}</h2><p className="muted">{t("Before a planned shutdown, silence its area so nobody is woken up for alarms everyone expects.")}</p></div>}
    {adding && <SilenceDialog assets={assets} alarms={alarms} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); void load(); }} />}
  </>;
}
