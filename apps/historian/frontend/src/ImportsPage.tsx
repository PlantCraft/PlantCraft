/**
 * Imports: CSV and Excel files. A file is checked first
 * and nothing is written until the person confirms; the check fills in how the file is read
 * (separator, columns, time format…), which the person can change and check again. An import
 * keeps that, so the next file of the same kind is read the same way into the same points.
 * Deleting an import removes its points and every value it brought.
 */
import { confirmAction, DataTable, LOCAL_ZONE, Pill, resolveTimeZone, saveFile, TimeZoneSelect, Dialog } from "@plantcraft/ui";
import { Ban, Download, FilePlus2, FileSpreadsheet, FileUp, FolderSync, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ExampleShape } from "./api";
import { ago, formatCount, formatMs } from "./format";
import { t } from "./i18n";
import { navigate } from "./nav";
import { sourcePath } from "./SourcesPage";
import { READ_KEYS, type ImportCheck, type ImportItem, type ImportProblem, type ImportRepeat, type Me, type ReadOptions } from "./types";
import { ImportSignalList } from "./SignalList";
import { ErrorBox, Heading, Loading } from "./ui";

const STATUS: Record<ImportItem["status"], { pill: string; label: string }> = {
  writing: { pill: "waiting", label: "Writing values" },
  done: { pill: "ok", label: "Imported" },
  error: { pill: "bad", label: "Failed" },
  gone: { pill: "disabled", label: "Removed" },
};

/** How often a repeating import checks its folder (minutes). */
export const REPEAT_EVERY: [number, string][] = [[15, "Every 15 minutes"], [60, "Every hour"], [360, "Every 6 hours"], [1440, "Every day"]];
const REPEATS: Record<number, string> = { 15: "Repeats every 15 minutes from {pattern}", 60: "Repeats every hour from {pattern}", 360: "Repeats every 6 hours from {pattern}", 1440: "Repeats every day from {pattern}" };

export function repeatLine(repeat: ImportRepeat): string {
  const line = REPEATS[repeat.check_minutes];
  return line ? t(line, { pattern: repeat.pattern }) : t("Repeats every {count} minutes from {pattern}", { count: repeat.check_minutes, pattern: repeat.pattern });
}

const isRepeat = (repeat: ImportItem["repeat"]): repeat is ImportRepeat => !!repeat && "pattern" in repeat && !!repeat.pattern;

const period = (start: number | null, end: number | null) => (start === null || end === null ? "—" : `${formatMs(start)} – ${formatMs(end)}`);

