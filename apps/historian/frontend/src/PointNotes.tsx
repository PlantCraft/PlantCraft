import { periodRange, type TimePeriod } from "@plantcraft/ui";
import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Note } from "./api";
import { formatMs } from "./format";
import { t } from "./i18n";
import type { Me } from "./types";
import { ErrorBox, FormSection } from "./ui";

/** The window a period shows, as ISO times (a relative one ends now). */
export function noteWindow(period: TimePeriod, now = Date.now()): { start: string; end: string } {
  const range = periodRange(period);
  if (period.window === "fixed" && range.start && range.end) return { start: range.start, end: range.end };
  const seconds = Math.max(1, range.seconds || 3600);
  return { start: new Date(now - seconds * 1000).toISOString(), end: new Date(now).toISOString() };
}

/** A `datetime-local` value as an ISO time in UTC (empty stays empty). */
export function localToIso(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

/** Notes on the signal in the period shown (H8): what a person knows that the values do not say.
 * A note added is also told to PlantCraft's events, in the person's name. */
export function PointNotes({ signal, period, me }: { signal: string; period: TimePeriod; me: Me }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [draft, setDraft] = useState({ at: "", end: "", text: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const { start, end } = noteWindow(period);
  const load = () => api.notes(signal, start, end).then((found) => setNotes(found.notes)).catch((err: Error) => setError(err.message));
  useEffect(() => { void load(); }, [signal, period.window, period.from, period.to]);

  async function add() {
    setError(""); setMessage("");
    const at = localToIso(draft.at) || new Date().toISOString();
    try {
      const made = await api.addNote({ signal, at, end: localToIso(draft.end) || null, text: draft.text });
      setDraft({ at: "", end: "", text: "" });
      // Told to PlantCraft as an event in the person's name (the Historian never calls the suite).
      const told = await fetch("/api/v1/events", { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(made.event) }).then((answer) => answer.ok).catch(() => false);
      setMessage(told ? t("Note kept and told to Events.") : t("Note kept. Events could not be told now."));
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function remove(note: Note) {
    setError(""); setMessage("");
    try { await api.removeNote(note.id); await load(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  return <div className="panel form-panel">
    <FormSection title={t("Notes")} detail={t("What happened that the values do not say, at an instant or over an interval. Each note is also an event in PlantCraft.")}>
      {error && <ErrorBox text={error} />}
      {message && <div className="notice notice-ok">{message}</div>}
      {notes.length === 0 ? <p className="muted">{t("No notes in this period.")}</p> : <ul className="note-list">
        {notes.map((note) => <li key={note.id}>
          <span className="pc-mono">{formatMs(Date.parse(note.at))}{note.end ? ` – ${formatMs(Date.parse(note.end))}` : ""}</span>{" "}
          <b>{note.text}</b> <small className="muted">{t("by {author}", { author: note.author })}</small>
          {me.can_edit && (note.author === me.username || me.is_admin) && <> <button type="button" className="button button-secondary button-small" aria-label={t("Remove note")} onClick={() => void remove(note)}><Trash2 size={14} /></button></>}
        </li>)}
      </ul>}
      {me.can_edit && <div className="form-grid">
        <label>{t("At")}<input type="datetime-local" value={draft.at} onChange={(event) => setDraft({ ...draft, at: event.target.value })} /><small>{t("Empty: now")}</small></label>
        <label>{t("Until")}<input type="datetime-local" value={draft.end} onChange={(event) => setDraft({ ...draft, end: event.target.value })} /><small>{t("Empty: one instant")}</small></label>
        <label className="field-span">{t("Note")}<input type="text" maxLength={2000} value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })} /></label>
        <div><button type="button" className="button button-primary" disabled={!draft.text.trim()} onClick={() => void add()}>{t("Add note")}</button></div>
      </div>}
    </FormSection>
  </div>;
}
