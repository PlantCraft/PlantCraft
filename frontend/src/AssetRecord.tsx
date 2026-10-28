/** One asset's record, signals by role and relations: the parts of the asset page built from its type. */
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, ArrowDownLeft, ArrowUpRight, LoaderCircle, Plug, Plus, Save, Search, Waves, X } from "lucide-react";
import { requestJson } from "./api";
import { modelApi, showValue, type AssetRelations, type AssetType, type AttributeValue, type CatalogSignal, type Missing, type RelationKind, type TypeAttribute } from "./assetModel";
import { locale, t } from "./i18n";
import { assetPath } from "./assetLinks";
import { navigate } from "./nav";
import { READ_ONLY } from "./session";

/** A signal the asset references; `used_in` lists the other assets that reference it too. */
export interface RecordSignal { signal_id: string; role: string; name: string; unit: string; origin: string; used_in?: { asset_id: string; name: string; kind: string; role: string }[] }
export interface AssetOption { asset_id: string; name: string; kind: string }
interface SignalValue { value: number | string | null; at: string | null }

const ORIGIN_LABELS: Record<string, string> = { platform: t("Platform"), manual: t("Entered by hand"), scenario: t("Scenario file"), map: t("Configuration file"), cpm: t("Scenario file") };

function Go({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  return <a href={to} className={className} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); navigate(to); }}>{children}</a>;
}

function message(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

function asText(value: AttributeValue | undefined) {
  return value === null || value === undefined ? "" : String(value);
}

// --- Record -----------------------------------------------------------------------

/** The attributes of the asset's type as a form, editable in place by editors. */
export function RecordForm({ assetId, type, values, missing, assets, canEdit, onSaved }: { assetId: string; type: AssetType; values: Record<string, AttributeValue>; missing: Missing; assets: AssetOption[]; canEdit: boolean; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { setDraft(Object.fromEntries(type.attributes.map((item) => [item.key, asText(values[item.key])]))); }, [type, values]);
  const changed = type.attributes.filter((item) => (draft[item.key] ?? "") !== asText(values[item.key]));
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!changed.length) return;
    setBusy(true);
    try {
      await modelApi.setAttributes(assetId, Object.fromEntries(changed.map((item) => [item.key, draft[item.key] === "" ? null : item.data_type === "number" ? Number(draft[item.key]) : draft[item.key]])));
      setError("");
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(message(err, t("Could not save.")));
    } finally {
      setBusy(false);
    }
  }
  if (!type.attributes.length) return <p className="muted">{t("The type {type} has no attributes yet.", { type: type.name })}</p>;
  return <form className="as-record" onSubmit={save} aria-label={t("Record")}>
    {error && <div className="form-error">{error}</div>}
    <div className="as-record-grid">
      {type.attributes.map((item) => {
        const empty = missing.attributes.includes(item.key);
        return <label key={item.key} className={`as-field ${empty ? "as-field-missing" : ""} ${(draft[item.key] ?? "") !== asText(values[item.key]) ? "as-field-dirty" : ""}`}>
          <span>{item.name}{item.unit ? <small> ({item.unit})</small> : null}{item.required && <em title={t("Required")}>*</em>}</span>
          {canEdit ? <FieldInput attribute={item} value={draft[item.key] ?? ""} assets={assets} assetId={assetId} onChange={(value) => { setDraft((current) => ({ ...current, [item.key]: value })); setSaved(false); }} />
            : <strong>{showValue(values[item.key], item)}</strong>}
        </label>;
      })}
    </div>
    {canEdit && <footer className="as-record-actions">
      {saved && !changed.length && <span className="ty-saved">{t("Saved.")}</span>}
      {changed.length > 0 && <span className="muted">{changed.length === 1 ? t("1 change") : t("{count} changes", { count: changed.length })}</span>}
      <button type="button" className="button button-secondary" disabled={!changed.length || busy} onClick={() => setDraft(Object.fromEntries(type.attributes.map((item) => [item.key, asText(values[item.key])])))}>{t("Discard")}</button>
      <button className="button button-primary" disabled={!changed.length || busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} {t("Save record")}</button>
    </footer>}
    {!canEdit && <p className="ty-note">{READ_ONLY}</p>}
  </form>;
}

