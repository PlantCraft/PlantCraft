/**
 * Schedules (owner, 2026-10-23): when each algorithm runs, on what, with which window of data.
 * One kind of schedule: the loops' monitoring round, Signal quality and each algorithm on assets
 * are schedules like any other, paused, re-timed and run from here. A schedule opens on a page of
 * its own with a preview of what it will queue (how many executions, the next occurrences and
 * whether the queue keeps up) before it is saved.
 */
import { AssetSearch, chosenFolder, confirmAction, DataTable, FolderColumn, FolderField, FolderPlaceLine, inFolder, LOCAL_ZONE, NO_FOLDER, putInFolder, recipientLabel, RecipientPicker, rememberFolder, timeZoneLabel, TimeZoneSelect, useAssistantPage, useFolders, type DataColumn, type GroupOption, type PersonOption } from "@plantcraft/ui";
import { BellPlus, History, Pause, Play, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { ParameterField } from "@plantcraft/ui/blockEditor";
import { blockCatalog } from "./AlgorithmEditor";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, formatNumber, t } from "./i18n";
import { navigate } from "./nav";
import { BLANK_WHEN, FREQUENCIES, timingOf, WEEKDAY_SHORT, whenOf, whenProblem, type Frequency, type When } from "./scheduleWhen";
import type { Algorithm, AssetChoice, CatalogBlock, Me, NodeParameters, OutputChoice, OutputKeep, RecordedOutput, RetryPolicy, Schedule, SchedulePreview, ScheduleStats } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
/** The Alarms app's new rule, filled in for a schedule (repeated criticals per asset, its owner told). */
export function alarmRuleHref(scheduleId: string, name: string): string {
  return `/alarm/rules/new?${new URLSearchParams({ schedule: scheduleId, name }).toString()}`;
}

/** The schedules' places in the queue: a person's "Run now" is 100, a replay of the past 10. */
export const PRIORITIES = [{ value: 80, label: "High" }, { value: 50, label: "Normal" }, { value: 20, label: "Low" }];

export function priorityLabel(value: number | undefined): string {
  const found = PRIORITIES.find((item) => item.value === value);
  return t(found ? found.label : "Normal");
}

export function cadenceText(schedule: Pick<Schedule, "cadence" | "interval_minutes" | "time_local" | "weekday" | "scheduled_for" | "when">): string {
  if (schedule.cadence === "calendar") return schedule.when ?? t("on a calendar");
  if (schedule.cadence === "interval") {
    const minutes = Number(schedule.interval_minutes ?? 0);
    return minutes < 1 ? t("every {n} s", { n: Math.round(minutes * 60) }) : t("every {n} min", { n: Number(minutes.toFixed(2)) });
  }
  if (schedule.cadence === "once") return schedule.scheduled_for ? t("once, {when}", { when: formatDate(schedule.scheduled_for) }) : t("once");
  if (schedule.cadence === "hourly") return t("every hour at :{minute}", { minute: (schedule.time_local ?? "00:00").slice(3) });
  if (schedule.cadence === "weekly") return t("{day} at {time}", { day: t(WEEKDAYS[schedule.weekday ?? 0]), time: schedule.time_local ?? "08:00" });
  return t("daily at {time}", { time: schedule.time_local ?? "08:00" });
}

function lastText(schedule: Schedule): string {
  if (schedule.last_run_by_hand) return t("Run by hand");
  const summary = schedule.last_summary ?? {};
  if (typeof summary.skipped === "number" && summary.skipped > 0) return t("{jobs} queued, {skipped} skipped", { jobs: summary.jobs ?? 0, skipped: summary.skipped });
  if (typeof summary.jobs === "number") return t("{jobs} queued", { jobs: summary.jobs });
  return "";
}

export function SchedulesPage({ me }: { me: Me }) {
  const [schedules, setSchedules] = useState<Schedule[] | null>(null);
  const [error, setError] = useState("");
  const [folders, reloadFolders] = useFolders("schedule");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  const load = () => api.schedules().then((items) => { setSchedules(items); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); }, []);
  useAssistantPage({ place: t("Analytics › Monitors"), page: "linkcraft:schedules", platformUrl: me.processcraft_url, facts: { schedules: schedules?.length ?? 0 },
    view: { rows: (schedules ?? []).slice(0, 30).map((item) => `${item.schedule_id}: ${item.name.slice(0, 80)} (${item.algorithm?.name ?? item.kind ?? ""}, ${item.enabled ? "on" : "paused"}${item.next_run_at ? `, next ${item.next_run_at}` : ""})`) } });
  const act = (action: () => Promise<unknown>) => (event: { stopPropagation: () => void }) => {
    event.stopPropagation();
    setError("");
    action().then(() => load()).catch((err: Error) => setError(err.message));
  };
  const columns: DataColumn<Schedule>[] = [
    { key: "name", label: t("Monitor"), sort: (item) => item.name, render: (item) => <><Link to={`/schedules/${encodeURIComponent(item.schedule_id)}`}><b>{item.name}</b></Link><small>{item.algorithm?.name ?? t("Each loop's own algorithm")}</small></> },
    { key: "subjects", label: t("On"), sort: (item) => item.subject_label ?? "", render: (item) => item.subject_label },
    { key: "when", label: t("When"), sort: (item) => item.cadence, render: (item) => <>{cadenceText(item)}<small>{timeZoneLabel(item.timezone || LOCAL_ZONE, t("Local time"))}</small></> },
    { key: "next", label: t("Next"), sort: (item) => item.next_run_at ?? "", render: (item) => (item.enabled ? formatDate(item.next_run_at ?? null) : "—") },
    { key: "last", label: t("Last"), className: "hide-narrow", sort: (item) => item.last_run_at ?? "", render: (item) => <>{item.last_run_at ? formatAgo(item.last_run_at) : "—"}<small>{lastText(item)}</small></> },
    { key: "priority", label: t("Priority"), className: "hide-narrow", sort: (item) => item.priority ?? 50, render: (item) => priorityLabel(item.priority) },
    { key: "state", label: t("Status"), sort: (item) => Number(Boolean(item.enabled)), render: (item) => <Pill status={item.enabled ? "ok" : "unknown"} label={item.enabled ? t("Active") : t("Paused")} /> },
    ...(me.can_edit ? [{
      key: "actions", label: "", render: (item: Schedule) => <div className="row-actions">
        <button type="button" className="icon-button" title={item.enabled ? t("Pause") : t("Resume")} aria-label={item.enabled ? t("Pause") : t("Resume")} onClick={act(() => api.updateSchedule(item.schedule_id, { enabled: !item.enabled }))}>{item.enabled ? <Pause size={16} /> : <Play size={16} />}</button>
      </div>,
    }] : []),
  ];
  return <>
    <Heading eyebrow={t("When algorithms run")} title={t("Monitors")}
      detail={t("Each monitor says which algorithm runs, on what, how often and on how much data. Every occurrence puts its runs in the queue.")}
      actions={<>
        {me.can_edit && <Link to={folder && folder !== NO_FOLDER ? `/schedules/new?folder=${encodeURIComponent(folder)}` : "/schedules/new"} className="button button-primary"><Plus size={16} />{t("New monitor")}</Link>}
      </>} />
    {error && <ErrorBox text={error} />}
    {!schedules ? (error ? null : <Loading />) : <div className="pc-folder-layout">
    <FolderColumn kind="schedule" list={folders} chosen={folder} onChoose={(value) => { setFolder(value); rememberFolder("/schedules", value); }} total={schedules.length} canEdit={me.can_edit} onChanged={reloadFolders} />
    <section className="methods-main"><DataTable
      rows={schedules.filter((item) => inFolder(folders, item.schedule_id, folder))}
      columns={columns}
      rowKey={(item) => item.schedule_id}
      onRowClick={(item) => navigate(`/schedules/${encodeURIComponent(item.schedule_id)}`)}
      searchText={(item) => `${item.name} ${item.algorithm?.name ?? ""} ${item.subject_label ?? ""} ${item.owner ?? ""}`}
      searchPlaceholder={t("Search monitor, algorithm or target")}
      label={t("Monitors")}
      empty={folder ? t("No monitor in this folder.") : t("No monitor yet.")}
    /></section></div>}
  </>;
}

