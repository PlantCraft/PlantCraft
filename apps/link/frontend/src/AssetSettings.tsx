/**
 * What an algorithm on assets adds to an algorithm: when it runs (its cycle, the window each run
 * reads and the step it reads on), the assets it runs on, and its latest run on each of them.
 */
import { DataTable, type DataColumn } from "@plantcraft/ui";
import { LoaderCircle, Play, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatAgo, t } from "./i18n";
import { resultLabel } from "./status";
import type { AssetChoice, AssetRun, AssetTiming, AssetTypeChoice, Me } from "./types";
import { ErrorBox, Link, Loading, Pill } from "./ui";

let choicesCache: Promise<AssetChoice[]> | null = null;
/** PlantCraft's assets, read once per page load. */
export function assetChoices(): Promise<AssetChoice[]> {
  if (!choicesCache) choicesCache = api.assetChoices().catch((error: unknown) => { choicesCache = null; throw error; });
  return choicesCache;
}

/** The equipment types an algorithm also runs on every asset of (A20): a pump algorithm on every
 * pump, an asset of the type added later included at its next run. */
export function AssetTypePicker({ types, onChange, disabled }: { types: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const [choices, setChoices] = useState<AssetTypeChoice[] | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState("");
  useEffect(() => { api.assetTypeChoices().then(setChoices).catch((err: Error) => setError(err.message)); }, []);
  const byId = useMemo(() => new Map((choices ?? []).map((item) => [item.id, item])), [choices]);
  const free = (choices ?? []).filter((item) => !types.includes(item.id));
  return <div className="asset-picker" data-testid="asset-type-picker">
    {types.length
      ? <ul>{types.map((typeId) => {
        const found = byId.get(typeId);
        return <li key={typeId}>
          <span><b>{t("Every {type}", { type: found?.name ?? typeId })}</b><small>{found ? [typeId, found.roles.length ? t("roles {roles}", { roles: found.roles.join(", ") }) : ""].filter(Boolean).join(" · ") : t("Not in PlantCraft now")}</small></span>
          {!disabled && <button type="button" className="icon-button" aria-label={t("Take {name} out", { name: found?.name ?? typeId })} onClick={() => onChange(types.filter((item) => item !== typeId))}><X size={14} /></button>}
        </li>;
      })}</ul>
      : <p className="muted small">{t("No equipment type: it runs only on the assets above.")}</p>}
    {error && <p className="muted small">{error}</p>}
    {!disabled && <span className="asset-picker-add">
      <select aria-label={t("Equipment type to add")} value={adding} onChange={(event) => setAdding(event.target.value)}>
        <option value="">{choices ? t("Choose an equipment type…") : t("Reading PlantCraft's asset types…")}</option>
        {free.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      <button type="button" className="button button-secondary" disabled={!adding} onClick={() => { onChange([...types, adding]); setAdding(""); }}><Plus size={15} />{t("Add")}</button>
    </span>}
  </div>;
}

/** The cycle, window and step of an algorithm on assets (seconds, the window shown in minutes). */
export function TimingFields({ timing, onChange, disabled }: { timing: AssetTiming; onChange: (next: AssetTiming) => void; disabled?: boolean }) {
  const set = (key: keyof AssetTiming, value: string, scale = 1) => {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) onChange({ ...timing, [key]: number * scale });
  };
  return <div className="asset-timing">
    <label>{t("Every (s)")}<input type="number" min={10} step={10} value={timing.cycle_seconds} disabled={disabled} onChange={(event) => set("cycle_seconds", event.target.value)} /></label>
    <label>{t("Window (min)")}<input type="number" min={1} step={1} value={Math.round(timing.window_seconds / 6) / 10} disabled={disabled} onChange={(event) => set("window_seconds", event.target.value, 60)} /></label>
    <label>{t("Step (s)")}<input type="number" min={0.1} step={1} value={timing.step_seconds} disabled={disabled} onChange={(event) => set("step_seconds", event.target.value)} /></label>
    <small>{t("Each run reads the window that ends at its time, on the step, and runs again after the cycle.")}</small>
  </div>;
}

/** The assets an algorithm runs on, picked from PlantCraft's asset tree. */
export function AssetPicker({ assets, onChange, disabled }: { assets: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const [choices, setChoices] = useState<AssetChoice[] | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState("");
  useEffect(() => { assetChoices().then(setChoices).catch((err: Error) => setError(err.message)); }, []);
  const byId = useMemo(() => new Map((choices ?? []).map((item) => [item.id, item])), [choices]);
  const free = (choices ?? []).filter((item) => !assets.includes(item.id));
  return <div className="asset-picker">
    {assets.length
      ? <ul>{assets.map((assetId) => {
        const found = byId.get(assetId);
        return <li key={assetId}>
          <span><b>{found?.name ?? assetId}</b><small>{found ? [found.path, found.kind].filter(Boolean).join(" · ") : t("Not in PlantCraft now")}</small></span>
          {!disabled && <button type="button" className="icon-button" aria-label={t("Take {name} out", { name: found?.name ?? assetId })} onClick={() => onChange(assets.filter((item) => item !== assetId))}><X size={14} /></button>}
        </li>;
      })}</ul>
      : <p className="muted small">{t("No asset yet: the algorithm runs on none.")}</p>}
    {error && <p className="muted small">{error}</p>}
    {!disabled && <span className="asset-picker-add">
      <select aria-label={t("Asset to add")} value={adding} onChange={(event) => setAdding(event.target.value)}>
        <option value="">{choices ? t("Choose an asset…") : t("Reading PlantCraft's assets…")}</option>
        {free.map((item) => <option key={item.id} value={item.id}>{item.path ? `${item.path} / ${item.name}` : item.name}</option>)}
      </select>
      <button type="button" className="button button-secondary" disabled={!adding} onClick={() => { onChange([...assets, adding]); setAdding(""); }}><Plus size={15} />{t("Add")}</button>
    </span>}
  </div>;
}

const RUN_COLUMNS: DataColumn<AssetRun>[] = [
  { key: "asset", label: t("Asset"), sort: (item) => item.asset_name, render: (item) => <Link to={`/assets/${encodeURIComponent(item.asset_id)}`} className="strong">{item.asset_name}</Link> },
  { key: "status", label: t("Status"), sort: (item) => resultLabel(item.status), render: (item) => <Pill status={item.status === "bad" ? "alarm" : item.status} label={resultLabel(item.status)} />, filter: { value: (item) => resultLabel(item.status) } },
  { key: "message", label: t("What it says"), render: (item) => <small>{item.error ? `${t("Did not run")}: ${item.error}` : item.message || "—"}</small> },
  { key: "at", label: t("Ran"), sort: (item) => item.analyzed_at ?? "", render: (item) => <small>{item.analyzed_at ? formatAgo(item.analyzed_at) : "—"}</small> },
];

/** An algorithm on assets on its page: its latest run on each asset, and Run now. */
export function AssetRuns({ algorithmId, assets, types = [], me }: { algorithmId: string; assets: string[]; types?: string[]; me: Me }) {
  const [rows, setRows] = useState<AssetRun[] | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const load = () => api.algorithmRuns(algorithmId).then((found) => { setRows(found); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => window.clearInterval(timer);
  }, [algorithmId]);
  async function runNow() {
    setRunning(true);
    try { setRows(await api.runAlgorithm(algorithmId)); setError(""); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }
  return <div className="panel used-by">
    <p>{types.length
      ? t("Runs on {count} named assets and every asset of {types}, each on its own cycle.", { count: assets.length, types: types.join(", ") })
      : assets.length ? t("Runs on {count} assets, each on its own cycle.", { count: assets.length }) : t("No asset yet: choose them below.")}</p>
    {error && <ErrorBox text={error} />}
    {!rows ? <Loading /> : rows.length
      ? <DataTable rows={rows} columns={RUN_COLUMNS} rowKey={(item) => item.asset_id} initialSort={{ key: "asset", descending: false }} label={t("Latest run on each asset")} />
      : assets.length || types.length ? <p className="muted small">{t("Not run yet: its first run starts within a cycle.")}</p> : null}
    {me.can_edit && (assets.length > 0 || types.length > 0) && <div className="row-actions"><button type="button" className="button button-secondary" disabled={running} onClick={() => void runNow()}>{running ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}{t("Run now")}</button></div>}
  </div>;
}
