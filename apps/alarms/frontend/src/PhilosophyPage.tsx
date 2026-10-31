import { FormFooter, FormSection, TimeZoneSelect } from "@plantcraft/ui";
import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { PerformanceTabs } from "./PerformanceTabs";
import { AssetChips, NameChips } from "./Chips";
import { consolesProblem, newConsoleId } from "./consoles";
import { useDirectory } from "./people";
import type { AssetOption, Console, Me, Philosophy, PhilosophyRecord, Priority } from "./types";
import { ErrorBox, Heading, Link, Loading, PRIORITY_WORDS, message } from "./ui";

const PRIORITIES: Priority[] = ["critical", "high", "medium", "low"];
type Pace = "now" | "gathered" | "summary";
const PACE_WORDS: Record<Pace, string> = { now: "At once, one by one", gathered: "Gathered by its rule", summary: "In the shift summary" };

function strip(record: PhilosophyRecord): Philosophy {
  const { defaults: _defaults, updated_at: _at, updated_by: _by, next_summary: _next, ...draft } = record;
  return draft;
}

function paceOf(draft: Philosophy, priority: Priority): Pace {
  if (draft.immediate.includes(priority)) return "now";
  return draft.digest.includes(priority) ? "summary" : "gathered";
}

function Whole({ label, value, onChange, min, max, hint }: { label: string; value: number; onChange: (value: number) => void; min: number; max: number; hint?: string }) {
  return <label>{label}<input type="number" min={min} max={max} value={value} onChange={(event) => onChange(Math.max(min, Math.min(max, Math.round(Number(event.target.value) || min))))} />{hint && <small>{hint}</small>}</label>;
}

/** Operator positions: the areas each one answers, who sits at it, its own alarms-an-hour target. */
function ConsolesEditor({ consoles, perPerson, assets, onChange }: { consoles: Console[]; perPerson: number; assets: AssetOption[]; onChange: (consoles: Console[]) => void }) {
  const directory = useDirectory();
  const areas = assets.filter((asset) => asset.kind !== "loop");
  const people = directory.people.map((person) => ({ id: person.username, label: person.name || person.username }));
  for (const id of consoles.flatMap((item) => item.operators)) if (!people.some((option) => option.id === id)) people.push({ id, label: id });
  const change = (index: number, patch: Partial<Console>) => onChange(consoles.map((item, at) => (at === index ? { ...item, ...patch } : item)));
  return <>
    {consoles.map((item, index) => <div key={item.id} className="al-console" role="group" aria-label={t("Console {name}", { name: item.name || item.id })}>
      <div className="form-grid">
        <label>{t("Console name")}<input value={item.name} maxLength={80} onChange={(event) => change(index, { name: event.target.value })} /></label>
        <label>{t("Alarms an hour, at most")}<input type="number" min={1} max={60} value={item.per_hour ?? ""} placeholder={String(perPerson)}
          onChange={(event) => change(index, { per_hour: event.target.value === "" ? null : Math.max(1, Math.min(60, Math.round(Number(event.target.value) || 1))) })} />
          <small>{t("Empty: the load per person ({n}).", { n: perPerson })}</small></label>
        <div className="field-span"><AssetChips label={t("Areas")} value={item.areas} assets={areas} onChange={(value) => change(index, { areas: value })} hint={t("Any level of the asset tree: a unit, a section, one equipment.")} /></div>
        <div className="field-span"><NameChips label={t("Operators")} value={item.operators} options={people} onChange={(operators) => change(index, { operators })} hint={t("Who sits at it: Performance opens on their console.")} /></div>
      </div>
      <button type="button" className="button button-secondary" onClick={() => onChange(consoles.filter((_, at) => at !== index))}><Trash2 size={16} />{t("Remove the console")}</button>
    </div>)}
    <button type="button" className="button button-secondary" onClick={() => onChange([...consoles, { id: newConsoleId(consoles), name: t("Console {n}", { n: consoles.length + 1 }), areas: [], operators: [], per_hour: null }])}><Plus size={16} />{t("Add a console")}</button>
  </>;
}

