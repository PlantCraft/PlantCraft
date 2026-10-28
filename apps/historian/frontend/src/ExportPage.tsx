/**
 * Export: search assets of any kind and tags, tick what you want, "Add" puts their tags in the
 * package list below, repeat, then download one ZIP with the series and metadata. A choice
 * can be saved under a name and run again later ("the same package for the last day"). The
 * tags can be replaced by aliases; the key that turns them back stays here.
 */
import { DataTable, isoOf, localOf, MultiSelect, confirmAction } from "@plantcraft/ui";
import { Boxes, Download, KeyRound, ListPlus, Save, Search, Tags, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type Downloaded, type Aggregate, type ExportChoice, type ExportTag, type SavedExport } from "./api";
import { t } from "./i18n";
import type { ExportAsset, ExportOptions, ExportPreview, Me, Point } from "./types";
import { NotebookButton } from "./notebook";
import { ExportSignalList } from "./SignalList";
import { ErrorBox, FormFooter, Heading, Loading } from "./ui";

const PERIODS: { hours: number; label: string }[] = [
  { hours: 2, label: "Last 2 hours" },
  { hours: 24, label: "Last 24 hours" },
  { hours: 24 * 7, label: "Last 7 days" },
  { hours: 24 * 30, label: "Last 30 days" },
];
const STEPS: { seconds: number | null; label: string }[] = [
  { seconds: null, label: "As recorded" },
  { seconds: 60, label: "Every minute" },
  { seconds: 600, label: "Every 10 minutes" },
  { seconds: 3600, label: "Every hour" },
  { seconds: 86400, label: "Every day" },
];
/** What each step keeps (owner, 2026-10-21). */
export const AGGREGATES: { id: Aggregate; label: string }[] = [
  { id: "mean", label: "Mean (time-weighted)" },
  { id: "first", label: "First value" },
  { id: "last", label: "Last value" },
  { id: "min", label: "Lowest value" },
  { id: "max", label: "Highest value" },
];
/** The kind filter's entry for tags (assets filter by their own kinds). */
export const TAG_KIND = "@tag";

/** What the browser saved, in a sentence: where it went and what the package holds. */
export function downloadedText(file: Downloaded): string {
  const size = file.bytes < 1024 * 1024 ? t("{kb} kB", { kb: Math.max(1, Math.round(file.bytes / 1024)) }) : t("{mb} MB", { mb: (file.bytes / 1024 / 1024).toFixed(1) });
  const saved = t("{name} ({size}) is in your browser's downloads.", { name: file.name, size });
  if (file.rows === undefined) return saved;
  const held = t("It holds {rows} rows of {signals} tags; CSV compresses well, so a small ZIP is normal.", { rows: file.rows, signals: file.signals ?? 0 });
  const missed = file.notRead ? ` ${t("{count} tags could not be read: see manifest.json.", { count: file.notRead })}` : "";
  return `${saved} ${held}${missed}`;
}

/** Each asset's path of names from the top ("Site / Unit 100 / Area 1"). */
export function assetPaths(assets: ExportAsset[]): Record<string, string> {
  const byId = new Map(assets.map((item) => [item.id, item]));
  const paths: Record<string, string> = {};
  for (const item of assets) {
    const names: string[] = [];
    let current = item.parent_id ? byId.get(item.parent_id) : undefined;
    while (current && names.length < 12) { names.unshift(current.name); current = current.parent_id ? byId.get(current.parent_id) : undefined; }
    paths[item.id] = names.join(" / ");
  }
  return paths;
}

/** Assets matching a search, by name, id or path, of the kinds chosen (none: every kind). */
export function matchAssets(assets: ExportAsset[], paths: Record<string, string>, query: string, kinds: string[] = []): ExportAsset[] {
  const needle = query.trim().toLowerCase();
  const assetKinds = kinds.filter((kind) => kind !== TAG_KIND);
  if (kinds.length && !assetKinds.length) return [];
  return assets.filter((item) => (!assetKinds.length || assetKinds.includes(item.kind))
    && (!needle || `${item.name} ${item.id} ${paths[item.id] ?? ""}`.toLowerCase().includes(needle)));
}