export function ImportsPage({ me }: { me: Me }) {
  const [items, setItems] = useState<ImportItem[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // The dialog: a new import (true), the next file of one, or an example file to try.
  const [checking, setChecking] = useState<boolean | ImportItem | File>(false);
  const [removing, setRemoving] = useState<ImportItem | null>(null);
  const [repeating, setRepeating] = useState<ImportItem | null>(null);
  const cancel = (item: ImportItem) => void confirmAction(t("The file waiting is not written. A new import goes with its signals; for the next file of an import, only that file is dropped."), { title: t("Cancel {name}?", { name: item.name }), confirm: t("Cancel the file"), cancel: t("Keep it") })
    .then(async (yes) => { if (!yes) return; await api.cancelImport(item.id); setNotice(t("{name}: the waiting file was cancelled.", { name: item.name })); void load(); })
    .catch((err: Error) => setError(err.message));
  const load = () => api.imports().then(setItems).catch((err: Error) => setError(err.message));
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5_000);
    return () => window.clearInterval(timer);
  }, []);
  return <>
    <Heading
      eyebrow={t("Historian")}
      title={t("Imports")}
      detail={t("CSV and Excel files. Each file is checked before anything is written, and an import reads its next files the same way. Deleting an import removes its signals and data.")}
      actions={<>
        <Examples onError={setError} onTry={me.can_edit ? setChecking : undefined} />
        {me.can_edit && <ImportSignalList onError={setError} onDone={setNotice} />}
        {me.can_edit && <button className="button button-primary" onClick={() => setChecking(true)}><FileUp size={16} />{t("Import a file")}</button>}
      </>}
    />
    {notice && <div className="notice notice-ok">{notice}</div>}
    {error && <ErrorBox text={error} />}
    {!items ? (error ? null : <Loading />) : items.length === 0
      ? <div className="panel empty"><h2>{t("No imports")}</h2><p>{t("Import a CSV or Excel file: lab analyses, an export from another system, a spreadsheet. Start from an example to see the two layouts. For files another application keeps writing, add a CSV source instead.")}</p></div>
      : <DataTable
        rows={items}
        rowKey={(item) => item.id}
        label={t("Imports")}
        searchText={(item) => `${item.name} ${item.file_name} ${item.imported_by}`}
        searchPlaceholder={t("Filter imports")}
        onRowClick={(item) => navigate(sourcePath(item.id))}
        columns={[
          { key: "name", label: t("Import"), sort: (item) => item.name, render: (item) => <><b>{item.name}</b><small className="pc-mono">{item.id}{item.file_name !== item.name ? ` · ${item.file_name}` : ""}</small>{isRepeat(item.repeat) && <small className="import-repeat">{repeatLine(item.repeat)}</small>}</> },
          { key: "period", label: t("Period"), sort: (item) => item.start_ms ?? 0, render: (item) => period(item.start_ms, item.end_ms) },
          { key: "points", label: t("Signals"), numeric: true, sort: (item) => item.points },
          { key: "values", label: t("Values"), numeric: true, sort: (item) => item.values, render: (item) => <>{formatCount(item.values)}<small>{(item.runs?.length || 1) === 1 ? t("1 file") : t("{count} files", { count: item.runs?.length ?? 0 })}</small></> },
          { key: "by", label: t("Imported"), sort: (item) => item.created, render: (item) => <>{formatMs(Date.parse(item.created))}<small>{item.imported_by}</small></> },
          { key: "status", label: t("Status"), filter: { value: (item) => t(STATUS[item.status].label) }, render: (item) => <Status item={item} /> },
          { key: "actions", label: "", render: (item) => me.can_edit && <span className="row-actions">
            {item.queued && <button className="icon-button" aria-label={t("Cancel the waiting file")} title={t("Cancel the waiting file")} onClick={(event) => { event.stopPropagation(); cancel(item); }}><Ban size={16} /></button>}
            <button className="icon-button" aria-label={t("Repeat from a folder")} title={t("Repeat from a folder: read each new file there the same way")} onClick={(event) => { event.stopPropagation(); setRepeating(item); }}><FolderSync size={16} /></button>
            <button className="icon-button" aria-label={t("Import the next file")} title={t("Import the next file, read the same way")} disabled={item.status === "writing"} onClick={(event) => { event.stopPropagation(); setChecking(item); }}><FilePlus2 size={16} /></button>
            <button className="icon-button danger" aria-label={t("Delete import")} title={t("Delete import")} onClick={(event) => { event.stopPropagation(); setRemoving(item); }}><Trash2 size={16} /></button></span> },
        ]}
      />}
    {checking && <ImportDialog into={typeof checking === "object" && !(checking instanceof File) ? checking : undefined} example={checking instanceof File ? checking : undefined} onClose={() => setChecking(false)} onDone={(item) => { setChecking(false); setNotice(t("{name} imported: {count} signals. The values are being written.", { name: item.name, count: item.points })); void load(); }} />}
    {repeating && <RepeatDialog item={repeating} onClose={() => setRepeating(null)} onDone={(text) => { setRepeating(null); setNotice(text); void load(); }} />}
    {removing && <DeleteDialog item={removing} onClose={() => setRemoving(null)} onDone={() => { setNotice(t("{name} deleted with its signals and data.", { name: removing.name })); setRemoving(null); void load(); }} />}
  </>;
}

/** The two example files: opened in the import dialog, checked, for whoever can import
 * (a download alone looked like nothing happened); downloaded otherwise. */
function Examples({ onError, onTry }: { onError: (text: string) => void; onTry?: (file: File) => void }) {
  const get = (shape: ExampleShape) => (onTry ? api.exampleFile(shape).then(onTry) : api.importExample(shape)).catch((err: Error) => onError(err.message));
  const Icon = onTry ? FileSpreadsheet : Download;
  return <span className="button-group" aria-label={t("Examples")}>
    <button type="button" className="button button-secondary" title={t("Time, then one column per tag")} onClick={() => void get("wide")}><Icon size={15} />{t("Example: wide")}</button>
    <button type="button" className="button button-secondary" title={t("Time, tag, value and quality on each line")} onClick={() => void get("long")}><Icon size={15} />{t("Example: long")}</button>
  </span>;
}

/** Only the settings an import keeps (a check answers more: columns, sheets, format). */
export function readOptions(from: Partial<ReadOptions> | undefined): Partial<ReadOptions> {
  const out: Partial<ReadOptions> = {};
  for (const key of READ_KEYS) if (from && from[key] !== undefined) (out as Record<string, unknown>)[key] = from[key];
  return out;
}

const TIME_FORMATS = ["%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M", "epoch_s", "epoch_ms"];