type Form = {
  name: string; profile_id: string; owner: string; mode: "all" | "list" | "filter"; ids: string; assets: string[]; q: string;
  when: When; timezone: string; lookback_minutes: number; priority: number; spread_minutes: number; enabled: boolean; retry: RetryPolicy;
  outputs: Record<string, OutputChoice>; node_parameters: NodeParameters;
};

/** What a schedule does by default when an execution cannot read the plant or finds no data. */
export const DEFAULT_RETRY: RetryPolicy = { enabled: true, count: 2, wait_minutes: 5, abort_on_next: true };

const BLANK: Form = {
  name: "", profile_id: "", owner: "", mode: "all", ids: "", assets: [], q: "", when: BLANK_WHEN,
  timezone: "", lookback_minutes: 1440, priority: 50, spread_minutes: 0, enabled: true, retry: DEFAULT_RETRY, outputs: {}, node_parameters: {},
};
/** Below this a schedule runs more often than a first look needs; the form asks before saving it. */
export const FREQUENT_MINUTES = 5;

/** An owner as the suite names people and groups (`user:<name>`, `group:<id>`); older schedules kept a bare user name. */
export function ownerRef(value: string | null | undefined): string {
  const text = (value ?? "").trim();
  if (!text) return "";
  return /^(user|group):/.test(text) ? text : `user:${text}`;
}

function formOf(schedule: Schedule): Form {
  const selector = schedule.selector ?? null;
  const onAssets = schedule.subject_kind === "asset";
  return {
    name: schedule.name, profile_id: schedule.profile_id ?? "", owner: ownerRef(schedule.owner ?? schedule.created_by),
    mode: selector ? (selector.mode as Form["mode"]) ?? "all" : "list", ids: !onAssets ? (selector ? (selector.ids ?? []).join("\n") : schedule.loop_id) : "",
    assets: onAssets ? selector?.ids ?? [] : [], q: selector?.q ?? "",
    when: whenOf(schedule), timezone: schedule.timezone || LOCAL_ZONE, lookback_minutes: schedule.lookback_minutes, priority: schedule.priority ?? 50,
    spread_minutes: Number(schedule.spread_minutes ?? 0), enabled: Boolean(schedule.enabled), retry: { ...DEFAULT_RETRY, ...schedule.retry },
    outputs: schedule.outputs ?? {}, node_parameters: schedule.method_config?.node_parameters ?? {},
  };
}

/** Where a parameter's value comes from: the block's default, the algorithm, or this monitor. */
export function parameterSource(algorithm: unknown, monitor: unknown): "monitor" | "algorithm" | "block" {
  return monitor !== undefined ? "monitor" : algorithm !== undefined ? "algorithm" : "block";
}

const SOURCE_TEXT = { monitor: "set here", algorithm: "from the algorithm", block: "block's default" } as const;

/** The defaults cascade (owner, 2026-10-27): every parameter of the algorithm's blocks with its
 * value and where it comes from; a value set here is this monitor's only. */
