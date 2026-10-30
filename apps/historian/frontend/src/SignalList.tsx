/**
 * The signal list as a CSV (every signal's tag, source, address and settings): exported on
 * Exports and imported on Imports, beside the history they move (the
 * Signals page keeps only the buttons that add signals).
 */
import { Dialog } from "@plantcraft/ui";
import { ListChecks } from "lucide-react";
import { useRef, useState } from "react";
import { api, type PointsImport } from "./api";
import { t } from "./i18n";
import { ErrorBox } from "./ui";

/** Downloads every signal's settings as one CSV, the file the import below reads back. */
export function ExportSignalList({ onError }: { onError: (text: string) => void }) {
  return <button type="button" className="button button-secondary" onClick={() => void api.exportPoints().catch((err: Error) => onError(err.message))}><ListChecks size={16} />{t("Export signal list")}</button>;
}

/** Chooses a signal list (CSV), shows what it would add and change, then applies it. */
export function ImportSignalList({ onError, onDone }: { onError: (text: string) => void; onDone: (text: string) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState<{ file: File; plan: PointsImport } | null>(null);
  async function preview(file: File | undefined) {
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;
    try { setImporting({ file, plan: await api.importPoints(file, false) }); } catch (err) { onError(err instanceof Error ? err.message : String(err)); }
  }
  return <>
    <button type="button" className="button button-secondary" onClick={() => fileInput.current?.click()}><ListChecks size={16} />{t("Import signal list")}</button>
    <input ref={fileInput} type="file" accept=".csv,text/csv" hidden onChange={(event) => void preview(event.target.files?.[0])} />
    {importing && <ImportDialog file={importing.file} plan={importing.plan} onClose={() => setImporting(null)} onDone={(done) => {
      setImporting(null);
      onDone(t("{added} signals added, {updated} updated.", { added: done.added?.length ?? 0, updated: done.updated?.length ?? 0 }));
    }} />}
  </>;
}

/** A point list in CSV: what it adds and changes, its lines with errors, then Apply. */
function ImportDialog({ file, plan, onClose, onDone }: { file: File; plan: PointsImport; onClose: () => void; onDone: (done: PointsImport) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const changes = plan.add.length + plan.update.length;
  async function apply() {
    setBusy(true); setError("");
    try { onDone(await api.importPoints(file, true)); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <Dialog title={t("Import signal list: {name}", { name: file.name })} onClose={onClose}>
      {error && <ErrorBox text={error} />}
      <div className="kpis compact">
        <span className="kpi"><b className="pc-num">{plan.add.length}</b><span>{t("to add")}</span></span>
        <span className="kpi"><b className="pc-num">{plan.update.length}</b><span>{t("to change")}</span></span>
        <span className="kpi"><b className="pc-num">{plan.unchanged.length}</b><span>{t("unchanged")}</span></span>
        <span className="kpi"><b className="pc-num">{plan.errors.length}</b><span>{t("lines with errors")}</span></span>
      </div>
      {plan.errors.length > 0 && <>
        <p>{t("Fix these lines in the file and choose it again; nothing is imported while one is wrong.")}</p>
        <table className="table compact"><thead><tr><th>{t("Line")}</th><th>{t("Signal")}</th><th>{t("Problem")}</th></tr></thead>
          <tbody>{plan.errors.slice(0, 50).map((item) => <tr key={`${item.line}-${item.message}`}><td className="pc-num">{item.line}</td><td className="pc-mono">{item.signal}</td><td>{item.message}</td></tr>)}</tbody></table>
      </>}
      {plan.errors.length === 0 && changes > 0 && <p className="muted">{t("Empty setting cells inherit from the source or the general settings, as on a signal's page.")}</p>}
      {plan.errors.length === 0 && changes === 0 && <p className="muted">{t("The file matches the signals as they are: nothing to change.")}</p>}
      <footer><button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button className="button button-primary" disabled={busy || plan.errors.length > 0 || changes === 0} onClick={() => void apply()}>{t("Import")}</button></footer>
  </Dialog>;
}
