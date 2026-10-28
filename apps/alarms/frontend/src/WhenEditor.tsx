/**
 * When a rule raises, written two ways: a Simple sentence (up to three conditions on values or
 * events) or Python (a function over a few values, written by administrators only), in the
 * suite's code editor. Blocks was retired (owner's review, 2026-10-27): Simple covers the common
 * rules and Python any other logic; a rule drawn in Blocks before keeps running as drawn. Every
 * value and event is picked in the suite's Explorer.
 */
import "@plantcraft/ui/codeEditor.css";
import { Dialog, Explorer, type ExplorePick, type ExploreWant } from "@plantcraft/ui";
import { CodeEditor } from "@plantcraft/ui/codeEditor";
import { Code2, ListChecks, Maximize2, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import {
  canBeRelative, eventCondition, inputLabel, MAX_CONDITIONS, overAssets, pythonDiagram, pythonForm, pythonFromSimple, pythonTemplate,
  valueCondition, valueOfPick, valueWords, type PythonForm,
} from "./rules";
import type { Editor, Op, RuleDraft, Severity, SimpleCondition, SimpleLogic, SimpleValue, Where } from "./types";
import { ErrorBox, message } from "./ui";

const OPS: Array<[Op, string]> = [
  [">", "above"], [">=", "at or above"], ["<", "below"], ["<=", "at or below"], ["==", "equal to"], ["!=", "not equal to"],
  ["between", "between"], ["outside", "outside"], ["changed", "changed"], ["unchanged", "did not change (frozen)"],
];
const SEVERITIES: Array<[Severity, string]> = [["warning", "Warning"], ["critical", "Critical"]];
const EDITORS: Array<[Editor, string, string, typeof ListChecks]> = [
  ["simple", "Simple", "A sentence: values and events, a limit, how long.", ListChecks],
  ["python", "Python", "A function over a few values, for any other logic (administrators write it).", Code2],
];

function NumberField({ label, value, onChange, hint, min, step = "any" }: { label: string; value: number | null; onChange: (value: number | null) => void; hint?: string; min?: number; step?: string }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  return <label>{label}<input type="number" step={step} min={min} value={text} onChange={(event) => {
    setText(event.target.value);
    const number = Number(event.target.value);
    if (event.target.value === "") onChange(null);
    else if (Number.isFinite(number)) onChange(number);
  }} />{hint && <small>{hint}</small>}</label>;
}

/** The suite's Explorer in a dialog: pick a value (a plant signal or an app's series) or an
 * event kind, on each asset of the rule or on the one it was found on. */
export function PickDialog({ want, where, onPick, onClose }: { want: ExploreWant[]; where: Where; onPick: (pick: ExplorePick, each: boolean) => void; onClose: () => void }) {
  const [each, setEach] = useState(overAssets(where));
  return <Dialog title={want.includes("event") ? t("Pick an event") : t("Pick a value")} onClose={onClose} wide>
    {overAssets(where) && <label className="check al-pad-bottom"><input type="checkbox" checked={each} onChange={(event) => setEach(event.target.checked)} /> {want.includes("event")
      ? t("About each asset of the rule (not only the one it was found on)")
      : t("Read on each asset of the rule (the same role or series on each)")}</label>}
    <Explorer load={api.explore} search={api.exploreSearch} preview={api.value} want={want} onPick={(pick) => { onPick(pick, each); onClose(); }} />
  </Dialog>;
}

/** One value: what was picked, and the button that opens the Explorer. */
function ValueField({ value, where, onChange, label }: { value: SimpleValue | null; where: Where; onChange: (value: SimpleValue) => void; label: string }) {
  const [open, setOpen] = useState(false);
  return <div><span className="al-label">{label}</span>
    <div className="al-inline">
      {value && (value.signal || value.role)
        ? <span className="al-chip" title={value.signal || value.role}>{valueWords(value)}</span>
        : <span className="muted">{t("Nothing picked yet")}</span>}
      <button type="button" className="button button-small button-secondary" onClick={() => setOpen(true)}><Search size={14} />{t("Pick in the Explorer")}</button>
    </div>
    {open && <PickDialog want={["value"]} where={where} onClose={() => setOpen(false)} onPick={(pick, each) => onChange(valueOfPick(pick, each && canBeRelative(pick)))} />}
  </div>;
}

function ConditionRow({ condition, where, onChange, onRemove, index }: { condition: SimpleCondition; where: Where; onChange: (condition: SimpleCondition) => void; onRemove?: () => void; index: number }) {
  const [picking, setPicking] = useState(false);
  const set = (patch: Partial<SimpleCondition>) => onChange({ ...condition, ...patch });
  const event = condition.event;
  const range = condition.op === "between" || condition.op === "outside";
  const moving = condition.op === "changed" || condition.op === "unchanged";
  return <fieldset className="al-condition">
    <legend>{t("Condition {n}", { n: index + 1 })}</legend>
    <div className="al-inline al-condition-head">
      <div className="pc-segmented" role="group" aria-label={t("Condition on")}>
        <button type="button" className={condition.input === "value" ? "on" : ""} onClick={() => condition.input !== "value" && onChange({ ...valueCondition(), for_seconds: condition.for_seconds })}>{t("A value")}</button>
        <button type="button" className={condition.input === "event" ? "on" : ""} onClick={() => condition.input !== "event" && onChange({ ...eventCondition([], overAssets(where) ? "subject" : "any"), for_seconds: condition.for_seconds })}>{t("An event")}</button>
      </div>
      {onRemove && <button type="button" className="icon-button" aria-label={t("Remove this condition")} title={t("Remove this condition")} onClick={onRemove}><Trash2 size={16} /></button>}
    </div>
    <div className="form-grid">
      {condition.input === "value" && <>
        <div className="field-span"><ValueField label={t("Value")} value={condition.value} where={where} onChange={(value) => set({ value })} /></div>
        <label>{t("Is")}<select value={condition.op} onChange={(item) => set({ op: item.target.value as Op })}>
          {OPS.map(([id, words]) => <option key={id} value={id}>{t(words)}</option>)}
        </select></label>
        {!moving && <NumberField label={range ? t("Low") : t("Limit")} value={condition.limit} onChange={(limit) => set({ limit })} />}
        {range && <NumberField label={t("High")} value={condition.high} onChange={(high) => set({ high })} />}
        {!moving && !range && <NumberField label={t("Deadband")} value={condition.deadband} min={0} onChange={(deadband) => set({ deadband: deadband ?? 0 })} hint={t("Clears only this far back inside the limit.")} />}
      </>}
      {condition.input === "event" && event && <>
        <div className="field-span"><span className="al-label">{t("Event")}</span>
          <div className="al-inline">
            {event.kinds.length ? event.kinds.map((kind) => <span key={kind} className="al-chip">{kind}<button type="button" aria-label={t("Remove {name}", { name: kind })} onClick={() => set({ event: { ...event, kinds: event.kinds.filter((item) => item !== kind) } })}><X size={12} /></button></span>) : <span className="muted">{t("Nothing picked yet")}</span>}
            <button type="button" className="button button-small button-secondary" onClick={() => setPicking(true)}><Search size={14} />{t("Pick in the Explorer")}</button>
          </div>
          <small className="muted">{event.about === "subject" ? t("About each asset of the rule.") : event.about === "any" ? t("About anything (a part of the suite, any asset).") : t("About {ref}.", { ref: event.about })}</small>
        </div>
        <div><span className="al-label">{t("Severity")}</span><div className="al-inline">
          {SEVERITIES.map(([value, words]) => <label key={value} className="check"><input type="checkbox" checked={event.severities.includes(value)} onChange={(item) => set({ event: { ...event, severities: item.target.checked ? [...event.severities, value] : event.severities.filter((one) => one !== value) } })} /> {t(words)}</label>)}
        </div><small className="muted">{t("None ticked: any severity.")}</small></div>
        <label>{t("Raise when")}<select value={condition.test} onChange={(item) => set({ test: item.target.value as SimpleCondition["test"] })}>
          <option value="open">{t("It is open (its end clears it)")}</option>
          <option value="count">{t("It happened so many times")}</option>
        </select></label>
        {condition.test === "count" && <>
          <NumberField label={t("How many times")} value={condition.count} min={1} step="1" onChange={(count) => set({ count: Math.max(1, Math.round(count ?? 1)) })} />
          <NumberField label={t("Within (min)")} value={condition.window_minutes} min={1} step="1" onChange={(minutes) => set({ window_minutes: Math.max(1, Math.round(minutes ?? 60)) })} hint={t("It clears when the window holds fewer again.")} />
        </>}
        {picking && <PickDialog want={["event"]} where={where} onClose={() => setPicking(false)} onPick={(pick, each) => set({
          event: { ...event, kinds: event.kinds.includes(pick.id) ? event.kinds : [...event.kinds, pick.id], about: each ? "subject" : pick.relativeTo ? `asset:${pick.relativeTo}` : "any" },
        })} />}
      </>}
      <NumberField label={t("For at least (min)")} value={condition.for_seconds ? condition.for_seconds / 60 : null} min={0} onChange={(minutes) => set({ for_seconds: Math.max(0, Math.round((minutes ?? 0) * 60)) })} hint={t("Raised only once it holds this long. Empty: at once.")} />
      {condition.input === "value" && <NumberField label={t("Values in a row")} value={condition.for_points || null} min={0} step="1" onChange={(points) => set({ for_points: Math.max(0, Math.round(points ?? 0)) })} hint={t("An app's series has one value per run: health under 50 for 5 runs.")} />}
    </div>
  </fieldset>;
}

function SimpleForm({ simple, where, onChange }: { simple: SimpleLogic; where: Where; onChange: (simple: SimpleLogic) => void }) {
  const [sentence, setSentence] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => { api.simple(simple).then((found) => setSentence(found.sentence)).catch(() => setSentence("")); }, 300);
    return () => window.clearTimeout(timer);
  }, [simple]);
  const setCondition = (index: number, condition: SimpleCondition) => onChange({ ...simple, conditions: simple.conditions.map((item, at) => (at === index ? condition : item)) });
  return <div className="al-simple">
    {simple.conditions.map((condition, index) => <div key={index}>
      {index > 0 && <div className="pc-segmented al-combine" role="group" aria-label={t("Join the conditions with")}>
        <button type="button" className={simple.combine === "and" ? "on" : ""} onClick={() => onChange({ ...simple, combine: "and" })}>{t("and")}</button>
        <button type="button" className={simple.combine === "or" ? "on" : ""} onClick={() => onChange({ ...simple, combine: "or" })}>{t("or")}</button>
      </div>}
      <ConditionRow index={index} condition={condition} where={where} onChange={(item) => setCondition(index, item)}
        onRemove={simple.conditions.length > 1 ? () => onChange({ ...simple, conditions: simple.conditions.filter((_, at) => at !== index) }) : undefined} />
    </div>)}
    <div className="al-inline al-simple-foot">
      {simple.conditions.length < MAX_CONDITIONS && <button type="button" className="button button-small button-secondary" onClick={() => onChange({ ...simple, conditions: [...simple.conditions, valueCondition()] })}><Plus size={14} />{t("Add a condition")}</button>}
      <div className="al-narrow"><NumberField label={t("Clears after back to normal for (min)")} value={simple.clear_after_seconds ? simple.clear_after_seconds / 60 : null} min={0} onChange={(minutes) => onChange({ ...simple, clear_after_seconds: Math.max(0, Math.round((minutes ?? 0) * 60)) })} /></div>
    </div>
    {sentence && <p className="notice notice-ok al-sentence"><b>{t("When")}</b> {sentence}{t(", it raises.")}</p>}
  </div>;
}