function MonitorParameters({ algorithm, value, onChange, disabled }: { algorithm: Algorithm; value: NodeParameters; onChange: (value: NodeParameters) => void; disabled: boolean }) {
  const [specs, setSpecs] = useState<Record<string, CatalogBlock>>({});
  useEffect(() => { blockCatalog().then((catalog) => setSpecs(Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block])))).catch(() => setSpecs({})); }, []);
  const nodes = (algorithm.diagram?.nodes ?? []).filter((node) => !/^(input|output)\./.test(node.block) && (specs[node.block]?.parameters ?? []).length);
  if (!Object.keys(specs).length) return <Loading />;
  if (!nodes.length) return <p className="muted small">{t("No block of this algorithm has parameters.")}</p>;
  function setOne(nodeId: string, name: string, next: unknown) {
    const own = { ...(value[nodeId] ?? {}) };
    if (next === undefined) delete own[name]; else own[name] = next;
    const all = { ...value, [nodeId]: own };
    if (!Object.keys(own).length) delete all[nodeId];
    onChange(all);
  }
  return <div className="schedule-parameters">{nodes.map((node) => <div key={node.id} className="blkf-row alg-node-parameters">
    <h3>{node.label || specs[node.block]?.name || node.block} <small className="muted pc-mono">{node.id}</small></h3>
    <div className="alg-node-fields">{specs[node.block].parameters.map((parameter) => {
      const mine = value[node.id]?.[parameter.name];
      const theirs = node.parameters?.[parameter.name];
      const source = parameterSource(theirs, mine);
      const shown = { ...node, parameters: { ...(node.parameters ?? {}), ...(value[node.id] ?? {}) } };
      return <div key={parameter.name} className={`schedule-parameter schedule-parameter-${source}`}>
        <ParameterField node={shown} parameter={parameter} readOnly={disabled} onSet={(next) => setOne(node.id, parameter.name, next === undefined ? undefined : next)} />
        <small className="muted">{t(SOURCE_TEXT[source])}{source === "monitor" && !disabled && <> · <button type="button" className="link-button" onClick={() => setOne(node.id, parameter.name, undefined)}>{t("follow the algorithm")}</button></>}</small>
      </div>;
    })}</div>
  </div>)}</div>;
}

/** The request body of a form: only what its frequency uses; an algorithm on assets runs on the assets chosen. */
export function payloadOf(form: Form, onAssets = false): Record<string, unknown> {
  const ids = form.ids.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean);
  const selector = onAssets ? { mode: "list", ids: form.assets }
    : form.mode === "list" ? { mode: "list", ids } : form.mode === "filter" ? { mode: "filter", q: form.q.trim() } : { mode: "all" };
  return {
    name: form.name.trim() || t("Monitor"), profile_id: form.profile_id || null, owner: form.owner || null,
    selector, timezone: form.timezone || LOCAL_ZONE, ...timingOf(form.when),
    // Empty (0) is Analytics' default window: left out, as the API reads no field (it refuses 0).
    lookback_minutes: Number(form.lookback_minutes) || undefined, priority: Number(form.priority), spread_minutes: Number(form.spread_minutes),
    retry: { ...form.retry, count: Number(form.retry.count), wait_minutes: Number(form.retry.wait_minutes) },
    ...(onAssets ? { outputs: form.outputs, node_parameters: form.node_parameters } : {}),
  };
}

/** How long an output may be kept: a single value forever or for days, a series for its last executions. */
export function keepOptions(kind: RecordedOutput["kind"], current?: OutputKeep): { value: string; label: string }[] {
  const found = kind === "series"
    ? [1, 3, 10, 30, 100].map((runs) => ({ value: `runs:${runs}`, label: runs === 1 ? t("The last run") : t("The last {n} runs", { n: runs }) }))
    : [{ value: "forever", label: t("Forever") }, ...[30, 90, 400, 730, 1825].map((days) => ({ value: `days:${days}`, label: days % 365 === 0 || days === 730 || days === 1825 ? t("{n} years", { n: Math.round(days / 365) }) : t("{n} days", { n: days }) }))];
  const now = current ? keepValue(current) : "";
  if (now && !found.some((item) => item.value === now)) {
    found.push({ value: now, label: current?.runs ? t("The last {n} runs", { n: current.runs }) : t("{n} days", { n: current?.days ?? 0 }) });
  }
  return found;
}

export function keepValue(keep: OutputKeep): string {
  return keep.forever ? "forever" : keep.runs ? `runs:${keep.runs}` : `days:${keep.days ?? 0}`;
}

export function keepOf(value: string): OutputKeep {
  if (value === "forever") return { forever: true };
  const [unit, count] = value.split(":");
  return unit === "runs" ? { runs: Number(count) } : { days: Number(count) };
}

/** Bytes as a person reads a size: 512 B, 3.4 kB, 12 MB, 1.2 GB. */
export function sizeText(bytes: number): string {
  const units = ["B", "kB", "MB", "GB", "TB"];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) { value /= 1000; unit += 1; }
  return `${formatNumber(value, value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

/** What the recorded outputs cost on ``assets`` assets: values written a day and what is kept (a year of those kept forever). */
export function outputsCost(rows: RecordedOutput[], assets: number): { perDay: number; bytes: number; grows: boolean } {
  const kept = rows.filter((row) => row.record);
  return {
    perDay: kept.reduce((sum, row) => sum + row.values_per_day, 0) * assets,
    bytes: kept.reduce((sum, row) => sum + row.stored_bytes, 0) * assets,
    grows: kept.some((row) => row.grows),
  };
}

const OUTPUT_KINDS: Record<RecordedOutput["kind"], string> = { number: "A value per run", verdict: "A result: its score and its status", series: "A whole series per run" };

/** The schedule's "Recorded outputs" (owner, 2026-10-25, D6): what each execution writes in the
 * Historian, one row per output the algorithm records, and what it costs before it is saved. */
function RecordedOutputs({ rows, assets, choices, onChange, disabled }: { rows: RecordedOutput[]; assets: number; choices: Record<string, OutputChoice>; onChange: (choices: Record<string, OutputChoice>) => void; disabled: boolean }) {
  if (!rows.length) return <p className="muted small schedule-note">{t("The algorithm records no output. Mark the ports to record in its diagram.")}</p>;
  const choose = (row: RecordedOutput, change: Partial<OutputChoice>) => {
    const before = choices[row.key] ?? { record: row.record };
    onChange({ ...choices, [row.key]: { ...before, keep: before.keep ?? row.keep, ...change } });
  };
  // The person's choices show at once; the costs follow with the next preview.
  const shown = rows.map((row) => ({ ...row, record: choices[row.key]?.record ?? row.record, keep: choices[row.key]?.keep ?? row.keep }));
  const total = outputsCost(shown, Math.max(assets, 1));
  return <>
    <ul className="schedule-outputs">{shown.map((row) => <li key={row.key} className={row.record ? "" : "schedule-output-off"}>
      <label className="schedule-toggle"><input type="checkbox" checked={row.record} disabled={disabled} onChange={(event) => choose(row, { record: event.target.checked })} />
        <span><b>{row.name}</b><small>{[t(OUTPUT_KINDS[row.kind]), row.unit].filter(Boolean).join(" · ")}</small></span></label>
      <Field label={t("Keep")}>
        <select value={keepValue(row.keep)} disabled={disabled || !row.record} onChange={(event) => choose(row, { keep: keepOf(event.target.value) })}>
          {keepOptions(row.kind, row.keep).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </Field>
      {row.record && <small className="muted schedule-output-cost">{t("About {values} values a day; keeps {size}", { values: formatNumber(row.values_per_day * Math.max(assets, 1), 0), size: sizeText(row.stored_bytes * Math.max(assets, 1)) })}{row.grows ? ` ${t("after a year, and it keeps growing")}` : ""}</small>}
    </li>)}</ul>
    <p className="schedule-output-total">{t(assets === 1 ? "In all, on 1 asset: about {values} values a day; keeps {size}" : "In all, on {count} assets: about {values} values a day; keeps {size}", { count: Math.max(assets, 1), values: formatNumber(total.perDay, 0), size: sizeText(total.bytes) })}{total.grows ? ` ${t("after a year, and it keeps growing")}` : ""}.</p>
    <p className="muted small schedule-note">{t("The Historian keeps these values as the monitor says: change how long here. Turning one off stops its writes; what it wrote stays until its time is up.")}</p>
  </>;
}

/** How often the form runs it, in minutes, when that is fixed (to ask before a very frequent one). */
function stepMinutes(when: When): number | null {
  if (when.freq === "interval") return Number(when.interval_minutes);
  if (when.freq === "minutes") return Number(when.every);
  return null;
}

function Field({ label, hint, children, wide }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return <label className={`schedule-field${wide ? " schedule-field-wide" : ""}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