/** Choose a file, read the check (it fills in how the file is read), change that if needed,
 * check again, then import: a new import, or the next file of ``into``. */
function ImportDialog({ into, example, onClose, onDone }: { into?: ImportItem; example?: File; onClose: () => void; onDone: (item: ImportItem) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [zone, setZone] = useState(into?.read?.timezone || into?.timezone || LOCAL_ZONE);
  const [name, setName] = useState("");
  const [options, setOptions] = useState<Partial<ReadOptions>>(readOptions(into?.read));
  const [check, setCheck] = useState<ImportCheck | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const choose = (chosen: File | null) => { setFile(chosen); setName(chosen?.name.replace(/\.(csv|txt|tsv|xlsx|xlsm)$/i, "") ?? ""); void run(chosen, zone, options); };
  // An example opens checked, as if it had been chosen.
  useEffect(() => { if (example) choose(example); }, [example]);
  async function run(chosen: File | null, timezone: string, read: Partial<ReadOptions>) {
    if (!chosen) return;
    setBusy(true); setError(""); setCheck(null);
    try {
      // "Local time" is the installation's zone now: a file's times are read once.
      const found = await api.checkImport(chosen, resolveTimeZone(timezone), read, into?.id);
      setCheck(found);
      // The form shows what was used: what the person set and what was detected.
      setOptions(readOptions(found.report.options));
      if (!found.ok) setOpen(true);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!check?.token) return;
    setBusy(true); setError("");
    try { onDone(await api.createImport(check.token, name, into?.id)); } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  }
  const report = check?.report;
  const used = report?.options;
  const columns = used?.columns ?? [];
  const set = (key: keyof ReadOptions, value: string | number) => setOptions({ ...options, [key]: value });
  const pick = (key: keyof ReadOptions, label: string, choices: [string, string][]) => <label>{t(label)}
    <select value={String(options[key] ?? "")} onChange={(event) => set(key, event.target.value)}>{choices.map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label>;
  const column = (key: keyof ReadOptions, label: string, none?: string) => pick(key, label, [...(none ? [["", none] as [string, string]] : []), ...columns.map((name) => [name, name] as [string, string])]);
  const title = into ? t("Next file for {name}", { name: into.name }) : t("Import a file");
  return <Dialog title={title} onClose={onClose} wide>
      {error && <ErrorBox text={error} />}
      {example && file === example && <p className="muted">{t("An example file, checked as any file is. Import it to see its signals, or download it to start yours from it.")} <button type="button" className="link-button" onClick={() => saveFile(example.name, example)}><Download size={14} />{t("Download the example")}</button></p>}
      {into && <p className="muted">{t("Read as its last file was. New tags become signals; values at a time already imported are replaced.")}</p>}
      <div className="form-grid">
        <label>{t("File")}<span className="file-row"><input readOnly value={file?.name ?? ""} placeholder={t("No file chosen")} />
          <button type="button" className="button button-secondary" disabled={busy} onClick={() => input.current?.click()}><FileUp size={15} />{t("Choose file")}</button></span>
          <input ref={input} type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm,text/csv" hidden onChange={(event) => choose(event.target.files?.[0] ?? null)} />
          <small>{t("CSV or Excel (.xlsx). Wide (time, then one column per tag) or long (time, tag, value, optional quality). Up to 200 MB.")}</small></label>
        <label>{t("Time zone of times without an offset")}<TimeZoneSelect value={zone} ariaLabel={t("Time zone of times without an offset")} onChange={(chosen) => { setZone(chosen); void run(file, chosen, options); }} />
          <small>{t("Times with an offset or Z are read as written. Everything is stored in UTC.")}</small></label>
        {check?.ok && !into && <label>{t("Name")}<input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} /></label>}
      </div>
      {busy && !check && <Loading text={t("Checking the file…")} />}
      {report && used && <details className="read-options" open={open} onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
        <summary>{t("How the file is read")}<small>{used.format === "excel" ? t("Excel, sheet {sheet}", { sheet: used.sheet ?? "" }) : t("separator {sep}, decimal {dec}", { sep: report.delimiter === "\t" ? t("tab") : `“${report.delimiter}”`, dec: `“${report.decimal}”` })} · {report.shape === "long" ? t("long") : t("wide")} {used.time_column ? <> · {t("time in {column}", { column: used.time_column })}</> : null}</small></summary>
        <div className="form-grid">
          {used.format === "excel"
            ? <label>{t("Sheet")}<select value={String(options.sheet ?? "")} onChange={(event) => set("sheet", event.target.value)}>{(used.sheets ?? []).map((sheet) => <option key={sheet}>{sheet}</option>)}</select></label>
            : <>{pick("delimiter", "Separator", [[",", "Comma ,"], [";", "Semicolon ;"], ["\t", "Tab"], ["|", "Bar |"]])}
              {pick("decimal", "Decimal mark", [[".", "Point 1.5"], [",", "Comma 1,5"]])}</>}
          <label>{t("Lines before the header")}<input type="number" min={0} max={1000} value={options.skip_rows ?? 0} onChange={(event) => set("skip_rows", Number(event.target.value) || 0)} /><small>{t("A title or notes above the column names.")}</small></label>
          {pick("shape", "Layout", [["wide", "Wide: one column per tag"], ["long", "Long: one value per line"]])}
          {column("time_column", "Time column")}
          <label>{t("Time format")}<input list="time-formats" value={options.time_format ?? ""} placeholder={t("Detected (ISO 8601, epoch)")} onChange={(event) => set("time_format", event.target.value)} />
            <datalist id="time-formats">{TIME_FORMATS.map((format) => <option key={format} value={format} />)}</datalist>
            <small>{t("Like %d/%m/%Y %H:%M, or epoch_s / epoch_ms. Empty: detected.")}</small></label>
          {pick("day_first", "Dates like 01/10/2026", [["auto", "Detected"], ["day", "Day first (01/10 = 1 October)"], ["month", "Month first (01/10 = January 10)"]])}
          {options.shape === "long" && <>{column("tag_column", "Tag column")}{column("value_column", "Value column")}{column("quality_column", "Quality column", "None")}</>}
          <label>{t("Tag prefix")}<input value={options.tag_prefix ?? ""} maxLength={100} placeholder="LAB." onChange={(event) => set("tag_prefix", event.target.value)} /><small>{t("Put before every tag of the file.")}</small></label>
        </div>
        <button type="button" className="button button-secondary" disabled={busy || !file} onClick={() => void run(file, zone, options)}><RotateCw size={15} />{t("Check again")}</button>
        <Preview report={report} />
      </details>}
      {report && <>
        <div className={`notice ${check.ok ? (report.warnings.length ? "notice-warn" : "notice-ok") : "notice-error"}`}>
          {check.ok ? (report.warnings.length ? t("The file can be imported. Review the notes below first.") : t("The file is ready to import.")) : t("The file cannot be imported. Fix the file, or how it is read above, and check again.")}
        </div>
        <dl className="settings-list">
          <dt>{t("Period")}</dt><dd>{period(report.start_ms, report.end_ms)}</dd>
          <dt>{t("Lines")}</dt><dd className="pc-num">{formatCount(report.rows)}</dd>
          <dt>{t("Values")}</dt><dd className="pc-num">{formatCount(report.values)}</dd>
          <dt>{t("Signals")}</dt><dd>{report.tags.length ? `${formatCount(report.tags.length)}: ${report.tags.slice(0, 8).map((tag) => tag.tag).join(", ")}${report.tags.length > 8 ? "…" : ""}` : "—"}</dd>
        </dl>
        <Problems title={t("Errors")} items={report.errors} />
        <Problems title={t("Notes")} items={report.warnings} />
      </>}
      <footer><button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button className="button button-primary" disabled={busy || !check?.ok} onClick={() => void confirm()}>{t("Import")}</button></footer>
  </Dialog>;
}

/** The file's first lines as read: the time each line gets, then its cells. */
function Preview({ report }: { report: ImportCheck["report"] }) {
  const { columns = [], rows = [], times = [] } = report.preview ?? {};
  if (!rows.length) return null;
  const shown = columns.slice(0, 8);
  return <div className="table-scroll"><table className="table compact preview-table">
    <caption>{t("First lines as read")}</caption>
    <thead><tr><th>{t("Time read (UTC)")}</th>{shown.map((name, index) => <th key={`${index}-${name}`}>{name}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}><td className={times[index] ? "pc-mono" : "pc-mono bad"}>{times[index] ? formatMs(Date.parse(times[index]!)) : t("not read")}</td>
      {shown.map((_, cell) => <td key={cell}>{row[cell]}</td>)}</tr>)}</tbody>
  </table></div>;
}

