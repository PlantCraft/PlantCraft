/** A model's or a block's versions and the dialog that names a new one; apart from ModelPage so the
 * blocks pages do not load the model editor (React Flow). */
import type { VersionItem } from "@plantcraft/ui";
import { Save } from "lucide-react";
import { useState } from "react";
import { formatDate, t } from "./i18n";
import type { Revision } from "./types";
import { Dialog } from "./ui";

/** A file's versions, newest first: the file as it is now, then each content a save replaced
 * (a revision keeps the old text, with who replaced it and when; round 9: Versions and About in
 * a tab of their own, as Link's blocks and algorithms). */
export function modelVersions(revisions: Revision[], now: { by?: string | null; at?: string | null; name?: string; note?: string }): VersionItem[] {
  const count = revisions.length + 1;
  return [
    { number: count, name: now.name || null, description: now.note || null, author: now.by ?? null, at: now.at ?? null, note: now.at ? null : t("As Models ships it"), current: true },
    ...revisions.map((item, index) => ({ number: count - 1 - index, name: item.version_name || null, description: item.version_note || null,
      note: t("Until {when}, replaced by {who}", { when: formatDate(item.saved_at), who: item.saved_by }) })),
  ];
}

/** The name of a new version and what changed in it, as Link's algorithms ask (round 9 M4). */
export function VersionDialog({ next, title: named, busy, error, onClose, onSave }: { next: number; title?: string; busy: boolean; error: string; onClose: () => void; onSave: (name: string, note: string) => void }) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const title = named ?? t("Save as version {n}", { n: next });
  // What changed is asked every time; the name is optional.
  const submit = () => { if (note.trim()) onSave(name.trim(), note.trim()); };
  return <Dialog title={title} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !note.trim()} onClick={submit}><Save size={16} />{busy ? t("Saving…") : title}</button>
  </>}>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label className="pc-span-all">{t("What changed")}<textarea id="mc-version-note" rows={3} value={note} maxLength={2000} autoFocus required onChange={(event) => setNote(event.target.value)} placeholder={t("e.g. A faster valve, and the tank 2 m² larger")} /></label>
      <label>{t("Version name")} <small>{t("optional")}</small><input id="mc-version-name" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("Faster valve")} /></label>
    </form>
  </Dialog>;
}