/** The alarm philosophy of the installation: what an alarm is here, and the targets Alarms both
 * measures (History, Performance) and uses to hold back what reaches people. */
export function PhilosophyPage({ me }: { me: Me }) {
  const [record, setRecord] = useState<PhilosophyRecord | null>(null);
  const [draft, setDraft] = useState<Philosophy | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  useEffect(() => { api.philosophy().then((found) => { setRecord(found); setDraft(strip(found)); }).catch((err) => setError(message(err))); }, []);
  useEffect(() => { if (me.can_edit) api.assets().then(setAssets).catch(() => setAssets([])); }, [me.can_edit]);
  if (!record || !draft) return error ? <ErrorBox text={error} /> : <Loading />;
  const update = (patch: Partial<Philosophy>) => { setDraft({ ...draft, ...patch }); setSaved(false); };
  const setPace = (priority: Priority, pace: Pace) => update({
    immediate: pace === "now" ? [...new Set([...draft.immediate, priority])] : draft.immediate.filter((item) => item !== priority),
    digest: pace === "summary" ? [...new Set([...draft.digest, priority])] : draft.digest.filter((item) => item !== priority),
  });
  const total = draft.target_high + draft.target_medium + draft.target_low;
  const consoles = draft.consoles ?? [];
  const problem = consolesProblem(consoles);
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const found = await api.savePhilosophy(draft);
      setRecord(found);
      setDraft(strip(found));
      setSaved(true);
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  };
  const readOnly = !me.can_edit;
  return <div className="al-editor">
    <Heading eyebrow={<Link to="/">{t("Overview")}</Link>} title={t("Targets")}
      detail={t("An alarm exists only when a person must act. These targets are measured in History (Performance, with the worst alarms) and decide how fast each alarm reaches people. The defaults are the public ISA-18.2 and EEMUA 191 targets.")} />
    <PerformanceTabs />
    {error && <ErrorBox text={error} />}
    {saved && <div className="notice">{t("Saved. The next shift summary goes at {time}.", { time: formatDate(record.next_summary) })}</div>}
    <fieldset className="panel form-panel" disabled={readOnly}>
      <FormSection id="philosophy-statement" title={t("Philosophy")} detail={t("In your words: what is an alarm here, who answers it, how priorities are chosen. Auditors ask for it.")}>
        <div className="form-grid">
          <label className="field-span">{t("Statement")}<textarea rows={5} maxLength={5000} value={draft.statement} placeholder={t("An alarm tells the operator of an abnormal situation that needs an action within its priority's time. Every alarm has a cause, a consequence and an action.")} onChange={(event) => update({ statement: event.target.value })} /></label>
        </div>
      </FormSection>
      <FormSection id="philosophy-pace" title={t("How fast each priority reaches people")} detail={t("Critical always goes at once. A rule can still ask for \"always at once\" in its notifications.")}>
        <div className="form-grid">
          {PRIORITIES.map((priority) => <label key={priority}>{t(PRIORITY_WORDS[priority])}<select value={paceOf(draft, priority)} disabled={priority === "critical"} onChange={(event) => setPace(priority, event.target.value as Pace)}>
            {(Object.keys(PACE_WORDS) as Pace[]).map((pace) => <option key={pace} value={pace}>{t(PACE_WORDS[pace])}</option>)}
          </select></label>)}
          <label>{t("Shift summaries at")}<input value={draft.digest_times.join(", ")} placeholder="07:00, 19:00" onChange={(event) => update({ digest_times: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /><small>{t("Times of day, comma separated; the summary lists what waited, chattering and stale alarms.")}</small></label>
          <label>{t("Time zone")}<TimeZoneSelect value={draft.timezone} onChange={(timezone) => update({ timezone })} /><small>{t("The clock the summaries are sent on; Local time is the installation's.")}</small></label>
        </div>
      </FormSection>
      <FormSection id="philosophy-load" title={t("Load per person")} detail={t("Past these, Alarms sends one message instead of many; the alarms are all in Active.")}>
        <div className="form-grid">
          <Whole label={t("Messages an hour, at most")} value={draft.per_person_hour} min={1} max={60} onChange={(value) => update({ per_person_hour: value })} hint={t("About 6 is the target for one person.")} />
          <Whole label={t("Flood: more than (alarms)")} value={draft.flood_alarms} min={2} max={500} onChange={(value) => update({ flood_alarms: value })} />
          <Whole label={t("Flood: within (min)")} value={draft.flood_minutes} min={1} max={120} onChange={(value) => update({ flood_minutes: value })} hint={t("In a flood a person gets one message; critical alarms still come one by one.")} />
          <Whole label={t("Chattering: raised (times in a minute)")} value={draft.chatter_minute} min={2} max={100} onChange={(value) => update({ chatter_minute: value })} />
          <Whole label={t("Chattering: or (times in an hour)")} value={draft.chatter_hour} min={2} max={1000} onChange={(value) => update({ chatter_hour: value })} hint={t("A chattering alarm stops sending and is listed in the summary, to fix its rule.")} />
          <Whole label={t("Stale after (hours active)")} value={draft.stale_hours} min={1} max={720} onChange={(value) => update({ stale_hours: value })} hint={t("No more reminders; the summary lists it for review.")} />
        </div>
      </FormSection>
      <FormSection id="philosophy-consoles" title={t("Consoles")} detail={t("The load targets are for one operator. With several boards, say which areas each console answers: Performance then measures each one against its own target. An alarm goes to the console naming the most specific of its areas; with no console, the whole plant is one position.")}>
        <ConsolesEditor consoles={consoles} perPerson={draft.per_person_hour} assets={assets} onChange={(value) => update({ consoles: value })} />
        {problem && <p className="muted small">{problem}</p>}
      </FormSection>
      <FormSection id="philosophy-shelve" title={t("Longest shelving")} detail={t("An alarm is shelved for this long at most, by priority: the more urgent, the shorter (ISA-18.2).")}>
        <div className="form-grid">
          <Whole label={t("Critical (hours)")} value={draft.shelve_hours_critical} min={1} max={168} onChange={(value) => update({ shelve_hours_critical: value })} />
          <Whole label={t("High (hours)")} value={draft.shelve_hours_high} min={1} max={168} onChange={(value) => update({ shelve_hours_high: value })} />
          <Whole label={t("Medium (hours)")} value={draft.shelve_hours_medium} min={1} max={168} onChange={(value) => update({ shelve_hours_medium: value })} />
          <Whole label={t("Low (hours)")} value={draft.shelve_hours_low} min={1} max={168} onChange={(value) => update({ shelve_hours_low: value })} />
        </div>
      </FormSection>
      <FormSection id="philosophy-mix" title={t("Target share of priorities")} detail={t("Of the alarms raised; high counts critical too. Performance compares the real share.")}>
        <div className="form-grid">
          <Whole label={t("High and critical (%)")} value={draft.target_high} min={0} max={100} onChange={(value) => update({ target_high: value })} />
          <Whole label={t("Medium (%)")} value={draft.target_medium} min={0} max={100} onChange={(value) => update({ target_medium: value })} />
          <Whole label={t("Low (%)")} value={draft.target_low} min={0} max={100} onChange={(value) => update({ target_low: value })} hint={total === 100 ? undefined : t("They add up to {total} %; make it 100.", { total })} />
        </div>
      </FormSection>
      <FormFooter sticky note={record.updated_by ? t("Changed by {who} on {when}.", { who: record.updated_by, when: formatDate(record.updated_at ?? "") }) : t("The defaults; nobody changed them yet.")}>
        <Link to="/history/performance" className="button button-secondary">{t("See performance")}</Link>
        {!readOnly && <button type="button" className="button button-secondary" disabled={busy} onClick={() => update(record.defaults)}><RotateCcw size={16} />{t("Defaults")}</button>}
        {!readOnly && <button type="button" className="button button-primary" disabled={busy || total !== 100 || Boolean(problem)} onClick={() => void save()}><Save size={16} />{t("Save")}</button>}
      </FormFooter>
    </fieldset>
  </div>;
}