function Problems({ title, items }: { title: string; items: ImportProblem[] }) {
  if (!items.length) return null;
  return <table className="table compact"><thead><tr><th>{title}</th><th>{t("Lines")}</th></tr></thead>
    <tbody>{items.map((item) => <tr key={item.message}><td>{item.message}{item.tags?.length ? <small className="pc-mono">{item.tags.join(", ")}</small> : null}</td>
      <td className="pc-num">{item.lines.length ? `${item.lines.join(", ")}${item.count > item.lines.length ? t(" and {count} more", { count: item.count - item.lines.length }) : ""}` : "—"}</td></tr>)}</tbody></table>;
}

/** Deleting takes the import's data with it: the name is typed to confirm. */
function DeleteDialog({ item, onClose, onDone }: { item: ImportItem; onClose: () => void; onDone: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function remove() {
    setBusy(true); setError("");
    try { await api.deleteImport(item.id); onDone(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  }
  return <Dialog title={t("Delete import: {name}", { name: item.name })} onClose={onClose}>
      {error && <ErrorBox text={error} />}
      <p>{t("This deletes {signals} signals and {values} values. It cannot be undone.", { signals: formatCount(item.points), values: formatCount(item.written ?? item.values) })}</p>
      <label>{t("Type {id} to confirm", { id: item.id })}<input value={typed} onChange={(event) => setTyped(event.target.value)} autoFocus /></label>
      <footer><button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button className="button button-danger" disabled={busy || typed.trim() !== item.id} onClick={() => void remove()}><Trash2 size={15} />{t("Delete")}</button></footer>
  </Dialog>;
}

/** An import's status; while written, its step and how far it is. */
function Status({ item }: { item: ImportItem }) {
  const shown = STATUS[item.status];
  if (item.status === "writing") {
    const percent = item.progress == null ? null : Math.round(item.progress * 100);
    return <><Pill status={shown.pill} label={item.queued ? t("Waiting") : t(shown.label)} />
      {!item.queued && <span className="import-progress"><progress max={100} value={percent ?? undefined} aria-label={t("Progress")} />{percent != null && <small className="pc-num">{percent}%</small>}</span>}
      {(item.queued || item.progress == null) && <small>{item.queued ? t("In the queue: the collector writes one file at a time.") : item.step}</small>}</>;
  }
  const checked = isRepeat(item.repeat) && item.repeat.checked_ms ? t("Folder checked {ago}", { ago: ago(item.repeat.checked_ms) }) : "";
  const problem = isRepeat(item.repeat) ? item.repeat.problem : "";
  return <><Pill status={shown.pill} label={t(shown.label)} />{item.detail && <small>{item.detail}</small>}{problem ? <small className="bad">{problem}</small> : checked && <small>{checked}</small>}</>;
}

/** Repeat an import from a folder: each new or changed file there is read the way the import
 * reads its files, into the same signals. The folder is only read. */
function RepeatDialog({ item, onClose, onDone }: { item: ImportItem; onClose: () => void; onDone: (notice: string) => void }) {
  const current = isRepeat(item.repeat) ? item.repeat : null;
  const [pattern, setPattern] = useState(current?.pattern ?? "");
  const [every, setEvery] = useState(current?.check_minutes ?? 60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(text: string) {
    setBusy(true); setError("");
    try {
      const answer = await api.repeatImport(item.id, text, every);
      onDone(text ? t("{name} repeats from {pattern}: {count} files there now.", { name: item.name, pattern: text, count: answer.found }) : t("{name} no longer repeats. Its values stay.", { name: item.name }));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  }
  return <Dialog title={t("Repeat {name} from a folder", { name: item.name })} onClose={onClose}>
    {error && <ErrorBox text={error} />}
    <p className="muted">{t("Each file in the folder that is new or changed is read the way this import reads its files, into the same signals: new tags become signals, values at a time already there are replaced. The files are only read, never moved or changed. Each one shows in the queue while it is written.")}</p>
    <div className="form-grid">
      <label>{t("File or pattern")}<input value={pattern} placeholder="/csv/lab/*.csv" maxLength={500} onChange={(event) => setPattern(event.target.value)} autoFocus />
        <small>{t("A file, or a pattern in its last part, inside the folders the administrator opened to CSV sources.")}</small></label>
      <label>{t("Check the folder")}<select value={every} onChange={(event) => setEvery(Number(event.target.value))}>{REPEAT_EVERY.map(([minutes, label]) => <option key={minutes} value={minutes}>{t(label)}</option>)}</select>
        <small>{t("A file that has not changed is not read again.")}</small></label>
    </div>
    <footer>
      {current && <button className="button button-secondary" disabled={busy} onClick={() => void save("")}>{t("Stop repeating")}</button>}
      <button className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
      <button className="button button-primary" disabled={busy || !pattern.trim()} onClick={() => void save(pattern.trim())}><FolderSync size={15} />{t("Repeat")}</button>
    </footer>
  </Dialog>;
}
