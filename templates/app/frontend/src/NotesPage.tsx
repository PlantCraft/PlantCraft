/** The app's pages: every note (with the form for a new one), one note, and one asset's notes. */
import { useCallback, useEffect, useState } from "react";
import { DataTable } from "@plantcraft/ui";
import { api } from "./api";
import { formatAgo, t } from "./i18n";
import { navigate } from "./nav";
import type { Me, Note } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

function NoteForm({ assetId = "", onSaved }: { assetId?: string; onSaved: (note: Note) => void }) {
  const [asset, setAsset] = useState(assetId);
  const [text, setText] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [followUpBy, setFollowUpBy] = useState("");
  const [error, setError] = useState("");
  const save = () => api.create({ asset_id: asset.trim(), text: text.trim(), follow_up: followUp || null, follow_up_by: followUpBy.trim() || null })
    .then((note) => { setText(""); setFollowUp(""); setFollowUpBy(""); setError(""); onSaved(note); })
    .catch((err) => setError(message(err)));
  return <form className="panel" onSubmit={(event) => { event.preventDefault(); void save(); }}>
    <h2>{t("New note")}</h2>
    <div className="form-grid">
      <label>{t("Asset")}<input value={asset} onChange={(event) => setAsset(event.target.value)} placeholder="FIC-1001" required /></label>
      <label className="form-wide">{t("Note")}<textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} maxLength={4000} required /></label>
      <label>{t("Follow up on")}<input type="date" value={followUp} onChange={(event) => setFollowUp(event.target.value)} /></label>
      <label>{t("Follow up by")}<input value={followUpBy} onChange={(event) => setFollowUpBy(event.target.value)} placeholder={t("Username")} maxLength={80} /></label>
    </div>
    {error && <ErrorBox text={error} />}
    <div className="form-actions"><button className="button button-primary" type="submit">{t("Save note")}</button></div>
  </form>;
}

function NoteList({ notes }: { notes: Note[] }) {
  if (!notes.length) return <div className="panel"><h2>{t("No notes yet")}</h2><p className="muted">{t("An editor writes the first one.")}</p></div>;
  // The suite's table: sort, filter by asset or author, search the text, pages.
  return <DataTable rows={notes} rowKey={(note) => note.note_id} label={t("Notes")}
    searchText={(note) => `${note.asset_id} ${note.text}`} initialSort={{ key: "when", descending: true }}
    columns={[
      { key: "asset", label: t("Asset"), sort: (note) => note.asset_id, filter: true,
        render: (note) => <Link to={`/assets/${encodeURIComponent(note.asset_id)}`}>{note.asset_id}</Link> },
      { key: "text", label: t("Note"), sort: (note) => note.text, render: (note) => <Link to={`/notes/${note.note_id}`}>{note.text}</Link> },
      { key: "by", label: t("By"), sort: (note) => note.updated_by, filter: true, render: (note) => note.updated_by },
      { key: "when", label: t("When"), sort: (note) => note.updated_at, render: (note) => formatAgo(note.updated_at) },
    ]} />;
}

/** `/` and `assets/<id>`: the notes, all or one asset's, and the form for a new one. */
export function NotesPage({ me, assetId }: { me: Me; assetId?: string }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.notes(assetId).then(setNotes).catch((err) => setError(message(err))), [assetId]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorBox text={error} />;
  if (!notes) return <Loading />;
  return <>
    <Heading eyebrow={assetId ? t("Asset") : t("Starter")} title={assetId ?? t("Notes")}
      detail={assetId ? t("The notes on this asset.") : t("Notes on the plant's assets, newest first.")} />
    {me.can_edit && <NoteForm assetId={assetId} onSaved={() => void load()} />}
    <NoteList notes={notes} />
  </>;
}

/** `notes/<id>`: one note, and for an editor, deleting it. */
export function NotePage({ me, noteId }: { me: Me; noteId: string }) {
  const [note, setNote] = useState<Note | null>(null);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");
  useEffect(() => { api.note(noteId).then(setNote).catch((err) => setError(message(err))); }, [noteId]);
  if (error) return <ErrorBox text={error} />;
  if (!note) return <Loading />;
  const remove = () => api.remove(noteId).then(() => navigate("/")).catch((err) => setError(message(err)));
  // A model chosen in PlantCraft's Setup > Language models; the page says so while there is none.
  const summarise = () => api.summary(noteId).then((answer) => setSummary(answer.summary)).catch((err) => setSummary(message(err)));
  return <>
    <Heading eyebrow={t("Note")} title={note.asset_name ?? note.asset_id}
      detail={t("Written by {who}, {when}.", { who: note.created_by, when: formatAgo(note.created_at) })} />
    <div className="panel">
      <p>{note.text}</p>
      {note.follow_up && <p className="muted">{t("Follow up on {day}", { day: note.follow_up })}{note.follow_up_by ? ` · ${note.follow_up_by}` : ""}</p>}
      {summary && <p role="status">{summary}</p>}
      <button className="button" type="button" onClick={() => void summarise()}>{t("Summarise")}</button>{" "}
      {me.can_edit && <button className="button" type="button" onClick={() => void remove()}>{t("Delete")}</button>}
    </div>
  </>;
}
