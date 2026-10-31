import { type TimePeriod } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api, type ValueEdit } from "./api";
import { formatMs } from "./format";
import { t } from "./i18n";
import { localToIso, noteWindow } from "./PointNotes";
import type { Me, Point } from "./types";
import { ErrorBox, FormSection } from "./ui";

const ACTION_LABELS: Record<string, string> = { inserted: "Inserted", edited: "Edited", deleted: "Deleted" };

/** People's edits of archived values (H7): insert, change or delete one value with a reason;
 * the value replaced is kept in the history below, and each edit is in the audit log. */
export function PointEdits({ point, signal, period, me }: { point: Point; signal: string; period: TimePeriod; me: Me }) {
  const [edits, setEdits] = useState<ValueEdit[]>([]);
  const [draft, setDraft] = useState({ at: "", value: "", remove: false, reason: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const { start, end } = noteWindow(period);
  const load = () => api.valueEdits(signal, start, end).then((found) => setEdits(found.edits)).catch((err: Error) => setError(err.message));
  useEffect(() => { void load(); }, [signal, period.window, period.from, period.to]);

  async function save() {
    setError(""); setMessage("");
    const at = localToIso(draft.at);
    if (!at) { setError(t("Give the time of the value.")); return; }
    const value = point.kind === "number" ? Number(draft.value) : draft.value;
    try {
      const done = await api.editValues({ signal, reason: draft.reason, changes: [draft.remove ? { t: at, delete: true } : { t: at, value }] });
      setMessage(t("{action} at {t}. The value it replaced is kept in the history.", { action: t(ACTION_LABELS[done.changes[0].action] ?? done.changes[0].action), t: formatMs(Date.parse(done.changes[0].t)) }));
      setDraft({ at: "", value: "", remove: false, reason: "" });
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  if (!me.can_edit && edits.length === 0) return null;
  return <div className="panel form-panel">
    <FormSection title={t("Edited values")} detail={t("Values inserted, changed or deleted by hand in the period shown. The original value, who and why are kept; each edit is in the audit log.")}>
      {error && <ErrorBox text={error} />}
      {message && <div className="notice notice-ok">{message}</div>}
      {edits.length === 0 ? <p className="muted">{t("No edited values in this period.")}</p> : <ul className="note-list">
        {edits.map((edit, index) => <li key={`${edit.t}-${index}`}>
          <span className="pc-mono">{formatMs(Date.parse(edit.t))}</span>{" "}
          <b>{t(ACTION_LABELS[edit.action] ?? edit.action)}</b>{" "}
          {edit.old !== null && <span>{t("was {old}", { old: String(edit.old) })} </span>}
          {edit.new !== null && <span>{t("now {new}", { new: String(edit.new) })} </span>}
          <small className="muted">{t("by {by}, {at}: {reason}", { by: edit.by, at: formatMs(Date.parse(edit.at)), reason: edit.reason })}</small>
        </li>)}
      </ul>}
      {me.can_edit && <div className="form-grid">
        <label>{t("Time of the value")}<input type="datetime-local" step="1" value={draft.at} onChange={(event) => setDraft({ ...draft, at: event.target.value })} /></label>
        {!draft.remove && <label>{t("New value")}<input type={point.kind === "number" ? "number" : "text"} step="any" value={draft.value} onChange={(event) => setDraft({ ...draft, value: event.target.value })} /></label>}
        <label className="check"><input type="checkbox" checked={draft.remove} onChange={(event) => setDraft({ ...draft, remove: event.target.checked })} />{t("Delete the value at this time")}</label>
        <label className="field-span">{t("Why")}<input type="text" maxLength={500} value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} /></label>
        <div><button type="button" className="button button-primary" disabled={!draft.at || !draft.reason.trim() || (!draft.remove && draft.value === "")} onClick={() => void save()}>{t("Save the edit")}</button></div>
      </div>}
    </FormSection>
  </div>;
}