/** A field of several controls (weekdays, times): a group, not a label, so a click on its name toggles nothing. */
/** A part of the form (owner D21, 2026-10-26): its number, title and what it is for on the left,
 * its fields on the right, the whole width of the page; on a phone they stack. */
function Part({ number, title, detail, disabled, children }: { number: number; title: string; detail?: string; disabled?: boolean; children: ReactNode }) {
  return <fieldset className="panel schedule-section" disabled={disabled}>
    <legend className="sr-only">{title}</legend>
    <div className="schedule-part">
      <header className="schedule-part-head" aria-hidden="true">
        <span className="blkf-part-number pc-num">{number}</span>
        <span className="schedule-legend-text"><b>{title}</b>{detail && <small>{detail}</small>}</span>
      </header>
      <div className="schedule-part-body">{children}</div>
    </div>
  </fieldset>;
}

/** What the schedule will queue, under its timing: the occurrences in words, the next five and
 * how long one takes to drain (it used to float beside the form). */
function SchedulePreviewBox({ preview, problem, timezone, waiting }: { preview: SchedulePreview | null; problem: string; timezone: string; waiting: boolean }) {
  return <section className="schedule-preview" aria-label={t("Preview")}>
    <h3>{t("Preview")}</h3>
    {problem ? <p className="muted">{t(problem)}</p> : !preview ? <p className="muted">{waiting ? t("Choose the assets to see what it will queue.") : t("Fill in the form to see what it will queue.")}</p> : <div className="schedule-preview-grid">
      <div>
        {preview.when && <p className="schedule-when"><b>{preview.when}</b><small>{timeZoneLabel(timezone, t("Local time"))}</small></p>}
        <p><b className="pc-num">{preview.executions}</b> {t("runs each occurrence")}</p>
        <p className="muted small">{preview.seconds_each === null
          ? t("Not measured yet: no run of this kind has finished.")
          : t("About {time} per occurrence with {workers} workers ({each} each).", { time: formatDuration(preview.drain_seconds ?? 0), workers: preview.workers, each: formatDuration(preview.seconds_each) })}</p>
      </div>
      <div>
        <span className="label">{t("Next occurrences")}</span>
        {preview.next_runs.length > 0 ? <ul>{preview.next_runs.map((item) => <li key={item}>{formatDate(item)}</li>)}</ul>
          : <p className="muted">{t("No occurrence ahead: check the dates.")}</p>}
      </div>
      {preview.warning && <div className="notice schedule-preview-warning" role="alert">{preview.warning}</div>}
    </div>}
  </section>;
}

function GroupField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div className="schedule-field" role="group" aria-label={label}><span>{label}</span>{children}{hint && <small>{hint}</small>}</div>;
}

const FREQUENCY_LABELS: Record<Frequency, string> = {
  once: "Once", minutes: "Every N minutes", hours: "Every N hours", days: "Every N days", weeks: "Every N weeks", months: "Every N months", interval: "Every N seconds (as it is)",
};
const EVERY_UNITS: Record<string, [string, string]> = {
  minutes: ["minute", "minutes"], hours: ["hour", "hours"], days: ["day", "days"], weeks: ["week", "weeks"], months: ["month", "months"],
};
const ORDINALS = [{ value: 1, label: "First" }, { value: 2, label: "Second" }, { value: 3, label: "Third" }, { value: 4, label: "Fourth" }, { value: -1, label: "Last" }];

/** The weekdays as toggles: Mon to Sun. */
function WeekdayPicker({ value, onChange }: { value: number[]; onChange: (days: number[]) => void }) {
  return <div className="schedule-weekdays">
    {WEEKDAY_SHORT.map((day, index) => {
      const on = value.includes(index);
      return <button key={day} type="button" className={`schedule-day${on ? " is-on" : ""}`} aria-pressed={on}
        onClick={() => onChange(on ? value.filter((item) => item !== index) : [...value, index])}>{t(day)}</button>;
    })}
  </div>;
}