/** The kinds to filter by: tags, then every kind of asset in the tree, with counts. */
export function kindOptions(assets: ExportAsset[], tagCount: number) {
  const kinds = new Map<string, { id: string; label: string; count: number }>();
  for (const item of assets) {
    const found = kinds.get(item.kind) ?? { id: item.kind, label: item.kind_label || item.kind, count: 0 };
    found.count += 1;
    kinds.set(item.kind, found);
  }
  return [{ id: TAG_KIND, label: t("Signals"), count: tagCount }, ...[...kinds.values()].sort((a, b) => a.label.localeCompare(b.label))];
}

/** Adds tags to the package list, keeping the first entry of each signal and the order. */
export function addTags(list: ExportTag[], more: ExportTag[]): ExportTag[] {
  const seen = new Set(list.map((item) => item.signal));
  return [...list, ...more.filter((item) => !seen.has(item.signal) && seen.add(item.signal))];
}

const tagOfPoint = (point: Point): ExportTag => ({ signal: point.signal, tag: point.tag, name: point.name || point.description || "", unit: point.unit || "", archived: true });
const tagOfSignal = (signal: string): ExportTag => ({ signal, tag: signal.split(":").slice(1).join(":") || signal, name: "", unit: "", archived: true });

export function ExportPage({ me }: { me: Me }) {
  const [options, setOptions] = useState<ExportOptions | null>(null);
  const [saved, setSaved] = useState<SavedExport[]>([]);
  const [current, setCurrent] = useState<SavedExport | null>(null);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [points, setPoints] = useState<Point[]>([]);
  const [checkedTags, setCheckedTags] = useState<string[]>([]);
  const [checkedAssets, setCheckedAssets] = useState<string[]>([]);
  const [list, setList] = useState<ExportTag[]>([]);
  const [assets, setAssets] = useState<string[]>([]);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [hours, setHours] = useState<number | "custom">(24);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [step, setStep] = useState<number | null>(600);
  const [aggregate, setAggregate] = useState<Aggregate>("mean");
  const [anonymize, setAnonymize] = useState(false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : String(err));
  useEffect(() => {
    api.exportOptions().then(setOptions).catch(fail);
    api.savedExports().then(setSaved).catch(() => setSaved([]));
  }, []);
  const showTags = !kinds.length || kinds.includes(TAG_KIND);
  useEffect(() => {
    if (!showTags || !query.trim()) { setPoints([]); return; }
    const timer = window.setTimeout(() => { api.points(query.trim()).then((items) => setPoints(items.slice(0, 200))).catch(() => setPoints([])); }, 250);
    return () => window.clearTimeout(timer);
  }, [showTags, query]);

  const paths = useMemo(() => assetPaths(options?.assets ?? []), [options]);
  const byId = useMemo(() => new Map((options?.assets ?? []).map((item) => [item.id, item])), [options]);
  const kindList = useMemo(() => kindOptions(options?.assets ?? [], options?.points ?? 0), [options]);
  const listed = useMemo(() => (query.trim() || kinds.length ? matchAssets(options?.assets ?? [], paths, query, kinds) : []), [options, paths, query, kinds]);
  const signals = useMemo(() => list.map((item) => item.signal), [list]);

  const choice = (): ExportChoice => ({
    signals,
    assets,
    expand_assets: false,
    ...(hours === "custom" ? { start: isoOf(start) || undefined, end: isoOf(end) || undefined, hours: undefined } : { hours }),
    step_seconds: step,
    aggregate,
    anonymize,
  });

  useEffect(() => {
    if (!signals.length) { setPreview(null); setPreviewError(""); return; }
    const timer = window.setTimeout(() => {
      api.exportPreview({ signals, assets, expand_assets: false }).then((value) => { setPreview(value); setPreviewError(""); }).catch((err: Error) => { setPreview(null); setPreviewError(err.message); });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [signals, assets]);

  async function add() {
    setAdding(true); setError("");
    try {
      const fromAssets = checkedAssets.length ? (await api.exportResolve(checkedAssets)).tags : [];
      const fromPoints = points.filter((point) => checkedTags.includes(point.signal)).map(tagOfPoint);
      setList((value) => addTags(value, [...fromPoints, ...fromAssets]));
      setAssets((value) => [...value, ...checkedAssets.filter((item) => !value.includes(item))]);
      setDone(t("{count} tags added.", { count: fromPoints.length + fromAssets.length }));
      setCheckedTags([]); setCheckedAssets([]);
    } catch (err) { fail(err); } finally { setAdding(false); }
  }

  async function open(item: SavedExport) {
    setError(""); setDone(""); setCurrent(item); setName(item.name);
    setAssets(item.assets); setStep(item.step_seconds ?? null); setAggregate(item.aggregate ?? "mean"); setAnonymize(item.anonymize);
    if (item.hours) { setHours(PERIODS.some((period) => period.hours === item.hours) ? item.hours : 24); setStart(""); setEnd(""); }
    else { setHours("custom"); setStart(localOf(item.start ?? "")); setEnd(localOf(item.end ?? "")); }
    let known: ExportTag[] = [];
    if (item.assets.length) { try { known = (await api.exportResolve(item.assets)).tags; } catch { known = []; } }
    const bySignal = new Map(known.map((tag) => [tag.signal, tag]));
    setList(item.signals.map((signal) => bySignal.get(signal) ?? tagOfSignal(signal)));
  }

  async function save(asNew: boolean) {
    const body = { name: name.trim(), signals, assets, step_seconds: step, aggregate, anonymize, ...(hours === "custom" ? { start: isoOf(start) || null, end: isoOf(end) || null, hours: null } : { hours, start: null, end: null }) };
    setBusy(true); setError(""); setDone("");
    try {
      const value = current && !asNew ? await api.updateSavedExport(current.id, body) : await api.saveExport(body);
      setCurrent(value);
      setSaved(await api.savedExports());
      setDone(t("Saved \"{name}\".", { name: value.name }));
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function remove() {
    if (!current || !(await confirmAction(t("Delete the saved export \"{name}\"?", { name: current.name }), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteSavedExport(current.id); setSaved(await api.savedExports()); startOver(); } catch (err) { fail(err); }
  }

  function startOver() { setCurrent(null); setName(""); setList([]); setAssets([]); setDone(""); }

  async function run(action: (value: ExportChoice) => Promise<Downloaded>) {
    setBusy(true); setError(""); setDone("");
    try { setDone(downloadedText(await action(choice()))); }
    catch (err) { fail(err); }
    finally { setBusy(false); }
  }

  const toggle = (value: string[], set: (next: string[]) => void, key: string) => set(value.includes(key) ? value.filter((item) => item !== key) : [...value, key]);
  const customMissing = hours === "custom" && (!start || !end);
  const empty = !list.length;
  const checked = checkedTags.length + checkedAssets.length;
  const mine = !current || current.created_by === me.username || me.can_edit;
  return <>
    <Heading
      eyebrow={t("Historian")}
      title={t("Exports")}
      detail={t("Choose signals or assets, a period and a resolution, and download their history with its metadata as one ZIP. Save a choice to run it again.")}
      actions={<ExportSignalList onError={setError} />}
    />
    {error && <ErrorBox text={error} />}
    {done && <div className="notice notice-ok">{done}</div>}
    {!options ? (error ? null : <Loading text={t("Loading…")} />) : <div className="export-layout">
      <aside className="panel export-saved" aria-label={t("Saved exports")}>
        <div className="panel-header"><div><h2>{t("Saved exports")}</h2></div></div>
        <ul>
          <li><button type="button" className={!current ? "on" : ""} onClick={startOver}>{t("New export")}</button></li>
          {saved.map((item) => <li key={item.id}><button type="button" className={current?.id === item.id ? "on" : ""} onClick={() => void open(item)}>
            <span>{item.name}</span><small>{[item.signals.length ? t("{count} tags", { count: item.signals.length }) : null, item.hours ? t(PERIODS.find((period) => period.hours === item.hours)?.label ?? "Last {hours} hours", { hours: item.hours }) : t("Fixed period")].filter(Boolean).join(" · ")}</small>
          </button></li>)}
          {!saved.length && <li className="muted small">{t("None yet. Build a package and save it to run it again later.")}</li>}
        </ul>
      </aside>

      <div className="export-main">
        <section className="panel export-choose">
          <div className="panel-header"><div><h2>{t("1. Find and add")}</h2><p>{t("Search by name, tag or path. Adding an asset adds the signals under it; a loop is just one asset type.")}</p></div></div>
          <div className="export-toolbar">
            <label className="export-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search assets and signals")} aria-label={t("Search")} /></label>
            <MultiSelect label={t("Type")} options={kindList} value={kinds} onChange={setKinds} />
            <button type="button" className="button button-secondary" disabled={!checked || adding} onClick={() => void add()}><ListPlus size={16} />{checked ? t("Add {count}", { count: checked }) : t("Add")}</button>
          </div>
          {options.assets_error && <p className="notice notice-warn">{t("PlantCraft's asset tree could not be read: {error}", { error: options.assets_error })}</p>}
          {!query.trim() && !kinds.length ? <p className="muted">{t("Type to search, or pick a type to list every asset of it.")}</p> : <ul className="export-list">
            {listed.map((item) => <li key={item.id}><label className="check">
              <input type="checkbox" checked={checkedAssets.includes(item.id)} onChange={() => toggle(checkedAssets, setCheckedAssets, item.id)} disabled={!item.signals} />
              <Boxes size={15} aria-hidden="true" className="export-icon" />
              <span><b>{item.name}</b><small>{[item.kind_label || item.kind, paths[item.id], t("{count} tags", { count: item.signals })].filter(Boolean).join(" · ")}</small></span>
            </label></li>)}
            {showTags && points.map((point) => <li key={point.signal}><label className="check">
              <input type="checkbox" checked={checkedTags.includes(point.signal) || signals.includes(point.signal)} disabled={signals.includes(point.signal)} onChange={() => toggle(checkedTags, setCheckedTags, point.signal)} />
              <Tags size={15} aria-hidden="true" className="export-icon" />
              <span><b className="pc-mono">{point.tag}</b><small>{[point.name || point.description, point.unit, point.source_id].filter(Boolean).join(" · ")}</small></span>
            </label></li>)}
            {!listed.length && !points.length && <li className="muted">{t("Nothing matches.")}</li>}
          </ul>}
        </section>

        <section className="panel export-package">
          <div className="panel-header"><div><h2>{t("2. Signals to export")}</h2>{preview && <p className="export-preview"><b className="pc-num">{preview.signals}</b> {t("signals")} · <b className="pc-num">{preview.assets}</b> {t("assets")}</p>}</div>
            {!empty && <button type="button" className="button button-secondary" onClick={() => { setList([]); setAssets([]); }}>{t("Clear")}</button>}</div>
          {empty ? <p className="muted">{t("Nothing added yet.")}</p> : <DataTable
            rows={list}
            rowKey={(item) => item.signal}
            label={t("Signals to export")}
            selectable
            searchText={(item) => `${item.tag} ${item.name} ${item.unit} ${item.asset_name ?? ""} ${item.role ?? ""}`}
            searchPlaceholder={t("Filter the list")}
            actions={(selected, clear) => <button type="button" className="button button-secondary button-small" onClick={() => { const drop = new Set(selected.map((item) => item.signal)); setList(list.filter((item) => !drop.has(item.signal))); clear(); }}><Trash2 size={14} />{t("Remove selected")}</button>}
            columns={[
              { key: "tag", label: t("Tag"), sort: (item) => item.tag, render: (item) => <span className="pc-mono">{item.tag}{!item.archived && <small className="muted"> · {t("not archived")}</small>}</span> },
              { key: "name", label: t("Name"), sort: (item) => item.name },
              { key: "unit", label: t("Unit"), sort: (item) => item.unit },
              { key: "from", label: t("From"), sort: (item) => item.asset_name ?? "", render: (item) => <span className="muted">{item.asset_name ? [item.asset_name, item.role].filter(Boolean).join(" · ") : ""}</span> },
              { key: "remove", label: "", render: (item) => <button type="button" className="icon-button" onClick={() => setList(list.filter((entry) => entry.signal !== item.signal))} aria-label={t("Remove {tag}", { tag: item.tag })}><X size={14} /></button> },
            ]}
          />}
          {previewError && <p className="form-error">{previewError}</p>}
        </section>

        <form className="panel export-form" onSubmit={(event) => { event.preventDefault(); void run(api.exportPackage); }}>
          <div className="panel-header"><div><h2>{t("3. Period and download")}</h2></div></div>
          <div className="form-grid">
            <label>{t("Period")}<select value={String(hours)} onChange={(event) => setHours(event.target.value === "custom" ? "custom" : Number(event.target.value))}>
              {PERIODS.map((item) => <option key={item.hours} value={item.hours}>{t(item.label)}</option>)}
              <option value="custom">{t("From – to")}</option>
            </select></label>
            {hours === "custom" && <>
              <label>{t("From")}<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} required /></label>
              <label>{t("To")}<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} required /></label>
            </>}
            <label>{t("Resolution")}<select value={String(step)} onChange={(event) => setStep(event.target.value === "null" ? null : Number(event.target.value))}>
              {STEPS.map((item) => <option key={String(item.seconds)} value={String(item.seconds)}>{t(item.label)}</option>)}
            </select></label>
            {step !== null && <label>{t("Each step keeps")}<select value={aggregate} onChange={(event) => setAggregate(event.target.value as Aggregate)}>
              {AGGREGATES.map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}
            </select></label>}
          <p className="form-note">{t("A relative period (\"last 24 hours\") reads up to the moment you download. At most {days} days ({raw} as recorded) and {count} tags per package.", { days: options.max_days, raw: options.max_raw_days, count: options.max_signals })}</p>
          <label className="check field-span"><input type="checkbox" checked={anonymize} onChange={(event) => setAnonymize(event.target.checked)} />{t("Replace tags and asset names by aliases (S001, A001…)")}</label>
          {anonymize && <p className="form-note">{t("Names and descriptions are left out. Download the key to turn the aliases back into tags; it stays with you.")}</p>}
          </div>

          <div className="export-save">
            <label>{t("Save this export as")}<input value={name} maxLength={120} placeholder={t("Unit 100, last day")} onChange={(event) => setName(event.target.value)} /></label>
            <button type="button" className="button button-secondary" disabled={busy || empty || !name.trim() || !mine || customMissing} onClick={() => void save(false)}><Save size={15} />{current ? t("Save") : t("Save export")}</button>
            {current && <button type="button" className="button button-secondary" disabled={busy || empty || !name.trim() || customMissing} onClick={() => void save(true)}>{t("Save as new")}</button>}
            {current && mine && <button type="button" className="button button-danger button-icon" onClick={() => void remove()} aria-label={t("Delete")} title={t("Delete")}><Trash2 size={15} /></button>}
          </div>

          <FormFooter>
            {anonymize && <button type="button" className="button button-secondary" disabled={busy || empty} onClick={() => void run(api.exportKey)}><KeyRound size={16} />{t("Download key")}</button>}
            <NotebookButton signals={signals} disabled={customMissing || empty} step={step}
              start={hours === "custom" ? isoOf(start) || "" : `-${hours}h`} end={hours === "custom" ? isoOf(end) || "" : "now"} />
            <button className="button button-primary" disabled={busy || customMissing || empty || Boolean(previewError)}><Download size={16} className={busy ? "spin" : ""} />{busy ? t("Preparing…") : t("Download package")}</button>
          </FormFooter>
          <details className="export-about">
            <summary>{t("What's inside")}</summary>
            <ul>
              <li><b className="pc-mono">series.csv</b> {t("one column per signal, time in UTC")}</li>
              <li><b className="pc-mono">signals.csv</b> {t("every signal: tag, name, unit, limits and the asset and role it serves")}</li>
              <li><b className="pc-mono">assets.csv</b> {t("the assets the signals came from, with their signals by role")}</li>
              <li><b className="pc-mono">plant-map.json</b> {t("the assets and signals as a PlantCraft plant map")}</li>
              <li><b className="pc-mono">manifest.json</b> {t("period, choices and a checksum of every file")}</li>
            </ul>
            <p className="muted small">{t("To open it in another PlantCraft: import series.csv in its Historian (Imports), then import plant-map.json in Administration > Setup. Every export is recorded in PlantCraft's audit log.")}</p>
          </details>
        </form>
      </div>
    </div>}
  </>;
}