function FieldInput({ attribute, value, assets, assetId, onChange }: { attribute: TypeAttribute; value: string; assets: AssetOption[]; assetId: string; onChange: (value: string) => void }) {
  const label = attribute.name;
  if (attribute.data_type === "choice")
    return <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><option value="">—</option>{attribute.options.map((option) => <option key={option} value={option}>{option}</option>)}{value && !attribute.options.includes(value) && <option value={value}>{value}</option>}</select>;
  if (attribute.data_type === "number") return <input aria-label={label} type="number" step="any" value={value} onChange={(event) => onChange(event.target.value)} />;
  if (attribute.data_type === "date") return <input aria-label={label} type="date" value={value} onChange={(event) => onChange(event.target.value)} />;
  if (attribute.data_type === "asset") {
    const list = `assets-${attribute.key}`;
    return <><input aria-label={label} list={list} value={value} maxLength={200} onChange={(event) => onChange(event.target.value)} /><datalist id={list}>{assets.filter((item) => item.asset_id !== assetId).slice(0, 500).map((item) => <option key={item.asset_id} value={item.asset_id}>{item.name}</option>)}</datalist></>;
  }
  return <input aria-label={label} value={value} maxLength={2000} onChange={(event) => onChange(event.target.value)} />;
}

// --- Signals by role ---------------------------------------------------------------