/** The times of day it runs: one or more, each removable. */
function TimesPicker({ value, onChange }: { value: string[]; onChange: (times: string[]) => void }) {
  return <div className="schedule-times">
    {value.map((item, index) => <span key={index} className="schedule-time">
      <input type="time" value={item} aria-label={t("Time {n}", { n: index + 1 })} onChange={(event) => onChange(value.map((other, at) => (at === index ? event.target.value : other)))} />
      {value.length > 1 && <button type="button" className="icon-button" aria-label={t("Remove {time}", { time: item })} title={t("Remove")} onClick={() => onChange(value.filter((_, at) => at !== index))}><X size={14} /></button>}
    </span>)}
    {value.length < 48 && <button type="button" className="button button-secondary button-small" onClick={() => onChange([...value, value[value.length - 1] ?? "08:00"])}><Plus size={14} />{t("Add a time")}</button>}
  </div>;
}

/** When it runs (owner, 2026-10-24): a frequency, every N, the days and times, a first and last day. */
function WhenFields({ when, onChange }: { when: When; onChange: (when: When) => void }) {
  const set = <K extends keyof When>(key: K, value: When[K]) => onChange({ ...when, [key]: value });
  const units = EVERY_UNITS[when.freq];
  const clocked = ["minutes", "hours"].includes(when.freq);
  const frequencies: Frequency[] = when.freq === "interval" ? [...FREQUENCIES, "interval"] : [...FREQUENCIES];
  return <>
    <div className="schedule-row">
      <Field label={t("Runs")}>
        <select value={when.freq} onChange={(event) => {
          const freq = event.target.value as Frequency;
          onChange({ ...when, freq, every: freq === "minutes" && when.freq !== "minutes" ? 15 : when.freq === freq ? when.every : 1, weekdays: freq === "weeks" && !when.weekdays.length ? [0] : when.weekdays });
        }}>{frequencies.map((item) => <option key={item} value={item}>{t(FREQUENCY_LABELS[item])}</option>)}</select>
      </Field>
      {units && <Field label={t("Every")}><span className="schedule-every">
        <input type="number" min={1} max={1000} value={when.every} onChange={(event) => set("every", Number(event.target.value))} />
        <span>{t(Number(when.every) === 1 ? units[0] : units[1])}</span></span></Field>}
      {when.freq === "interval" && <Field label={t("Every (minutes)")}><input type="number" min={0.1} step="any" value={when.interval_minutes} onChange={(event) => set("interval_minutes", Number(event.target.value))} /></Field>}
    </div>
    {when.freq === "once" && <Field label={t("On")}><input type="datetime-local" value={when.scheduled_for.slice(0, 16)} onChange={(event) => set("scheduled_for", event.target.value)} /></Field>}
    {when.freq === "weeks" && <GroupField label={t("On these days")}><WeekdayPicker value={when.weekdays} onChange={(days) => set("weekdays", days)} /></GroupField>}
    {(clocked || when.freq === "days") && <GroupField label={t("Only on")} hint={t("None chosen: every day.")}><WeekdayPicker value={when.weekdays} onChange={(days) => set("weekdays", days)} /></GroupField>}
    {when.freq === "months" && <div className="schedule-row">
      <Field label={t("On")}><select value={when.month_mode} onChange={(event) => set("month_mode", event.target.value as When["month_mode"])}>
        <option value="day">{t("A day of the month")}</option><option value="weekday">{t("A weekday of the month")}</option></select></Field>
      {when.month_mode === "day"
        ? <Field label={t("Day")}><select value={when.month_day} onChange={(event) => set("month_day", Number(event.target.value))}>
          {Array.from({ length: 31 }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}<option value={-1}>{t("The last day")}</option></select></Field>
        : <><Field label={t("Which")}><select value={when.month_n} onChange={(event) => set("month_n", Number(event.target.value))}>{ORDINALS.map((item) => <option key={item.value} value={item.value}>{t(item.label)}</option>)}</select></Field>
          <Field label={t("Weekday")}><select value={when.month_weekday} onChange={(event) => set("month_weekday", Number(event.target.value))}>{WEEKDAYS.map((day, index) => <option key={day} value={index}>{t(day)}</option>)}</select></Field></>}
    </div>}
    {["days", "weeks", "months"].includes(when.freq) && <GroupField label={t("At")} hint={t("Times in the monitor's time zone.")}><TimesPicker value={when.times} onChange={(times) => set("times", times)} /></GroupField>}
    {clocked && <>
      <label className="schedule-toggle"><input type="checkbox" checked={when.between} onChange={(event) => set("between", event.target.checked)} />{t("Only between two times of day")}</label>
      {when.between && <div className="schedule-row">
        <Field label={t("From")}><input type="time" value={when.between_from} onChange={(event) => set("between_from", event.target.value)} /></Field>
        <Field label={t("To")}><input type="time" value={when.between_to} onChange={(event) => set("between_to", event.target.value)} /></Field>
      </div>}
    </>}
    {when.freq !== "once" && when.freq !== "interval" && <div className="schedule-row">
      <Field label={t("First day")} hint={t("Empty: from now.")}><input type="date" value={when.start} onChange={(event) => set("start", event.target.value)} /></Field>
      <Field label={t("Last day")} hint={t("Empty: no end.")}><input type="date" value={when.end} min={when.start || undefined} onChange={(event) => set("end", event.target.value)} /></Field>
    </div>}
  </>;
}

/** What it does when an execution cannot read the plant or finds no data (owner, 2026-10-24, D5). */
function RetryFields({ retry, onChange }: { retry: RetryPolicy; onChange: (retry: RetryPolicy) => void }) {
  const set = <K extends keyof RetryPolicy>(key: K, value: RetryPolicy[K]) => onChange({ ...retry, [key]: value });
  return <>
    <label className="schedule-toggle"><input type="checkbox" checked={retry.enabled} onChange={(event) => set("enabled", event.target.checked)} />{t("Try again when it cannot read the plant or finds no data")}</label>
    {retry.enabled && <>
      <div className="schedule-row">
        <Field label={t("Tries again")}><select value={retry.count} onChange={(event) => set("count", Number(event.target.value))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 1 ? t("Once") : t("{n} times", { n })}</option>)}</select></Field>
        <Field label={t("Waits (minutes)")}><input type="number" min={0.5} max={240} step="any" value={retry.wait_minutes} onChange={(event) => set("wait_minutes", Number(event.target.value))} /></Field>
      </div>
      <label className="schedule-toggle"><input type="checkbox" checked={retry.abort_on_next} onChange={(event) => set("abort_on_next", event.target.checked)} />{t("Give up when the next occurrence comes first")}</label>
    </>}
    <p className="muted small schedule-note">{t("An error in the algorithm itself is not tried again: it would fail the same way.")}</p>
  </>;
}

