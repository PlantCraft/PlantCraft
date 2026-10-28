import { DataTable, FormFooter, FormSection, RecipientPicker, confirmAction } from "@plantcraft/ui";
import { FlaskConical, Save, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { AlarmChart } from "./AlarmChart";
import { t } from "./i18n";
import { navigate } from "./nav";
import { NotifyEditor } from "./notify";
import { useDirectory } from "./people";
import { draftOf, EMPTY_RULE, NO_WHERE, scheduleRule } from "./rules";
import { AssetSearch } from "./SourcePicker";
import type { AssetOption, Creates, Discipline, Execution, Me, Per, Priority, Rule, RuleDraft, TryResult, Where } from "./types";
import { DISCIPLINE_WORDS, ErrorBox, Heading, Link, Loading, PRIORITY_WORDS, WindowPicker, message } from "./ui";
import { WhenEditor } from "./WhenEditor";

export { EMPTY_RULE, scheduleRule };

/** ISA-18.2's usual guide for a rationalized alarm system: few critical, most medium or low. */
const PRIORITY_GUIDE: Record<Priority, number> = { critical: 5, high: 15, medium: 40, low: 40 };

/** "3 of 25 rules (12%) are critical; about 5% is the usual guide." */
export function priorityHint(rules: Pick<Rule, "priority" | "rule_id">[], priority: Priority, own?: string): string {
  const others = rules.filter((rule) => rule.rule_id !== own);
  const count = others.filter((rule) => rule.priority === priority).length + 1;
  const total = others.length + 1;
  const share = Math.round((100 * count) / total);
  return t("With this one, {count} of {total} rules ({share}%) are {priority}; about {guide}% is the usual guide (ISA-18.2).", { count, total, share, priority: t(PRIORITY_WORDS[priority]).toLowerCase(), guide: PRIORITY_GUIDE[priority] });
}

type Scope = "assets" | "executions" | "anywhere" | "none";
const SCOPES: Array<[Scope, string, string]> = [
  ["assets", "Assets", "Named assets, every asset under a branch or of a type."],
  ["executions", "Monitors", "The assets an app's monitor runs on (an Analytics monitor), or the monitor itself."],
  ["anywhere", "Any asset its events name", "An alarm appears for each asset the events are about."],
  ["none", "Only the values named", "One alarm, on the signals and events the rule names."],
];

export function scopeOf(where: Where): Scope {
  if (where.anywhere) return "anywhere";
  if (where.executions.length || where.per === "execution") return "executions";
  if (where.assets.length || where.under.length || where.types.length) return "assets";
  return "none";
}

/** Assets chosen one by one (search, then each shows as a chip). */
function AssetChips({ label, value, assets, onChange, hint }: { label: string; value: string[]; assets: AssetOption[]; onChange: (value: string[]) => void; hint?: string }) {
  const name = (id: string) => { const found = assets.find((item) => item.id === id); return found ? (found.parent ? `${found.parent} › ${found.name}` : found.name) : id; };
  return <div><span className="al-label">{label}</span>
    {value.length > 0 && <div className="al-chips">{value.map((id) => <span key={id} className="al-chip">{name(id)}
      <button type="button" aria-label={t("Remove {name}", { name: name(id) })} onClick={() => onChange(value.filter((item) => item !== id))}><X size={12} /></button></span>)}</div>}
    <AssetSearch assets={assets.filter((item) => !value.includes(item.id))} value="" label={label} placeholder={t("Search assets to add")} onPick={(id) => { if (id && !value.includes(id)) onChange([...value, id]); }} />
    {hint && <small className="muted">{hint}</small>}
  </div>;
}

/** Choices ticked from a short list (asset types, executions). */
function Ticks({ label, options, value, onChange, empty }: { label: string; options: Array<{ id: string; label: string; detail?: string }>; value: string[]; onChange: (value: string[]) => void; empty: string }) {
  return <div className="field-span"><span className="al-label">{label}</span>
    {options.length ? <div className="al-ticks">{options.map((item) => <label key={item.id} className="check">
      <input type="checkbox" checked={value.includes(item.id)} onChange={(event) => onChange(event.target.checked ? [...value, item.id] : value.filter((one) => one !== item.id))} />
      {" "}{item.label}{item.detail && <small className="muted"> {item.detail}</small>}
    </label>)}</div> : <p className="muted small">{empty}</p>}
  </div>;
}

function WhereEditor({ where, onChange, assets, types, executions }: { where: Where; onChange: (where: Where) => void; assets: AssetOption[]; types: Array<{ id: string; name: string }>; executions: Execution[] }) {
  // The choice is kept apart from what is filled in: Assets or Executions picked with nothing
  // named yet still shows its fields.
  const [chosen, setChosen] = useState<Scope | null>(null);
  const found = scopeOf(where);
  const scope = found === "none" && chosen ? chosen : found;
  const set = (patch: Partial<Where>) => onChange({ ...where, ...patch });
  function setScope(next: Scope) {
    if (next === scope) return;
    setChosen(next);
    if (next === "anywhere") onChange({ ...NO_WHERE(), anywhere: true });
    else if (next === "executions") onChange({ ...NO_WHERE(), executions: where.executions });
    else if (next === "assets") onChange({ ...NO_WHERE(), assets: where.assets, under: where.under, types: where.types });
    else onChange(NO_WHERE());
  }
  const pers: Array<[Per, string]> = scope === "executions"
    ? [["asset", "Each asset it runs on"], ["execution", "Each monitor"], ["rule", "One for the whole rule"]]
    : [["asset", "Each asset"], ["rule", "One for the whole rule"]];
  return <>
    <div className="al-types" role="radiogroup" aria-label={t("Where")}>
      {SCOPES.map(([id, label, detail]) => <button key={id} type="button" role="radio" aria-checked={scope === id} className={scope === id ? "al-type on" : "al-type"} onClick={() => setScope(id)}>
        <b>{t(label)}</b><small>{t(detail)}</small>
      </button>)}
    </div>
    <div className="form-grid">
      {scope === "assets" && <>
        <div className="field-span"><AssetChips label={t("Assets")} value={where.assets} assets={assets} onChange={(value) => set({ assets: value })} /></div>
        <div className="field-span"><AssetChips label={t("Every asset under")} value={where.under} assets={assets.filter((asset) => asset.kind !== "loop")} onChange={(value) => set({ under: value })}
          hint={t("A unit or an area: today's assets and those added later.")} /></div>
        <Ticks label={t("Every asset of the types")} value={where.types} onChange={(value) => set({ types: value })} empty={t("PlantCraft names no asset types yet.")}
          options={types.map((item) => ({ id: item.id, label: item.name }))} />
      </>}
      {scope === "executions" && <Ticks label={t("Monitors")} value={where.executions} onChange={(value) => set({ executions: value, per: value.length ? where.per : "asset" })} empty={t("No app has published a monitor yet (Analytics' monitors appear here).")}
        options={executions.map((item) => ({ id: item.id, label: item.name, detail: [item.cadence, t("{n} assets", { n: item.assets })].filter(Boolean).join(" · ") }))} />}
      {(scope === "assets" || scope === "executions") && <label>{t("One alarm for")}<select value={where.per} onChange={(event) => set({ per: event.target.value as Per })}>
        {pers.map(([id, words]) => <option key={id} value={id}>{t(words)}</option>)}
      </select><small>{where.per === "rule" ? t("Active while any of them is; the alarm names which.") : t("Each its own alarm, acknowledged on its own.")}</small></label>}
      {scope === "anywhere" && <p className="muted field-span">{t("Use events in the conditions: an alarm is made for an asset when the first event about it counts.")}</p>}
    </div>
  </>;
}

/** "3 alarms in 24 h (0.13 per hour) on 12 assets, about 2 messages." */
function triedWords(tried: TryResult, period: string, notifies: boolean): string {
  const raised = t("{count} alarms in {window} ({rate} per hour) over {subjects} targets.", { count: tried.count, window: period, rate: tried.per_hour, subjects: tried.subjects });
  if (!notifies) return `${raised} ${t("No message: this rule shows its alarms in Alarms only.")}`;
  return `${raised} ${t("Gathered, about {messages} messages ({rate} per hour) to each recipient.", { messages: tried.messages, rate: tried.messages_per_hour })}`;
}

/** The first condition's limits, drawn on the Test chart. */
function limitsOf(draft: RuleDraft): { limit: number | null; high: number | null; deadband: number } {
  const first = draft.simple?.conditions.find((item) => item.input === "value");
  if (!first || first.op === "changed" || first.op === "unchanged") return { limit: null, high: null, deadband: 0 };
  const range = first.op === "between" || first.op === "outside";
  return { limit: first.limit, high: range ? first.high : null, deadband: range ? 0 : first.deadband };
}

/** Create or change a rule, and test it on the plant's history and the events that came in.
 * ``fromEvent``: start from an event in Events; ``schedule``: from a Link schedule. */
export function RuleEditor({ me, ruleId, fromEvent, fromCatalog, schedule }: { me: Me; ruleId?: string; fromEvent?: number; fromCatalog?: string; schedule?: { id: string; name?: string } }) {
  const [draft, setDraft] = useState<RuleDraft | null>(ruleId || fromEvent || fromCatalog ? null : schedule ? scheduleRule(schedule.id, schedule.name) : EMPTY_RULE());
  const [stored, setStored] = useState<Rule | null>(null);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [types, setTypes] = useState<Array<{ id: string; name: string }>>([]);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [others, setOthers] = useState<Rule[]>([]);
  const [limit, setLimit] = useState(6);
  const directory = useDirectory();
  const [tried, setTried] = useState<TryResult | null>(null);
  const [period, setPeriod] = useState("24h");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api.assets().then(setAssets).catch(() => setAssets([]));
    api.assetTypes().then(setTypes).catch(() => setTypes([]));
    api.executions().then(setExecutions).catch(() => setExecutions([]));
    api.rules().then(setOthers).catch(() => setOthers([]));
    api.sent().then((found) => setLimit(found.limit_per_hour)).catch(() => undefined);
    const started = (found: Partial<RuleDraft>) => setDraft(draftOf(found));
    const failed = (err: unknown) => { setError(message(err)); setDraft(EMPTY_RULE()); };
    if (ruleId) api.rule(ruleId).then((rule) => { setStored(rule); setDraft(draftOf(rule)); }).catch((err) => setError(message(err)));
    else if (fromEvent) api.ruleFromEvent(fromEvent).then(started).catch(failed);
    else if (fromCatalog) api.ruleFromCatalog(fromCatalog).then(started).catch(failed);
  }, [ruleId, fromEvent, fromCatalog]);
  if (!me.can_edit) return <ErrorBox text={t("Your access to Alarms is read-only.")} />;
  if (!draft) return error ? <ErrorBox text={error} /> : <Loading />;
  const update = (patch: Partial<RuleDraft>) => { setDraft({ ...draft, ...patch }); setTried(null); };

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await task(); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  const tryIt = (span = period) => run(async () => setTried(await api.tryRule(draft, span, stored?.rule_id)));
  const save = () => run(async () => {
    const saved = stored ? await api.saveRule(stored.rule_id, draft, stored.updated_at) : await api.createRule(draft);
    navigate(`/rules/${saved.rule_id}`);
  });
  const remove = () => run(async () => {
    if (!stored || !(await confirmAction(t("Delete {name}? Its alarms end; their journal stays.", { name: stored.name }), { confirm: t("Delete"), danger: true }))) return;
    await api.removeRule(stored.rule_id);
    navigate("/rules");
  });
  const limits = limitsOf(draft);

  return <div className="al-editor">
    <Heading eyebrow={<Link to={stored ? `/rules/${stored.rule_id}` : "/rules"}>{t("Rules")}</Link>} title={stored ? t("Change {name}", { name: stored.name }) : t("New rule")}
      detail={t("Where it applies, when it raises, what it makes, who hears and what to do about it.")} />
    {error && <ErrorBox text={error} />}
    <section className="panel form-panel">
      <FormSection id="rule" title={t("Rule")} detail={t("Its name, what it makes and how urgent it is.")}>
      <div className="form-grid">
        <label className="field-span">{t("Name")}<input value={draft.name} maxLength={120} placeholder={t("Feed flow high")} onChange={(event) => update({ name: event.target.value })} /></label>
        <label>{t("Makes")}<select value={draft.creates} onChange={(event) => update({ creates: event.target.value as Creates })}>
          <option value="alarm">{t("An alarm (acknowledged by the operator, counts in performance)")}</option>
          <option value="notice">{t("An alert (to know, no acknowledgement)")}</option>
        </select></label>
        <label>{t("Priority")}<select value={draft.priority} onChange={(event) => update({ priority: event.target.value as Priority })}>
          {Object.entries(PRIORITY_WORDS).map(([id, label]) => <option key={id} value={id}>{t(label)}</option>)}
        </select>{others.length > 0 && <small>{priorityHint(others, draft.priority, stored?.rule_id)}</small>}</label>
        <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(event) => update({ enabled: event.target.checked })} /> {t("On")}</label>
      </div>
      </FormSection>
      <FormSection id="rule-where" title={t("Where")} detail={t("What its alarms are about. A rule over many assets makes one alarm each, today's and those added later.")}>
        <WhereEditor where={draft.where} onChange={(where) => update({ where })} assets={assets} types={types} executions={executions} />
      </FormSection>
      <FormSection id="rule-when" title={t("When")} detail={t("What raises it: a sentence (Simple) or a Python function for any other logic. Values and events are picked in the Explorer.")}>
        <WhenEditor draft={draft} update={update} canWritePython={me.is_admin} />
      </FormSection>
      <FormSection id="rule-outputs" title={t("Outputs")} detail={t("Where its alarms go. Alarms shows them always; the rest is on unless you turn it off.")}>
      <div className="form-grid al-outputs">
        <label className="check field-span"><input type="checkbox" checked disabled /> {draft.creates === "alarm" ? t("Alarms: listed to acknowledge, shelve and comment") : t("Alarms: listed as alerts (nothing to acknowledge)")}</label>
        <label className="check field-span"><input type="checkbox" checked={draft.dashboards} onChange={(event) => update({ dashboards: event.target.checked })} /> {t("Dashboards: colours its assets and shows in the Active alarms widgets (View, Overview)")}</label>
      </div>
      <h3 className="al-sub">{t("Messages")}</h3>
      <NotifyEditor draft={draft.notify} update={(patch) => update({ notify: { ...draft.notify, ...patch } })} directory={directory} limit={limit} email={Boolean(me.email_ready)} />
      </FormSection>
      <FormSection id="rule-owner" title={t("Owner and rationalization")} detail={t("Who answers for the rule, and why it exists. An alarm without an action should not be an alarm.")}>
      <div className="form-grid">
        <div><span className="al-label">{t("Owner")}</span>
          <RecipientPicker single label={t("Owner")} value={draft.owner ? [draft.owner] : []} onChange={(value) => update({ owner: value[0] ?? null })}
            people={directory.people} groups={directory.groups} placeholder={stored ? t("A person or a group") : t("You, when left empty")} />
          <small className="muted">{t("An alarm on a monitor answers to the owner its app names (Analytics: the monitor's).")}</small>
        </div>
        <label>{t("Area")}<select value={draft.area ?? ""} onChange={(event) => update({ area: event.target.value || null })}>
          <option value="">{t("From the asset tree")}</option>
          {assets.filter((asset) => asset.kind !== "loop").map((asset) => <option key={asset.id} value={asset.id}>{asset.parent ? `${asset.parent} › ${asset.name}` : asset.name}</option>)}
        </select></label>
        <label>{t("Discipline")}<select value={draft.discipline ?? ""} onChange={(event) => update({ discipline: (event.target.value || null) as Discipline | null })}>
          <option value="">{t("None")}</option>
          {Object.entries(DISCIPLINE_WORDS).map(([id, label]) => <option key={id} value={id}>{t(label)}</option>)}
        </select></label>
        <label>{t("Cause")}<textarea value={draft.cause} maxLength={2000} onChange={(event) => update({ cause: event.target.value })} /></label>
        <label>{t("Consequence of not acting")}<textarea value={draft.consequence} maxLength={2000} onChange={(event) => update({ consequence: event.target.value })} /></label>
        <label>{t("Corrective action")}<textarea value={draft.action} maxLength={2000} onChange={(event) => update({ action: event.target.value })} /></label>
      </div>
      </FormSection>
    <FormSection id="rule-try" title={t("Test")} detail={t("How many alarms and messages this rule would have made over the plant's recent data and the events that came in, judged exactly as it will run.")}>
      <div className="al-inline">
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void tryIt()}><FlaskConical size={16} />{busy ? t("Working…") : t("Test")}</button>
        <WindowPicker value={period} options={["6h", "24h", "7d"]} onChange={(span) => { setPeriod(span); if (tried) void tryIt(span); }} />
      </div>
      {tried && <>
        <p className={tried.messages_per_hour > 1 || tried.per_hour > 1 ? "notice" : "notice notice-ok"}>
          {triedWords(tried, period, draft.notify.enabled)}
          {tried.step > 1 && ` ${t("Read as averages of {step} s.", { step: tried.step })}`}
          {tried.subjects > tried.tried && ` ${t("Tested on the first {n}.", { n: tried.tried })}`}
        </p>
        {tried.problems.map((problem) => <p key={problem} className="muted small">{problem}</p>)}
        {tried.alarms.length > 1 && <DataTable rows={tried.alarms} rowKey={(item) => item.subject || item.label} label={t("Alarms it would make")} initialSort={{ key: "count", descending: true }} columns={[
          { key: "label", label: t("Target"), sort: (item) => item.label, render: (item) => <>{item.label}{item.message && <div className="small muted">{item.message}</div>}</> },
          { key: "count", label: t("Alarms"), numeric: true, sort: (item) => item.count, render: (item) => item.count },
        ]} />}
        {tried.chart.t.length > 0 && <AlarmChart chart={tried.chart} limit={limits.limit} high={limits.high} deadband={limits.deadband} occurrences={tried.occurrences} end={tried.end} />}
      </>}
    </FormSection>
    <FormFooter sticky note={draft.notify.enabled ? t("Saved rules start at once; their first messages follow the next alarm.") : t("Saved rules start at once.")}>
      {stored && <button type="button" className="button button-danger" disabled={busy} onClick={() => void remove()}><Trash2 size={16} />{t("Delete")}</button>}
      <Link to={stored ? `/rules/${stored.rule_id}` : "/rules"} className="button button-secondary">{t("Cancel")}</Link>
      <button type="button" className="button button-primary" disabled={busy || !draft.name.trim()} onClick={() => void save()}><Save size={16} />{t("Save")}</button>
    </FormFooter>
    </section>
  </div>;
}