function fmtValue(value: SignalValue | null | undefined, unit: string) {
  if (value === undefined) return "…";
  if (!value || value.value === null) return "—";
  if (typeof value.value === "string") return value.value;
  const digits = Math.abs(value.value) >= 100 ? 0 : Math.abs(value.value) >= 10 ? 1 : 2;
  return `${value.value.toLocaleString(locale, { maximumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
}

/** The signals of an asset as one table: each role of its type with the signal that fills it
 * (or a gap to bind), then the other signals, with description, unit, last value and origin.
 * ``limit`` shows the first rows only (the overview), with a link to the rest. */
export function SignalTable({ assetId, type, signals, canEdit, onChanged, limit, onMore }: { assetId: string; type: AssetType | null; signals: RecordSignal[]; canEdit: boolean; onChanged: () => void; limit?: number; onMore?: () => void }) {
  const [values, setValues] = useState<Record<string, SignalValue | null>>({});
  const [binding, setBinding] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    for (const signal of signals.slice(0, 40)) {
      requestJson<SignalValue>(`/api/signals/${encodeURIComponent(signal.signal_id)}/value?agg=last&window=1h`)
        .then((value) => { if (!cancelled) setValues((current) => ({ ...current, [signal.signal_id]: value })); })
        .catch(() => { if (!cancelled) setValues((current) => ({ ...current, [signal.signal_id]: null })); });
    }
    return () => { cancelled = true; };
  }, [signals]);
  const rows = signalRows(type, signals);
  const shown = limit ? rows.slice(0, limit) : rows;
  async function unbind(signalId: string) {
    try { await modelApi.unbindSignal(assetId, signalId); setError(""); onChanged(); } catch (err) { setError(message(err, t("Couldn't complete the operation."))); }
  }
  if (!rows.length) return <p className="muted">{type ? t("The type {type} has no signal roles.", { type: type.name }) : t("No signals.")}</p>;
  return <div className="as-signals">
    {error && <div className="form-error">{error}</div>}
    <div className="as-sig-wrap"><table className="as-sig-table">
      <thead><tr><th>{t("Role")}</th><th>{t("Signal")}</th><th>{t("Description")}</th><th className="as-num">{t("Last value")}</th>{!limit && <th>{t("Also used in")}</th>}{!limit && <th>{t("Origin")}</th>}{canEdit && !limit && <th aria-label={t("Change")} />}</tr></thead>
      <tbody>{shown.map((row) => {
        const signal = row.signal;
        return <tr key={`${row.role}|${signal?.signal_id ?? ""}`} className={row.missing ? "as-sig-missing" : ""}>
          <td><strong>{row.roleName}</strong>{row.required && <em className="as-sig-required" title={t("Required")}>*</em>}</td>
          <td>{signal ? <Go to={`/data?q=${encodeURIComponent(signal.signal_id)}`} className="as-signal-tag"><Waves size={13} /><span>{signal.signal_id}</span></Go>
            : canEdit && !limit ? <button type="button" className="button button-secondary as-bind" onClick={() => setBinding(row.role)}><Plug size={13} /> {t("Bind signal")}</button>
            : <span className="muted">{row.missing ? t("Missing") : "—"}</span>}</td>
          <td className="muted">{signal && signal.name !== signal.signal_id ? signal.name : ""}</td>
          <td className="as-num as-value">{signal ? fmtValue(values[signal.signal_id], signal.unit) : ""}</td>
          {!limit && <td className="as-sig-used">{(signal?.used_in ?? []).map((item) => <Go key={item.asset_id} to={assetPath(item.asset_id)} className="as-used-link"><span>{item.name}</span>{item.role && <small>{item.role}</small>}</Go>)}</td>}
          {!limit && <td className="muted">{signal ? ORIGIN_LABELS[signal.origin] ?? signal.origin : ""}</td>}
          {canEdit && !limit && <td className="as-sig-edit">{signal?.origin === "manual" && <><button type="button" className="as-link-button" onClick={() => setBinding(row.role)}>{t("Change")}</button><button type="button" className="icon-button" aria-label={t("Remove {signal}", { signal: signal.signal_id })} onClick={() => void unbind(signal.signal_id)}><X size={13} /></button></>}</td>}
        </tr>;
      })}</tbody>
    </table></div>
    {limit && rows.length > limit && onMore && <button type="button" className="as-link-button" onClick={onMore}>{t("See all {count} signals", { count: rows.length })}</button>}
    {binding !== null && <SignalPicker onClose={() => setBinding(null)} onPick={async (signalId) => { try { await modelApi.bindSignal(assetId, signalId, binding); setBinding(null); setError(""); onChanged(); } catch (err) { setError(message(err, t("Couldn't complete the operation."))); } }} />}
  </div>;
}

export interface SignalRow { role: string; roleName: string; required: boolean; missing: boolean; signal: RecordSignal | null }

/** The table's rows: the type's roles in order (one row per bound signal, or a gap), then the
 * signals in no role of the type. */
export function signalRows(type: Pick<AssetType, "roles"> | null, signals: RecordSignal[]): SignalRow[] {
  const roles = type?.roles ?? [];
  const keys = new Set(roles.map((item) => item.key));
  const rows: SignalRow[] = [];
  for (const role of roles) {
    const bound = signals.filter((item) => item.role === role.key);
    if (!bound.length) rows.push({ role: role.key, roleName: role.name, required: role.required, missing: role.required, signal: null });
    for (const signal of bound) rows.push({ role: role.key, roleName: role.name, required: role.required, missing: false, signal });
  }
  for (const signal of signals.filter((item) => !keys.has(item.role))) rows.push({ role: signal.role, roleName: signal.role || t("Other"), required: false, missing: false, signal });
  return rows;
}

function SignalPicker({ onPick, onClose }: { onPick: (signalId: string) => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<CatalogSignal[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      modelApi.searchSignals(query.trim()).then((found) => { setItems(found.slice(0, 30)); setError(""); }).catch((err) => setError(message(err, t("Couldn't load."))));
    }, query ? 200 : 0);
    return () => window.clearTimeout(timer);
  }, [query]);
  return <div className="as-picker">
    <div className="as-picker-head"><label className="as-search"><Search size={15} /><input autoFocus aria-label={t("Search signals")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search signals by tag or name")} /></label><button type="button" className="icon-button" onClick={onClose} aria-label={t("Cancel")}><X size={14} /></button></div>
    {error && <p className="ap-bad">{error}</p>}
    {!items && !error && <p className="muted">{t("Loading…")}</p>}
    <ul>{(items ?? []).map((item) => <li key={item.id}><button type="button" onClick={() => onPick(item.id)}><strong>{item.id}</strong>{item.name !== item.id && <small>{item.name}</small>}{item.unit && <em>{item.unit}</em>}</button></li>)}</ul>
    {items && !items.length && <p className="muted">{t("No signal found.")}</p>}
  </div>;
}

// --- Relations ---------------------------------------------------------------------

/** Typed links to other assets: outgoing ones can be added and removed, incoming ones are read. */
export function Relations({ assetId, relations, kinds, assets, canEdit, onChanged }: { assetId: string; relations: AssetRelations; kinds: RelationKind[]; assets: AssetOption[]; canEdit: boolean; onChanged: () => void }) {
  const [kind, setKind] = useState(kinds[0]?.id ?? "controls");
  const [target, setTarget] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const options = useMemo(() => assets.filter((item) => item.asset_id !== assetId), [assets, assetId]);
  async function add(event: FormEvent) {
    event.preventDefault();
    const typed = target.trim();
    const found = options.find((item) => item.asset_id === typed) ?? options.find((item) => item.name.toLowerCase() === typed.toLowerCase());
    setBusy(true);
    try {
      await modelApi.addRelation(assetId, kind, found?.asset_id ?? typed);
      setTarget("");
      setError("");
      onChanged();
    } catch (err) {
      setError(message(err, t("Couldn't complete the operation.")));
    } finally {
      setBusy(false);
    }
  }
  async function remove(type: string, to: string) {
    try { await modelApi.removeRelation(assetId, type, to); onChanged(); } catch (err) { setError(message(err, t("Couldn't complete the operation."))); }
  }
  const empty = !relations.outgoing.length && !relations.incoming.length;
  return <div className="as-relations">
    {error && <div className="form-error"><AlertTriangle size={14} /> {error}</div>}
    <ul>
      {relations.outgoing.map((item) => <li key={`o-${item.type}-${item.asset.asset_id}`}><ArrowUpRight size={14} className="as-rel-out" /><span className="as-rel-label">{item.label}</span><Go to={assetPath(item.asset.asset_id)}><strong>{item.asset.asset_id}</strong>{item.asset.name !== item.asset.asset_id && <small>{item.asset.name}</small>}</Go>{canEdit && <button type="button" className="icon-button" aria-label={t("Remove relation")} onClick={() => void remove(item.type, item.asset.asset_id)}><X size={13} /></button>}</li>)}
      {relations.incoming.map((item) => <li key={`i-${item.type}-${item.asset.asset_id}`}><ArrowDownLeft size={14} className="as-rel-in" /><span className="as-rel-label">{item.label}</span><Go to={assetPath(item.asset.asset_id)}><strong>{item.asset.asset_id}</strong>{item.asset.name !== item.asset.asset_id && <small>{item.asset.name}</small>}</Go></li>)}
    </ul>
    {empty && <p className="muted">{t("No relations yet: a loop controls a valve, a transmitter measures a pump.")}</p>}
    {canEdit && <form className="as-rel-form" onSubmit={add}>
      <select aria-label={t("Relation")} value={kind} onChange={(event) => setKind(event.target.value)}>{kinds.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
      <input aria-label={t("Related asset")} list={`rel-${assetId}`} value={target} maxLength={200} placeholder={t("Asset tag or name")} onChange={(event) => setTarget(event.target.value)} />
      <datalist id={`rel-${assetId}`}>{options.slice(0, 500).map((item) => <option key={item.asset_id} value={item.asset_id}>{item.name}</option>)}</datalist>
      <button className="button button-secondary" disabled={busy || !target.trim()}><Plus size={14} /> {t("Add")}</button>
    </form>}
  </div>;
}