/** A saved schedule's record over its latest executions (owner, 2026-10-25). */
function StatsStrip({ stats, scheduleId }: { stats: ScheduleStats; scheduleId: string }) {
  if (!stats.executions) return null;
  const share = (count: number) => `${Math.round((100 * count) / stats.executions)}%`;
  return <section className="panel schedule-stats" aria-label={t("Its record")}>
    <div><span className="label">{t("Runs")}</span><b className="pc-num">{stats.executions}</b>{stats.executions >= stats.limit && <small>{t("latest {n}", { n: stats.limit })}</small>}</div>
    <div><span className="label">{t("Failed")}</span><b className="pc-num">{stats.failed}</b><small>{share(stats.failed)}</small></div>
    <div><span className="label">{t("Tried again")}</span><b className="pc-num">{stats.retried}</b><small>{share(stats.retried)}</small></div>
    <div><span className="label">{t("Took")}</span><b className="pc-num">{stats.seconds_mean === null ? "—" : formatDuration(stats.seconds_mean)}</b>
      {stats.seconds_min !== null && stats.seconds_max !== null && <small>{t("{min} to {max}", { min: formatDuration(stats.seconds_min), max: formatDuration(stats.seconds_max) })}</small>}</div>
    <div><span className="label">{t("Last outcome")}</span><b>{stats.last_status === "failed" ? t("Failed") : t("Completed")}</b>
      {stats.last_change && <small>{t("since {when}", { when: formatAgo(stats.last_change.at) })}</small>}</div>
    <Link to={`/executions/${encodeURIComponent(scheduleId)}`} className="schedule-stats-link">{t("See the runs")}</Link>
  </section>;
}

/** The assets a schedule runs an algorithm on: find one to add, remove one from the list. */
function AssetList({ value, choices, onChange, disabled }: { value: string[]; choices: AssetChoice[]; onChange: (ids: string[]) => void; disabled?: boolean }) {
  const byId = new Map(choices.map((item) => [item.id, item]));
  const options = choices.filter((item) => !value.includes(item.id)).map((item) => ({ id: item.id, name: item.name, kind: item.kind, parent: item.path }));
  return <div className="schedule-assets">
    {!disabled && <AssetSearch assets={options} value="" label={t("Add an asset")} placeholder={t("Search an asset to add")} onPick={(picked) => { if (picked) onChange([...value, picked]); }} />}
    {value.length === 0 ? <p className="muted small">{t("No asset yet.")}</p> : <ul className="schedule-asset-list">{value.map((assetId) => {
      const found = byId.get(assetId);
      return <li key={assetId}><span><b>{found?.name ?? assetId}</b><small>{[assetId !== found?.name ? assetId : "", found?.kind, found?.path].filter(Boolean).join(" · ")}</small></span>
        {!disabled && <button type="button" className="icon-button" aria-label={t("Remove {asset}", { asset: found?.name ?? assetId })} title={t("Remove")} onClick={() => onChange(value.filter((item) => item !== assetId))}><X size={14} /></button>}</li>;
    })}</ul>}
  </div>;
}

/** One schedule on a page of its own (owner, 2026-10-24): what it runs, when, if it fails, who
 * answers for it, beside a preview that says it in words and lists the next occurrences. */
