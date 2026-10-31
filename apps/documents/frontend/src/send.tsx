/** Sending files: one or many, each read in the background once sent. */
import { useState } from "react";
import { Dialog } from "@plantcraft/ui";
import { api } from "./api";
import { t } from "./i18n";
import type { Folder, SendFields } from "./types";
import { ErrorBox, message } from "./ui";

const NUMBER = /^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d[A-Z0-9]*)\s+(.+)$/;

/** "DOC-U200-OM-001 Hydrotreating unit manual.pdf": its number and title, when it starts with one. */
export function splitName(filename: string): { number: string; title: string } {
  const stem = filename.replace(/\.[A-Za-z0-9]{1,5}$/, "").trim();
  const found = NUMBER.exec(stem);
  return found ? { number: found[1], title: found[2].trim() } : { number: "", title: stem };
}

export const ACCEPT = ".pdf,.docx,.docm,.xlsx,.xlsm,.pptx,.txt,.md,.markdown,.csv,.html,.htm,.svg,.xml,.png,.jpg,.jpeg,.tif,.tiff";

/** The files the library reads (`extract.FORMATS` on the server), as a person reads the list. */
export const FILE_TYPES = "PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), text (.txt), Markdown (.md), CSV, HTML and drawings (SVG, PNG, JPEG, TIFF)";

/** The line under every place that takes files: what can be sent and how large. */
export function fileTypesLine(maxMb?: number | null): string {
  return maxMb ? t("Files read: {types}, up to {mb} MB each. Older .doc, .xls and .ppt files: save them in the new format first.", { types: FILE_TYPES, mb: maxMb })
    : t("Files read: {types}. Older .doc, .xls and .ppt files: save them in the new format first.", { types: FILE_TYPES });
}

type Sent = { name: string; ok: boolean; detail: string };

export function SendDialog({ files, folders, kinds, folder, onClose, onSent }: {
  files: File[]; folders: Folder[]; kinds: string[]; folder: string; onClose: () => void; onSent: () => void;
}) {
  const single = files.length === 1;
  const named = single ? splitName(files[0].name) : { number: "", title: "" };
  const [fields, setFields] = useState<SendFields>({ folder, number: named.number, title: named.title, description: "", kind: "Other", unit: "", language: "", revision: "", issued: "" });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Sent[]>([]);
  const [error, setError] = useState("");
  const set = (key: keyof SendFields) => (event: { target: { value: string } }) => setFields({ ...fields, [key]: event.target.value });
  const editable = folders.filter((item) => item.can_edit);

  const send = async () => {
    setBusy(true);
    setError("");
    const done: Sent[] = [];
    for (const file of files) {
      // Many files: each one's number and title come from its own name.
      const own = single ? { number: fields.number, title: fields.title } : splitName(file.name);
      try {
        await api.send(file, { ...fields, ...own });
        done.push({ name: file.name, ok: true, detail: t("Sent; waiting to be read.") });
      } catch (err) {
        done.push({ name: file.name, ok: false, detail: message(err) });
      }
      setSent([...done]);
    }
    setBusy(false);
    if (done.every((item) => item.ok)) { onSent(); onClose(); } else { onSent(); setError(t("Some files were not sent.")); }
  };

  return <Dialog title={single ? t("Send a document") : t("Send {n} documents", { n: files.length })} onClose={onClose}
    onSubmit={(event) => { event.preventDefault(); void send(); }}
    footer={<>
      <button className="button button-secondary" type="button" onClick={onClose}>{t("Cancel")}</button>
      <button className="button button-primary" type="submit" disabled={busy}>{busy ? t("Sending…") : t("Send")}</button>
    </>}>
    <div className="form-grid">
      <label>{t("Folder")}<select value={fields.folder} onChange={set("folder")}>
        <option value="">{t("General")}</option>
        {editable.map((item) => <option key={item.folder_id} value={item.folder_id}>{item.name}</option>)}
      </select></label>
      <label>{t("Kind")}<select value={fields.kind} onChange={set("kind")}>
        {kinds.map((kind) => <option key={kind} value={kind}>{t(kind)}</option>)}
      </select></label>
      {single && <>
        <label>{t("Number")}<input value={fields.number} onChange={set("number")} placeholder="DOC-U200-OM-001" maxLength={60} /></label>
        <label className="form-wide">{t("Title")}<input value={fields.title} onChange={set("title")} maxLength={200} /></label>
        <label className="form-wide">{t("Description")}<textarea rows={2} value={fields.description} onChange={set("description")} maxLength={1000}
          placeholder={t("What it covers, for whom, what it replaces")} /></label>
      </>}
      <label>{t("Unit")}<input value={fields.unit} onChange={set("unit")} placeholder="U-200" maxLength={60} /></label>
      <label>{t("Revision")}<input value={fields.revision} onChange={set("revision")} placeholder="C" maxLength={20} /></label>
      <label>{t("Issued")}<input type="date" value={fields.issued} onChange={set("issued")} /></label>
      <label>{t("Language")}<select value={fields.language} onChange={set("language")}>
        <option value="">{t("Not said")}</option><option value="en">English</option><option value="pt">Português</option>
      </select></label>
    </div>
    <p className="muted">{single
      ? t("A document with the same number gets this file as its new revision.")
      : t("Each file's number and title come from its name (\"DOC-U200-OM-001 Hydrotreating manual.pdf\"); a number already in the library gets a new revision.")}</p>
    <ul className="send-list">
      {files.map((file) => {
        const result = sent.find((item) => item.name === file.name);
        return <li key={file.name}><span>{file.name}</span> <small className={result && !result.ok ? "send-failed" : "muted"}>
          {result ? result.detail : `${Math.max(1, Math.round(file.size / 1024))} KB`}</small></li>;
      })}
    </ul>
    {error && <ErrorBox text={error} />}
  </Dialog>;
}
