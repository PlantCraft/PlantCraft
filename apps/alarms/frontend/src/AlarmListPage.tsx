import { DataTable, type DataColumn } from "@plantcraft/ui";
import { Check, Download, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { href, navigate } from "./nav";
import type { AlarmListImport, AlarmListItem, AlarmListValues, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill, PriorityPill, message } from "./ui";

const CHANGE_WORDS: Record<AlarmListItem["change"], string> = { new: "New", changed: "Changed", removed: "Removed", same: "Same" };
const CHANGE_STATUS: Record<AlarmListItem["change"], string> = { new: "ok", changed: "warning", removed: "alarm", same: "unknown" };
const KIND_WORDS: Record<string, string> = { high_high: "HH", high: "HI", low: "LO", low_low: "LL" };
const FIELD_WORDS: Record<string, string> = {
  name: "Name", signal_id: "Signal", kind: "Type", limit: "Limit", unit: "Unit", deadband: "Deadband",
  on_delay_seconds: "On delay", priority: "Priority", enabled: "On", cause: "Cause", consequence: "Consequence",
  action: "Action", editor: "Rewritten in Blocks or Python",
};

function shown(field: string, values: AlarmListValues | null): string {
  if (!values) return "";
  const value = values[field as keyof AlarmListValues];
  if (field === "kind") return KIND_WORDS[String(value)] ?? String(value);
  if (field === "enabled") return value ? t("On") : t("Off");
  if (field === "on_delay_seconds") return `${value} s`;
  return value === "" || value === null || value === undefined ? "—" : String(value);
}

/** Before → after, for each field the list changes. */
function Difference({ item }: { item: AlarmListItem }) {
  if (item.change === "new") return <span className="small muted">{t("{kind} at {limit} {unit}", { kind: shown("kind", item.after), limit: shown("limit", item.after), unit: item.after?.unit ?? "" })}</span>;
  if (item.change === "removed") return <span className="small">{t("Not in the list any more: the rule is turned off (not deleted).")}</span>;
  if (item.change === "same") return <span className="small muted">{t("No difference")}</span>;
  return <ul className="al-diff small">{item.fields.map((field) => <li key={field}>
    <strong>{t(FIELD_WORDS[field] ?? field)}</strong>{field !== "editor" && <>: {shown(field, item.before)} → {shown(field, item.after)}</>}
  </li>)}</ul>;
}

async function base64Of(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text = "";
  for (let start = 0; start < bytes.length; start += 0x8000) text += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  return btoa(text);
}

/** Rules › Import alarm list: a DCS export read as a draft, reviewed alarm by alarm, then applied. */
export function AlarmListPage({ me, importId }: { me: Me; importId?: number }) {
  const [draft, setDraft] = useState<AlarmListImport | null>(null);
  const [recent, setRecent] = useState<AlarmListImport[] | null>(null);
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setError("");
    if (importId) api.alarmList(importId).then((found) => { setDraft(found); setSkip(new Set()); }).catch((err) => setError(message(err)));
    else { setDraft(null); api.alarmLists().then(setRecent).catch(() => setRecent([])); }
  }, [importId]);
  const items = useMemo(() => (draft?.items ?? []).filter((item) => item.change !== "same"), [draft]);
  if (!me.can_edit) return <ErrorBox text={t("Importing an alarm list needs the right to edit rules.")} />;

  async function choose(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const made = await api.readAlarmList(file.name, await base64Of(file));
      navigate(`/rules/import/${made.import_id}`);
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  async function finish(kind: "apply" | "discard") {
    if (!draft) return;
    setBusy(true); setError("");
    try {
      setDraft(kind === "apply" ? await api.applyAlarmList(draft.import_id, [...skip]) : await api.discardAlarmList(draft.import_id));
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  const toggle = (key: string) => setSkip((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const open = draft?.state === "draft";
  const columns: DataColumn<AlarmListItem>[] = [
    { key: "keep", label: t("Apply"), render: (item) => <input type="checkbox" aria-label={t("Apply {alarm}", { alarm: item.key })} checked={!skip.has(item.key)} disabled={!open} onChange={() => toggle(item.key)} /> },
    { key: "change", label: t("Change"), sort: (item) => item.change, filter: { value: (item) => t(CHANGE_WORDS[item.change]) }, render: (item) => <Pill status={CHANGE_STATUS[item.change]} label={t(CHANGE_WORDS[item.change])} /> },
    { key: "alarm", label: t("Alarm"), className: "al-name", sort: (item) => item.key, render: (item) => <>
      {item.rule_id ? <Link to={`/rules/${item.rule_id}`} className="strong">{item.key}</Link> : <span className="strong">{item.key}</span>}
      <div className="small muted">{(item.after ?? item.before)?.name}{item.line ? ` · ${t("line {n}", { n: item.line })}` : ""}</div>
    </> },
    { key: "priority", label: t("Priority"), phone: "hide", render: (item) => <PriorityPill priority={(item.after ?? item.before)?.priority ?? "medium"} /> },
    { key: "what", label: t("What changes"), render: (item) => <Difference item={item} /> },
  ];

  return <>
    <Heading title={t("Import alarm list")} actions={<a className="button button-secondary" href={href("/api/alarm-list/template.csv")} download><Download size={16} />{t("Template")}</a>} />
    <p className="muted">{t("Read the alarm list exported from the DCS (CSV, or Excel saved as .xlsx): one row per alarm, with its tag, type (HH, HI, LO, LL), limit, priority, deadband, on-delay, cause, consequence and action. Nothing changes until you review the differences and apply them.")}</p>
    {error && <ErrorBox text={error} />}
    {!importId && <>
      <label className="button button-primary al-file">
        <Upload size={16} />{busy ? t("Reading…") : t("Choose a file")}
        <input type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm" hidden disabled={busy} onChange={(event) => void choose(event.target.files?.[0])} />
      </label>
      {recent && recent.length > 0 && <section className="panel al-pad">
        <h2>{t("Recent imports")}</h2>
        <ul className="al-list">{recent.map((item) => <li key={item.import_id}>
          <Link to={`/rules/import/${item.import_id}`}>{item.filename}</Link> · {formatDate(item.created_at)} · {t(item.state === "draft" ? "Waiting for review" : item.state === "applied" ? "Applied" : "Thrown away")}
        </li>)}</ul>
      </section>}
    </>}
    {importId && !draft && !error && <Loading />}
    {draft && <>
      <section className="panel al-pad">
        <h2>{draft.filename}</h2>
        <p>{t("{new} new, {changed} changed, {removed} removed, {same} the same. Read {when} by {who}.", { ...draft.counts, when: formatDate(draft.created_at), who: draft.created_by })}</p>
        {draft.state === "applied" && draft.result && <p><Pill status="ok" label={t("Applied")} /> {t("{created} rules created, {changed} changed, {off} turned off, {left} left out.", { created: draft.result.created, changed: draft.result.changed, off: draft.result.turned_off, left: draft.result.left_out })}</p>}
        {draft.result?.not_applied.length ? <ErrorBox text={t("Not applied: {items}. Read the file again to see the difference now.", { items: draft.result.not_applied.map((item) => `${item.key} (${item.reason})`).join("; ") })} /> : null}
        {draft.state === "discarded" && <p><Pill status="unknown" label={t("Thrown away")} /></p>}
        {draft.problems.length > 0 && <details open={draft.rows === 0}>
          <summary>{t("Rows not read: {n}", { n: draft.problems.length })}</summary>
          <ul className="small">{draft.problems.map((problem, index) => <li key={index}>{problem.line ? t("Line {n}: ", { n: problem.line }) : ""}{problem.message}</li>)}</ul>
        </details>}
      </section>
      {items.length > 0 ? <DataTable rows={items} columns={columns} rowKey={(item) => item.key} label={t("Differences")} searchText={(item) => `${item.key} ${item.after?.name ?? item.before?.name ?? ""}`} searchPlaceholder={t("Search tags or names")} />
        : <p className="muted al-pad">{t("Nothing to change: the rules already say what the list says.")}</p>}
      {open && <div className="al-actions">
        <button type="button" className="button button-primary" disabled={busy || items.length === skip.size} onClick={() => void finish("apply")}><Check size={16} />{t("Apply the changes ({n})", { n: items.length - skip.size })}</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void finish("discard")}><X size={16} />{t("Throw away")}</button>
      </div>}
    </>}
  </>;
}