export function SchedulePage({ scheduleId, me }: { scheduleId: string | null; me: Me }) {
  // A new schedule goes in the folder its list showed (round 9, D14).
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [form, setForm] = useState<Form | null>(scheduleId ? null : { ...BLANK, timezone: LOCAL_ZONE, owner: ownerRef(me.username) });
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [choices, setChoices] = useState<AssetChoice[]>([]);
  const [people, setPeople] = useState<PersonOption[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  useAssistantPage({ title: schedule?.name, place: t("Analytics › Monitor {name}", { name: schedule?.name ?? t("New") }), page: "linkcraft:schedule", platformUrl: me.processcraft_url,
    facts: schedule ? { schedule: schedule.schedule_id, algorithm: schedule.algorithm?.name ?? "", enabled: Boolean(schedule.enabled), last_run: schedule.last_run_at ?? "", next_run: schedule.next_run_at ?? "", subjects: schedule.subject_count ?? 0 } : {} });
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const [frequentOk, setFrequentOk] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [replayHours, setReplayHours] = useState(24);
  const editable = schedule?.editable ?? { subjects: true, timing: true, algorithm: true, delete: true };
  const readOnly = !me.can_edit || (schedule?.kind === "round" && !me.is_admin);
  const load = () => {
    if (!scheduleId) return;
    api.schedule(scheduleId).then((found) => { setSchedule(found); setForm(formOf(found)); setError(""); }).catch((err: Error) => setError(err.message));
  };
  useEffect(() => {
    load();
    api.algorithms().then(setAlgorithms).catch(() => setAlgorithms([]));
    api.assetChoices().then(setChoices).catch(() => setChoices([]));
    if (me.can_edit) {
      api.blockPeople().then(setPeople).catch(() => setPeople([]));
      api.userGroups().then(setGroups).catch(() => setGroups([]));
    }
  }, [scheduleId]);
  const algorithm = algorithms.find((item) => item.algorithm_id === form?.profile_id);
  const onAssets = schedule ? schedule.subject_kind === "asset" : algorithm?.subject_kind === "asset";
  const body = useMemo(() => (form ? payloadOf(form, onAssets) : null), [form, onAssets]);
  const problem = form ? whenProblem(form.when) : "";
  useEffect(() => {
    if (!body || !me.can_edit || problem || (onAssets && !(form?.assets.length))) { setPreview(null); return; }
    const timer = window.setTimeout(() => {
      api.previewSchedule(body, scheduleId ?? undefined).then(setPreview).catch(() => setPreview(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [JSON.stringify(body), problem]);
  if (error && !form) return <ErrorBox text={error} />;
  if (!form) return <Loading />;
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm({ ...form, [key]: value });
  const step = stepMinutes(form.when);
  const frequent = step !== null && step < FREQUENT_MINUTES;
  const round = schedule?.kind === "round";
  const outputRows = preview?.recorded_outputs ?? schedule?.recorded_outputs ?? null;
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form || !body) return;
    setError(""); setNotice("");
    if (problem) { setError(t(problem)); return; }
    if (frequent && !frequentOk) { setError(t("Confirm that it should run more often than every {n} minutes.", { n: FREQUENT_MINUTES })); return; }
    try {
      if (!scheduleId) {
        const created = await api.createSchedule(body);
        await putInFolder("schedule", created.schedule_id, folder);
        navigate(`/schedules/${encodeURIComponent(created.schedule_id)}`);
        return;
      }
      const patch: Record<string, unknown> = { name: body.name, enabled: form.enabled, priority: body.priority, spread_minutes: body.spread_minutes, owner: body.owner, lookback_minutes: body.lookback_minutes };
      if (!round) patch.retry = body.retry;
      if (editable.timing) {
        for (const key of ["cadence", "interval_minutes", "time_local", "weekday", "scheduled_for", "recurrence", "timezone"]) patch[key] = body[key];
      }
      if (editable.subjects) patch.selector = body.selector;
      if (editable.algorithm && body.profile_id) patch.profile_id = body.profile_id;
      if (onAssets) { patch.outputs = body.outputs; patch.node_parameters = body.node_parameters; }
      await api.updateSchedule(scheduleId, patch);
      setNotice(t("Saved."));
      load();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  const run = (action: () => Promise<unknown>, done: string) => () => {
    setError(""); setNotice("");
    action().then(() => { setNotice(done); load(); }).catch((err: Error) => setError(err.message));
  };
  // A saved schedule keeps the kind of subject it runs on; a new one follows the algorithm chosen.
  const choosable = schedule ? algorithms.filter((item) => item.subject_kind === (onAssets ? "asset" : "loop")) : algorithms;
  const loopChoices = choosable.filter((item) => item.subject_kind === "loop");
  const assetChoices = choosable.filter((item) => item.subject_kind === "asset");
  return <form className="schedule-page" onSubmit={(event) => void save(event)}>
    <Heading eyebrow={t("Monitor")} title={scheduleId ? schedule?.name ?? "" : t("New monitor")}
      detail={round ? t("In turn: one run works through every target, one after another.") : t("Which algorithm runs, on which assets, when, what it does if it fails and who answers for it.")}
      actions={<>
        {scheduleId && me.can_edit && <button type="button" className="button button-secondary" onClick={run(() => api.runSchedule(scheduleId), t("Queued: it runs ahead of the monitors."))}><Play size={16} />{t("Run now")}</button>}
        {/* Link publishes, the Alarms app decides (owner decision D6): its rule opens filled in for this schedule. */}
        {scheduleId && schedule && scheduleId !== "round-signal_quality" && <a className="button button-secondary" href={alarmRuleHref(scheduleId, schedule.name)}><BellPlus size={16} />{t("Create alarm rule")}</a>}
      </>} />
    {error && <ErrorBox text={error} />}
    {notice && <div className="notice notice-ok" role="status">{notice}</div>}
    {scheduleId && <FolderPlaceLine kind="schedule" itemId={scheduleId} canEdit={me.can_edit} />}
    {schedule?.stats && scheduleId && <StatsStrip stats={schedule.stats} scheduleId={scheduleId} />}
    <div className="schedule-sections">
      <Part number={1} title={t("What it runs")} detail={onAssets ? t("Its name, the algorithm and the assets it runs on.") : t("Its name, the algorithm and the loops it runs on.")} disabled={readOnly}>
        <Field label={t("Name")}><input value={form.name} required maxLength={180} onChange={(event) => set("name", event.target.value)} /></Field>
        {!scheduleId && <FolderField kind="schedule" value={folder} onChange={setFolder} />}
        <Field label={t("Algorithm")} hint={!onAssets && editable.algorithm ? t("Empty: each loop runs the algorithm of its loop type.") : undefined}>
          {editable.algorithm
            ? <select value={form.profile_id} onChange={(event) => set("profile_id", event.target.value)}>
              {!onAssets && <option value="">{t("Each loop's own")}</option>}
              {loopChoices.length > 0 && <optgroup label={t("On loops")}>{loopChoices.map((item) => <option key={item.algorithm_id} value={item.algorithm_id}>{item.name}</option>)}</optgroup>}
              {assetChoices.length > 0 && <optgroup label={t("On assets")}>{assetChoices.map((item) => <option key={item.algorithm_id} value={item.algorithm_id}>{item.name}</option>)}</optgroup>}
            </select>
            : <input value={schedule?.algorithm?.name ?? ""} readOnly />}
        </Field>
        {algorithm && <p className="muted small schedule-note"><Link to={`/algorithms/${encodeURIComponent(algorithm.algorithm_id)}`}>{algorithm.name}</Link>{` · ${t("version {number}", { number: algorithm.version })}`}{algorithm.description ? ` · ${algorithm.description}` : ""}</p>}
        <div className="schedule-subsection">
          <h3>{onAssets ? t("On which assets") : t("On which loops")}</h3>
          {!editable.subjects ? <p className="muted">{schedule?.subject_label}</p>
            : onAssets ? <AssetList value={form.assets} choices={choices} onChange={(ids) => set("assets", ids)} disabled={readOnly} />
            : <>
              <Field label={t("Loops")}>
                <select value={form.mode} onChange={(event) => set("mode", event.target.value as Form["mode"])}>
                  <option value="all">{t("Every enabled loop")}</option>
                  <option value="filter">{t("Loops whose id or name contains")}</option>
                  <option value="list">{t("These loops")}</option>
                </select>
              </Field>
              {form.mode === "filter" && <Field label={t("Contains")}><input value={form.q} placeholder="FIC-" onChange={(event) => set("q", event.target.value)} /></Field>}
              {form.mode === "list" && <Field label={t("Loop ids")} hint={t("One per line, or separated by commas.")}><textarea rows={4} value={form.ids} onChange={(event) => set("ids", event.target.value)} /></Field>}
            </>}
        </div>
        {!onAssets && <Field label={t("Data window (minutes)")} hint={t("How far back each run reads, ending at its time. Empty: the analysis window set in Analytics' settings.")}><input type="number" min={5} value={form.lookback_minutes || ""} placeholder={t("Analytics' default")} onChange={(event) => set("lookback_minutes", Number(event.target.value) || 0)} /></Field>}
        {onAssets && <p className="muted small schedule-note">{t("The algorithm sets the window each run reads and its step.")}</p>}
      </Part>
      <Part number={2} title={t("When")} detail={t("How often it runs, in which time zone. The preview under the fields says it in words and lists the next occurrences.")} disabled={readOnly || !editable.timing}>
        <WhenFields when={form.when} onChange={(when) => set("when", when)} />
        {frequent && !readOnly && <label className="schedule-frequent"><input type="checkbox" checked={frequentOk} onChange={(event) => setFrequentOk(event.target.checked)} />{t("Run it more often than every {n} minutes: each run reads the plant and fills the queue.", { n: FREQUENT_MINUTES })}</label>}
        <Field label={t("Time zone")} hint={t("Local time follows the installation's zone (Settings). Times keep the zone's clock across daylight saving changes.")}><TimeZoneSelect value={form.timezone} onChange={(zone) => set("timezone", zone)} ariaLabel={t("Time zone")} /></Field>
        <SchedulePreviewBox preview={preview} problem={problem} timezone={form.timezone} waiting={onAssets && !form.assets.length} />
      </Part>
      {onAssets && algorithm && <Part number={3} title={t("Parameters")} detail={t("Each value comes from the block's default, then the algorithm, then this monitor: set one here to change it for this monitor only.")} disabled={readOnly}>
        <MonitorParameters algorithm={algorithm} value={form.node_parameters} onChange={(value) => set("node_parameters", value)} disabled={readOnly} />
      </Part>}
      {onAssets && <Part number={algorithm ? 4 : 3} title={t("Recorded outputs")} detail={t("What each run writes to the Historian, and for how long, with what it costs.")} disabled={readOnly}>
        {outputRows === null ? <p className="muted small">{t("Choose the algorithm and the assets to see what it records.")}</p>
          : <RecordedOutputs rows={outputRows} assets={form.assets.length} choices={form.outputs} onChange={(outputs) => set("outputs", outputs)} disabled={readOnly} />}
      </Part>}
      <Part number={onAssets ? (algorithm ? 5 : 4) : 3} title={t("If it fails")} detail={t("What it does when it cannot read the plant or finds no data.")} disabled={readOnly || round}>
        {round ? <p className="muted small schedule-note">{t("A run in turn tries a target it cannot read again on its next pass.")}</p>
          : <RetryFields retry={form.retry} onChange={(retry) => set("retry", retry)} />}
      </Part>
      <Part number={onAssets ? (algorithm ? 6 : 5) : 4} title={t("Owner and priority")} detail={t("Who answers for it, how it goes in the queue among the others, and whether it runs.")} disabled={readOnly}>
        <Field label={t("Owner")} hint={t("Who answers for this monitor. Alarms sends what it raises from this monitor to them.")}>
          {readOnly ? <input value={recipientLabel(form.owner, people, groups)} readOnly />
            : <RecipientPicker single value={form.owner ? [form.owner] : []} onChange={(value) => set("owner", value[value.length - 1] ?? "")} people={people} groups={groups} label={t("Owner")} placeholder={t("Search a person or a group")} />}
        </Field>
        <div className="schedule-row">
          <Field label={t("Priority")} hint={t("Among the monitors. A person's \"Run now\" always goes first, replays of the past last.")}><select value={form.priority} onChange={(event) => set("priority", Number(event.target.value))}>{PRIORITIES.map((item) => <option key={item.value} value={item.value}>{t(item.label)}</option>)}</select></Field>
          <Field label={t("Spread over (minutes)")} hint={t("0 queues every run at the occurrence; more spreads them over that window, so a large monitor does not arrive all at once.")}><input type="number" min={0} max={1440} value={form.spread_minutes} onChange={(event) => set("spread_minutes", Number(event.target.value))} /></Field>
        </div>
        <Field label={t("Active")}><span className="schedule-toggle"><input type="checkbox" checked={form.enabled} onChange={(event) => set("enabled", event.target.checked)} />{form.enabled ? t("Runs on time") : t("Paused")}</span></Field>
      </Part>
      {scheduleId && me.is_admin && schedule && ["round", "loop"].includes(schedule.work ?? "") && schedule.schedule_id !== "round-signal_quality" && <section className="panel schedule-replay" aria-label={t("Replay the past")}>
        <div><h2><History size={16} /> {t("Replay the past")}</h2>
          <p className="muted small">{t("Run this monitor's past occurrences over the archive, to fill its history. It runs after everything else in the queue.")}</p></div>
        <div className="schedule-replay-run"><input type="number" min={1} max={744} value={replayHours} aria-label={t("Hours")} onChange={(event) => setReplayHours(Number(event.target.value))} /><span>{t("hours")}</span>
          <button type="button" className="button button-secondary" onClick={run(() => api.replaySchedule(scheduleId, replayHours), t("The replay is in the queue."))}>{t("Replay")}</button></div>
      </section>}
      {!readOnly && <div className="panel blkf-bar schedule-bar">
        <div>{scheduleId && editable.delete && <button type="button" className="button button-secondary" onClick={run(async () => { if (await confirmAction(t("Delete this monitor? Its past runs stay."), { confirm: t("Delete"), danger: true })) { await api.deleteSchedule(scheduleId); navigate("/schedules"); } }, "")}><Trash2 size={16} />{t("Delete")}</button>}</div>
        <div className="schedule-bar-actions">
          <Link to="/schedules" className="button button-secondary">{t("Cancel")}</Link>
          <button className="button button-primary">{scheduleId ? t("Save") : t("Create monitor")}</button>
        </div>
      </div>}
    </div>
  </form>;
}