/** What `check(inputs)` receives and answers, beside the code: the inputs by name, then the answer. */
function PythonGuide({ labels }: { labels: string[] }) {
  return <aside className="al-python-guide">
    <h3 className="al-sub">{t("Inputs")}</h3>
    {labels.length
      ? <ul>{labels.map((label) => <li key={label}><code>inputs.{label}</code></li>)}</ul>
      : <p className="muted small">{t("No input yet: add the values the code reads.")}</p>}
    <p className="small">{t("Each input is its value's last reading: a number (True or False for a yes/no value), or None before the first one or when it has no data.")}</p>
    <h3 className="al-sub">{t("Answer")}</h3>
    <p className="small"><code>return True, "sentence"</code> {t("raises the alarm; the sentence is shown with it.")}<br /><code>return False, ""</code> {t("does not raise (or clears it).")}</p>
    <h3 className="al-sub">{t("How it runs")}</h3>
    <p className="small">{t("For each asset of the rule, at most once a minute, isolated: no files, no network, within a time limit. Modules: math, statistics, datetime, collections.")}</p>
  </aside>;
}

function PythonFormEditor({ form, where, onChange, canWrite }: { form: PythonForm; where: Where; onChange: (form: PythonForm) => void; canWrite: boolean }) {
  const [problems, setProblems] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.checkDiagram(pythonDiagram(form)).then((found) => setProblems(found.valid ? [] : found.errors ?? [])).catch(() => setProblems([]));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form]);
  const labels = form.inputs.map((item) => item.label);
  const setCode = (code: string) => onChange({ ...form, code });
  const editor = (tall: boolean) => <CodeEditor value={form.code} readOnly={!canWrite} problems={problems} label={t("Code")} onChange={setCode} tall={tall} />;
  return <div className="al-python">
    <span className="al-label">{t("Inputs")}</span>
    <ul className="al-inputs">
      {form.inputs.map((input, index) => <li key={index} className="al-inline">
        <input className="al-input-name" aria-label={t("Name in the code")} value={input.label} disabled={!canWrite} onChange={(event) => onChange({ ...form, inputs: form.inputs.map((item, at) => (at === index ? { ...item, label: inputLabel(event.target.value, labels.filter((_, other) => other !== index)) } : item)) })} />
        <span className="al-chip">{valueWords(input.value)}</span>
        {canWrite && <button type="button" className="icon-button" aria-label={t("Remove {name}", { name: input.label })} onClick={() => onChange({ ...form, inputs: form.inputs.filter((_, at) => at !== index) })}><X size={14} /></button>}
      </li>)}
    </ul>
    {canWrite && <ValueField label={t("Add an input")} value={null} where={where} onChange={(value) => onChange({ ...form, inputs: [...form.inputs, { label: inputLabel(value.name || value.role || value.signal, labels), value }] })} />}
    <div className="al-python-head">
      <span className="al-label">{t("Code")}</span>
      <button type="button" className="button button-small button-secondary" onClick={() => setExpanded(true)}><Maximize2 size={14} />{t("Expand")}</button>
    </div>
    <div className="al-python-body">
      {!expanded && editor(false)}
      <PythonGuide labels={labels} />
    </div>
    {!canWrite && <small className="muted">{t("Only an administrator writes or changes Python. You can change the rest of the rule.")}</small>}
    {canWrite && form.inputs.length > 0 && <button type="button" className="button-link small" onClick={() => setCode(pythonTemplate(labels))}>{t("Start again from the example for these inputs")}</button>}
    <NumberField label={t("Clears after back to normal for (min)")} value={form.clearAfter ? form.clearAfter / 60 : null} min={0} onChange={(minutes) => onChange({ ...form, clearAfter: Math.max(0, Math.round((minutes ?? 0) * 60)) })} />
    {problems.length > 0 && <ErrorBox text={problems.join(" ")} />}
    {expanded && <Dialog title={t("Python code")} onClose={() => setExpanded(false)} wide
      footer={<button type="button" className="button button-primary" onClick={() => setExpanded(false)}>{t("Done")}</button>}>
      <div className="al-python-body al-python-full">{editor(true)}<PythonGuide labels={labels} /></div>
      {problems.length > 0 && <ErrorBox text={problems.join(" ")} />}
    </Dialog>}
  </div>;
}

