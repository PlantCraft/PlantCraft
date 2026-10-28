/**
 * Where a value comes from: an asset's signal role (follows the plant map) or one signal. The
 * editors of every app that reads the plant use it (a twin's variables, an alarm's input).
 */
import { useEffect, useMemo, useState } from "react";
import { t } from "./i18n.js";

/** An asset as the pickers list it: its roles name the signals it holds. */
export interface AssetOption { id: string; name: string; kind?: string | null; parent?: string | null; signals?: Record<string, string> }
export interface SignalOption { id: string; name: string; unit?: string | null }
/** One of: `{asset_id, role}` or `{signal_id}` (empty while nothing is chosen). */
export interface SourceRef { asset_id?: string | null; role?: string | null; signal_id?: string | null }

export interface SourcePickerProps {
  value: SourceRef;
  assets: AssetOption[];
  onChange: (source: SourceRef) => void;
  label: string;
  /** Signals matching a text (the app's `/api/signals`). */
  searchSignals: (text: string) => Promise<SignalOption[]>;
}

export function SourcePicker({ value, assets, onChange, label, searchSignals }: SourcePickerProps) {
  const [mode, setMode] = useState<"asset" | "signal">(value.signal_id ? "signal" : "asset");
  const asset = assets.find((item) => item.id === value.asset_id);
  return <div className="pc-source">
    <div className="pc-segmented" role="group" aria-label={label}>
      <button type="button" className={mode === "asset" ? "on" : ""} onClick={() => { setMode("asset"); if (value.signal_id) onChange({}); }}>{t("Asset role")}</button>
      <button type="button" className={mode === "signal" ? "on" : ""} onClick={() => { setMode("signal"); if (value.asset_id) onChange({}); }}>{t("Signal")}</button>
    </div>
    {mode === "asset" ? <div className="pc-source-fields">
      <AssetSearch assets={assets} value={value.asset_id ?? ""} label={t("{label}: asset", { label })} onPick={(id) => {
        const picked = assets.find((item) => item.id === id);
        const roles = Object.keys(picked?.signals ?? {});
        onChange({ asset_id: id || null, role: value.role && roles.includes(value.role) ? value.role : roles.length === 1 ? roles[0] : null });
      }} />
      <select aria-label={t("{label}: role", { label })} value={value.role ?? ""} onChange={(event) => onChange({ asset_id: value.asset_id, role: event.target.value || null })} disabled={!asset}>
        <option value="">{t("role…")}</option>
        {Object.entries(asset?.signals ?? {}).map(([role, signal]) => <option key={role} value={role} title={signal}>{role}</option>)}
      </select>
    </div> : <SignalSearch value={value.signal_id ?? ""} label={t("{label}: signal", { label })} onPick={(id) => onChange({ signal_id: id || null })} search={searchSignals} />}
  </div>;
}

/** Find an asset by id, name or parent among the ones given. */
export function AssetSearch({ assets, value, onPick, label, placeholder }: { assets: AssetOption[]; value: string; onPick: (id: string) => void; label: string; placeholder?: string }) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  useEffect(() => setText(value), [value]);
  const found = useMemo(() => {
    const query = text.trim().toLowerCase();
    return assets.filter((item) => !query || `${item.id} ${item.name} ${item.parent ?? ""}`.toLowerCase().includes(query)).slice(0, 30);
  }, [assets, text]);
  return <div className="pc-search">
    <input aria-label={label} value={text} placeholder={placeholder ?? t("Search assets")} onFocus={() => setOpen(true)}
      onBlur={() => window.setTimeout(() => { setOpen(false); if (text !== value && !assets.some((item) => item.id === text)) setText(value); }, 150)}
      onChange={(event) => { setText(event.target.value); setOpen(true); if (!event.target.value) onPick(""); }} />
    {open && found.length > 0 && <ul>{found.map((item) => <li key={item.id}><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { onPick(item.id); setText(item.id); setOpen(false); }}>
      <span>{item.name}</span><small>{item.id}{item.kind ? ` · ${item.kind}` : ""}{item.parent ? ` · ${item.parent}` : ""}</small></button></li>)}</ul>}
  </div>;
}

/** Find a signal by text, asking the app as the person types. */
export function SignalSearch({ value, onPick, label, search }: { value: string; onPick: (id: string) => void; label: string; search: (text: string) => Promise<SignalOption[]> }) {
  const [text, setText] = useState(value);
  const [found, setFound] = useState<SignalOption[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => { search(text.trim()).then(setFound).catch(() => setFound([])); }, 200);
    return () => window.clearTimeout(timer);
  }, [text, open, search]);
  return <div className="pc-search pc-grow">
    <input aria-label={label} value={text} placeholder={t("Search signals")} onFocus={() => setOpen(true)}
      onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      onChange={(event) => { setText(event.target.value); if (!event.target.value) onPick(""); }} />
    {open && found.length > 0 && <ul>{found.map((item) => <li key={item.id}><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { onPick(item.id); setText(item.id); setOpen(false); }}>
      <span>{item.name}</span><small>{item.id}{item.unit ? ` · ${item.unit}` : ""}</small></button></li>)}</ul>}
  </div>;
}