/** The When section: the editor chosen and its form. */
export function WhenEditor({ draft, update, canWritePython }: { draft: RuleDraft; update: (patch: Partial<RuleDraft>) => void; canWritePython: boolean }) {
  const [error, setError] = useState("");
  const form = draft.editor === "python" ? pythonForm(draft.diagram) : null;

  async function switchTo(editor: Editor) {
    if (editor === draft.editor) return;
    setError("");
    try {
      if (editor === "python") {
        const existing = pythonForm(draft.diagram);
        update({ editor, simple: null, diagram: pythonDiagram(existing && draft.editor !== "simple" ? existing : pythonFromSimple(draft.simple)) });
      } else {
        update({ editor, simple: { conditions: [valueCondition()], combine: "and", clear_after_seconds: 0 } });
      }
    } catch (err) {
      setError(message(err));
    }
  }

  return <div className="al-when">
    <div className="al-types" role="radiogroup" aria-label={t("Written as")}>
      {EDITORS.map(([id, label, detail, Icon]) => {
        const locked = id === "python" && !canWritePython && draft.editor !== "python";
        return <button key={id} type="button" role="radio" aria-checked={draft.editor === id} disabled={locked} title={locked ? t("Only an administrator writes Python.") : undefined}
          className={draft.editor === id ? "al-type on" : "al-type"} onClick={() => void switchTo(id)}>
          <b><Icon size={16} /> {t(label)}</b><small>{t(detail)}</small>
        </button>;
      })}
    </div>
    {draft.editor === "python" && <p className="muted small">{t("Back to Simple starts the conditions over.")}</p>}
    {error && <ErrorBox text={error} />}
    {draft.editor === "simple" && draft.simple && <SimpleForm simple={draft.simple} where={draft.where} onChange={(simple) => update({ simple })} />}
    {draft.editor === "python" && (form
      ? <PythonFormEditor form={form} where={draft.where} canWrite={canWritePython} onChange={(next) => update({ diagram: pythonDiagram(next) })} />
      : <p className="notice">{t("This rule's logic holds more than values and one Python block. It keeps running as it is; to change its logic, write it again in Simple or Python.")}</p>)}
    {draft.editor === "blocks" && <p className="notice">{t("This rule was drawn in Blocks, which Alarms no longer offers. It keeps running as drawn; to change its logic, write it again in Simple or Python above.")}</p>}
  </div>;
}
