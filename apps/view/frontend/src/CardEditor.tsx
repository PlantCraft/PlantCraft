/** The card editor (round 7, after Grafana's panel editor): pick the kind first, then a full
 * screen with the card's preview on top, its signals under it and its options on the side, in
 * groups that open and close and a search over them. "Visualization" changes the kind and keeps
 * what still applies. */
import { BarChart3, ChevronDown, Gauge, LineChart, Plus, ScatterChart, Search, Table2, Trash2, Type, Workflow, X, Hash } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { api } from "./api";
import { diagramsApi } from "./diagrams/api";
import type { DiagramSummary } from "./diagrams/model";
import { CardBody } from "./CardView";
import { colorOf, levelLabel, LEVELS, optionsOf, PALETTE, sortedSteps } from "./fields";
import { t } from "./i18n";
import { AGG_LABELS, ALL_ROLES, cardPixels, cardTitle, defaultCard, HEIGHTS, itemMode, KIND_HINTS, KIND_LABELS, KINDS, maxItemsOf, minHeight, NO_ITEM_KINDS, type Mode, resultLabel, variableOf, VALUE_KINDS, WIDTHS, WINDOWS, windowLabel } from "./model";
import type { Aggregation, AssetKind, AssetOption, Card, CardData, CardItem, CardOptions, FieldConfig, Kind, Level, Mapping, Override, Page, ResultKind, SignalOption, Step, TableColumn, Thresholds, Variable } from "./types";

const KIND_ICONS: Record<Kind, typeof Gauge> = { stat: Hash, gauge: Gauge, trend: LineChart, bar: BarChart3, table: Table2, scatter: ScatterChart, text: Type, diagram: Workflow };

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

/** Search answers with the numbers first: a trend draws them, a text signal (a mode) has no line. */
export function rankSignals(found: SignalOption[]): SignalOption[] {
  return [...found].sort((a, b) => Number(a.kind === "text") - Number(b.kind === "text"));
}

/** A signal by tag or name; with `onText`, what is typed counts too (a signal id with `${var}`). */
export function SignalSearch({ value, onPick, onText }: { value: string; onPick: (signal: SignalOption) => void; onText?: (text: string) => void }) {
  const [q, setQ] = useState(value);
  const [found, setFound] = useState<SignalOption[]>([]);
  useEffect(() => {
    if (q.includes("$")) { setFound([]); return; }
    const timer = window.setTimeout(() => { api.signals(q).then((answer) => setFound(rankSignals(answer))).catch(() => setFound([])); }, 200);
    return () => window.clearTimeout(timer);
  }, [q]);
  return <div className="tc-search">
    <input aria-label={t("Search signals")} placeholder={t("Search signals by tag or name")} value={q} onChange={(event) => { setQ(event.target.value); onText?.(event.target.value); }} />
    {q !== value && found.length > 0 && <ul role="listbox">{found.slice(0, 12).map((signal) => <li key={signal.id}><button type="button" onClick={() => { setQ(signal.id); onPick(signal); }}><b>{signal.id}</b><small>{signal.name}{signal.unit ? ` · ${signal.unit}` : ""}{signal.kind === "text" ? ` · ${t("text")}` : ""}</small></button></li>)}</ul>}
  </div>;
}

// The options pane's search: an option whose words do not hold it is hidden, and so is a group
// left without options (CSS :has).
const SearchContext = createContext("");

function Opt({ label, hint, wide, children, words = "" }: { label: string; hint?: string; wide?: boolean; children: ReactNode; words?: string }) {
  const q = useContext(SearchContext).trim().toLowerCase();
  const hidden = Boolean(q) && !`${label} ${hint ?? ""} ${words}`.toLowerCase().includes(q);
  return <div className={`tc-opt${wide ? " tc-opt-wide" : ""}`} hidden={hidden}>
    <span className="tc-opt-label">{label}</span>
    {children}
    {hint && <small>{hint}</small>}
  </div>;
}

function Group({ title, children, open: initial = true, count }: { title: string; children: ReactNode; open?: boolean; count?: number }) {
  const q = useContext(SearchContext).trim();
  const [open, setOpen] = useState(initial);
  const shown = open || Boolean(q);
  return <section className={`tc-group${shown ? " tc-group-open" : ""}`}>
    <button type="button" className="tc-group-head" aria-expanded={shown} onClick={() => setOpen(!open)}>
      <ChevronDown size={15} /><span>{title}</span>{count ? <small className="tag">{count}</small> : null}
    </button>
    <div className="tc-group-body" hidden={!shown}>{children}</div>
  </section>;
}

function numberOrNull(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text.replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

/** A number typed freely (a minus sign, a comma) and kept when it is one. */
function NumberInput({ value, onChange, placeholder, label }: { value: number | null | undefined; onChange: (value: number | null) => void; placeholder?: string; label: string }) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => {
    if (numberOrNull(text) !== (value ?? null)) setText(value === null || value === undefined ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return <input aria-label={label} inputMode="decimal" value={text} placeholder={placeholder ?? t("Automatic")} onChange={(event) => { setText(event.target.value); onChange(numberOrNull(event.target.value)); }} />;
}

/** A colour: one of the palette's, the level's (`allowLevel`), or any other. */
function ColorPick({ value, onChange, allowLevel, label, automatic }: { value: string | null | undefined; onChange: (value: string) => void; allowLevel?: boolean; label: string; automatic?: string }) {
  const custom = Boolean(value && value.startsWith("#"));
  return <span className="tc-color">
    <i className="tc-swatch" style={{ background: value ? colorOf(value) : "transparent" }} aria-hidden="true" />
    <select aria-label={label} value={custom ? "#" : value ?? ""} onChange={(event) => onChange(event.target.value === "#" ? colorOf(value || "blue") : event.target.value)}>
      <option value="">{allowLevel ? t("The level's colour") : automatic ?? t("Automatic")}</option>
      {PALETTE.map((name) => <option key={name} value={name}>{t(name.charAt(0).toUpperCase() + name.slice(1))}</option>)}
      <option value="#">{t("Other…")}</option>
    </select>
    {custom && <input type="color" aria-label={t("Other colour")} value={value!} onChange={(event) => onChange(event.target.value)} />}
  </span>;
}

function Select<T extends string>({ value, options, onChange, label }: { value: T; options: Array<[T, string]>; onChange: (value: T) => void; label: string }) {
  return <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value as T)}>{options.map(([key, words]) => <option key={key} value={key}>{words}</option>)}</select>;
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <label className="tc-toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>;
}

/** Threshold steps, highest first (as Grafana lists them): colour, level, from which value. */
export function ThresholdsEditor({ value, onChange, lines }: { value: Thresholds | null | undefined; onChange: (value: Thresholds | null) => void; lines: boolean }) {
  const thresholds: Thresholds = value ?? { mode: "absolute", steps: [{ level: "ok" }], show: "lines" };
  const steps = sortedSteps(thresholds.steps);
  const set = (next: Partial<Thresholds>) => onChange({ ...thresholds, ...next });
  const setStep = (index: number, step: Step) => set({ steps: steps.map((old, n) => (n === index ? step : old)) });
  const add = () => {
    const top = steps.filter((step) => typeof step.value === "number").map((step) => step.value as number);
    const next = top.length ? Math.max(...top) + 10 : thresholds.mode === "percentage" ? 80 : 80;
    set({ steps: [...steps, { value: next, level: steps.length === 1 ? "warning" : "alarm" }] });
  };
  return <div className="tc-steps">
    <div className="tc-inline">
      <Select label={t("Threshold mode")} value={thresholds.mode ?? "absolute"} onChange={(mode) => set({ mode })} options={[["absolute", t("Absolute values")], ["percentage", t("Percent of min to max")]]} />
      {lines && <Select label={t("Show thresholds")} value={thresholds.show ?? "lines"} onChange={(show) => set({ show })} options={[["off", t("Not drawn")], ["lines", t("As lines")], ["area", t("As areas")], ["lines+area", t("Lines and areas")]]} />}
    </div>
    <ol className="tc-step-list">
      {steps.map((step, index) => ({ step, index })).reverse().map(({ step, index }) => <li key={index} className="tc-step">
        <ColorPick label={t("Colour")} allowLevel value={step.color ?? ""} onChange={(color) => setStep(index, { ...step, color })} />
        <Select<Level> label={t("Level")} value={step.level ?? "ok"} onChange={(level) => setStep(index, { ...step, level })} options={LEVELS.map((level) => [level, t(levelLabel(level))])} />
        {typeof step.value === "number"
          ? <><span className="tc-step-from">{t("from")}</span><NumberInput label={t("From value")} value={step.value} placeholder="0" onChange={(next) => setStep(index, { ...step, value: next ?? 0 })} />{thresholds.mode === "percentage" && <span>%</span>}
            <button type="button" className="icon-button" aria-label={t("Remove threshold")} title={t("Remove threshold")} onClick={() => set({ steps: steps.filter((_, n) => n !== index) })}><Trash2 size={14} /></button></>
          : <span className="tc-step-from muted">{t("Base: below every other")}</span>}
      </li>)}
    </ol>
    <div className="tc-inline">
      <button type="button" className="button button-secondary button-small" onClick={add} disabled={steps.length >= 20}><Plus size={14} /> {t("Add threshold")}</button>
      {value && <button type="button" className="button button-secondary button-small" onClick={() => onChange(null)}>{t("Remove all")}</button>}
    </div>
  </div>;
}

/** Value mappings: a value, a range or a text shown as words, a colour and a state. */
export function MappingsEditor({ value, onChange }: { value: Mapping[] | null | undefined; onChange: (value: Mapping[] | null) => void }) {
  const items = value ?? [];
  const setItem = (index: number, next: Mapping) => onChange(items.map((old, n) => (n === index ? next : old)));
  return <div className="tc-mappings">
    {items.map((item, index) => <div key={index} className="tc-mapping">
      <Select label={t("Mapping type")} value={item.type} onChange={(type) => setItem(index, { ...item, type })} options={[["value", t("Value")], ["range", t("Range")], ["text", t("Text")]]} />
      {item.type === "range"
        ? <><NumberInput label={t("From")} placeholder={t("From")} value={item.low} onChange={(low) => setItem(index, { ...item, low })} /><NumberInput label={t("To")} placeholder={t("To")} value={item.high} onChange={(high) => setItem(index, { ...item, high })} /></>
        : <input aria-label={t("Value")} placeholder={item.type === "text" ? t("Text, like OPEN") : t("Value, like 1")} maxLength={60} value={item.value ?? ""} onChange={(event) => setItem(index, { ...item, value: event.target.value })} />}
      <input aria-label={t("Shown as")} placeholder={t("Shown as")} maxLength={40} value={item.text ?? ""} onChange={(event) => setItem(index, { ...item, text: event.target.value })} />
      <ColorPick label={t("Colour")} value={item.color ?? ""} automatic={t("No colour")} onChange={(color) => setItem(index, { ...item, color })} />
      <Select label={t("State")} value={item.level ?? ""} onChange={(level) => setItem(index, { ...item, level })} options={[["", t("No state")], ["ok", t("Normal")], ["warning", t("Warning")], ["alarm", t("Critical")]]} />
      <button type="button" className="icon-button" aria-label={t("Remove mapping")} title={t("Remove mapping")} onClick={() => onChange(items.length > 1 ? items.filter((_, n) => n !== index) : null)}><Trash2 size={14} /></button>
    </div>)}
    <button type="button" className="button button-secondary button-small" disabled={items.length >= 30} onClick={() => onChange([...items, { type: "value", value: "", text: "", color: "", level: "" }])}><Plus size={14} /> {t("Add mapping")}</button>
  </div>;
}

type FieldKey = keyof FieldConfig;
const FIELD_LABELS: Record<FieldKey, string> = {
  unit: "Unit", min: "Min", max: "Max", decimals: "Decimals", display_name: "Display name", no_value: "No value",
  color_mode: "Colour scheme", color: "Colour", thresholds: "Thresholds", mappings: "Value mappings",
  draw: "Draw as", interpolation: "Line interpolation", line_width: "Line width", dash: "Line style", fill: "Fill opacity", axis: "Axis placement",
  normal_low: "Normal range from", normal_high: "Normal range to",
};
const STYLE_KEYS: FieldKey[] = ["draw", "interpolation", "line_width", "dash", "fill", "axis"];

/** The editor of one field option (shared by the card's options and its overrides). */
function FieldInput({ name, config, onChange, lines }: { name: FieldKey; config: FieldConfig; onChange: (config: FieldConfig) => void; lines: boolean }) {
  const label = t(FIELD_LABELS[name]);
  const set = (value: unknown) => onChange({ ...config, [name]: value === "" || value === undefined ? null : value });
  switch (name) {
    case "unit": case "display_name": case "no_value":
      return <input aria-label={label} maxLength={name === "display_name" ? 80 : 20} value={(config[name] as string | null) ?? ""} placeholder={name === "unit" ? t("From the signal") : name === "no_value" ? "—" : t("From the signal")} onChange={(event) => set(event.target.value)} />;
    case "normal_low": case "normal_high":
      return <NumberInput label={label} value={config[name] as number | null} onChange={(value) => set(value)} placeholder={t("From the thresholds")} />;
    case "min": case "max": case "fill": case "line_width":
      return <NumberInput label={label} value={config[name] as number | null} onChange={(value) => set(value)} placeholder={name === "min" || name === "max" ? t("From the signal's range") : t("Automatic")} />;
    case "decimals":
      return <select aria-label={label} value={config.decimals ?? ""} onChange={(event) => set(event.target.value === "" ? null : Number(event.target.value))}><option value="">{t("Automatic")}</option>{[0, 1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}</select>;
    case "color_mode":
      return <Select label={label} value={config.color_mode ?? ""} onChange={(value) => set(value)} options={[["", t("Automatic")], ["thresholds", t("From thresholds")], ["fixed", t("One colour")], ["palette", t("Palette (one per signal)")]]} />;
    case "color":
      return <ColorPick label={label} value={config.color ?? ""} onChange={(value) => set(value)} />;
    case "draw":
      return <Select label={label} value={config.draw ?? ""} onChange={(value) => set(value)} options={[["", t("Automatic")], ["lines", t("Lines")], ["points", t("Points")], ["lines+points", t("Lines and points")], ["bars", t("Bars")]]} />;
    case "interpolation":
      return <Select label={label} value={config.interpolation ?? ""} onChange={(value) => set(value)} options={[["", t("Automatic")], ["linear", t("Linear")], ["smooth", t("Smooth")], ["step", t("Step")]]} />;
    case "dash":
      return <Select label={label} value={config.dash ?? ""} onChange={(value) => set(value)} options={[["", t("Automatic")], ["solid", t("Solid")], ["dash", t("Dashes")], ["dot", t("Dots")], ["dashdot", t("Dash dot")]]} />;
    case "axis":
      return <Select label={label} value={config.axis ?? ""} onChange={(value) => set(value)} options={[["", t("Automatic")], ["left", t("Left")], ["right", t("Right")], ["hidden", t("Hidden")]]} />;
    case "thresholds":
      return <ThresholdsEditor value={config.thresholds} lines={lines} onChange={(value) => set(value)} />;
    case "mappings":
      return <MappingsEditor value={config.mappings} onChange={(value) => set(value)} />;
  }
}

/** Overrides: options for the signals a rule matches (a role, a signal id or a name, with *). */
function OverridesEditor({ card, onChange, keys }: { card: Card; onChange: (overrides: Override[]) => void; keys: FieldKey[] }) {
  const items = card.overrides ?? [];
  const setItem = (index: number, next: Override) => onChange(items.map((old, n) => (n === index ? next : old)));
  return <div className="tc-overrides">
    {items.map((item, index) => {
      const used = (Object.keys(item.field) as FieldKey[]).filter((key) => item.field[key] !== null && item.field[key] !== undefined);
      return <div key={index} className="tc-override">
        <div className="tc-inline">
          <b>{t("Signals whose")}</b>
          <Select label={t("Match by")} value={item.match.by} onChange={(by) => setItem(index, { ...item, match: { ...item.match, by } })} options={[["role", t("role is")], ["signal", t("signal id matches")], ["name", t("name matches")]]} />
          <input aria-label={t("Match value")} maxLength={120} placeholder={item.match.by === "role" ? "sp" : item.match.by === "signal" ? "FIC-*" : t("Flow*")} value={item.match.value} onChange={(event) => setItem(index, { ...item, match: { ...item.match, value: event.target.value } })} />
          <button type="button" className="icon-button" aria-label={t("Remove override")} title={t("Remove override")} onClick={() => onChange(items.filter((_, n) => n !== index))}><Trash2 size={14} /></button>
        </div>
        {used.map((key) => <div key={key} className="tc-override-prop">
          <span className="tc-opt-label">{t(FIELD_LABELS[key])}</span>
          <FieldInput name={key} config={item.field} lines={card.kind === "trend" || card.kind === "bar"} onChange={(field) => setItem(index, { ...item, field })} />
          <button type="button" className="icon-button" aria-label={t("Remove property")} title={t("Remove property")} onClick={() => { const field = { ...item.field }; delete field[key]; setItem(index, { ...item, field }); }}><X size={14} /></button>
        </div>)}
        <select aria-label={t("Add a property")} value="" onChange={(event) => {
          const key = event.target.value as FieldKey;
          const start: Partial<FieldConfig> = key === "thresholds" ? { thresholds: { mode: "absolute", steps: [{ level: "ok" }, { value: 80, level: "alarm" }], show: "lines" } } : key === "mappings" ? { mappings: [{ type: "value", value: "", text: "" }] } : key === "color" ? { color: "red", color_mode: "fixed" } : key === "line_width" ? { line_width: 2 } : key === "dash" ? { dash: "dash" } : key === "axis" ? { axis: "right" } : { [key]: key === "decimals" ? 1 : key === "draw" ? "lines" : key === "interpolation" ? "linear" : key === "fill" ? 20 : "" };
          setItem(index, { ...item, field: { ...item.field, ...start } as FieldConfig });
        }}>
          <option value="">{t("+ Add a property")}</option>
          {keys.filter((key) => !used.includes(key)).map((key) => <option key={key} value={key}>{t(FIELD_LABELS[key])}</option>)}
        </select>
      </div>;
    })}
    <button type="button" className="button button-secondary button-small" disabled={items.length >= 20} onClick={() => onChange([...items, { match: { by: "role", value: "" }, field: {} }])}><Plus size={14} /> {t("Add override")}</button>
  </div>;
}

/** One signal of the card: from a dashboard variable, a fixed asset, or a signal id. */
function ItemRow({ item, index, variables, kinds, assets, results, onChange, onRemove }: {
  item: CardItem; index: number; variables: Variable[]; kinds: AssetKind[]; assets: AssetOption[];
  results: string[]; onChange: (item: CardItem) => void; onRemove?: () => void;
}) {
  const mode = itemMode(item);
  const assetVariables = variables.filter((variable) => variable.type === "asset");
  const variable = assetVariables.find((found) => found.name === variableOf(item.asset_id));
  const asset = assets.find((option) => option.id === item.asset_id);
  const roles = mode === "variable" ? kinds.find((kind) => kind.kind === variable?.asset_kind)?.roles ?? [] : Object.keys(asset?.signals ?? {});
  const every = item.role === ALL_ROLES;
  const setMode = (next: Mode) => {
    if (next === "signal") onChange({ label: item.label, signal_id: "" });
    else if (next === "variable") {
      const first = assetVariables[0];
      onChange({ label: item.label, asset_id: `$${first?.name ?? "asset"}`, role: ALL_ROLES, roles: [] });
    } else {
      const first = assets.find((option) => Object.keys(option.signals).length);
      onChange({ label: item.label, asset_id: first?.id ?? "", role: ALL_ROLES, roles: [] });
    }
  };
  return <div className="tc-item" data-item={index}>
    <div className="tc-item-head">
      <b className="tc-item-letter">{String.fromCharCode(65 + index)}</b>
      <div className="pc-segmented" role="group" aria-label={t("Where the signal comes from")}>
        {assetVariables.length > 0 && <button type="button" className={mode === "variable" ? "on" : ""} onClick={() => setMode("variable")}>{t("Variable")}</button>}
        <button type="button" className={mode === "asset" ? "on" : ""} onClick={() => setMode("asset")}>{t("Asset")}</button>
        <button type="button" className={mode === "signal" ? "on" : ""} onClick={() => setMode("signal")}>{t("Signal")}</button>
      </div>
      {onRemove && <button type="button" className="icon-button" aria-label={t("Remove signal")} title={t("Remove signal")} onClick={onRemove}><Trash2 size={15} /></button>}
    </div>
    <div className="tc-item-fields">
      {mode === "variable" && <label>{t("Variable")}<select value={variable?.name ?? ""} onChange={(event) => onChange({ ...item, asset_id: `$${event.target.value}` })}>
        {!variable && <option value="">{item.asset_id}</option>}
        {assetVariables.map((found) => <option key={found.name} value={found.name}>${found.name}{found.label ? ` · ${found.label}` : ""} ({found.asset_kind})</option>)}
      </select></label>}
      {mode === "asset" && <label>{t("Asset")}<select value={item.asset_id ?? ""} onChange={(event) => {
        const picked = assets.find((option) => option.id === event.target.value);
        const keep = item.role === ALL_ROLES || (picked && item.role && picked.signals[item.role]) ? item.role : Object.keys(picked?.signals ?? {})[0] ?? "";
        onChange(item.result ? { ...item, asset_id: event.target.value } : { ...item, asset_id: event.target.value, role: keep });
      }}>
        {!asset && <option value={item.asset_id ?? ""}>{item.asset_id || t("Choose an asset")}</option>}
        {assets.filter((option) => Object.keys(option.signals).length).map((option) => <option key={option.id} value={option.id}>{option.parent ? `${option.parent} / ` : ""}{option.name} ({option.kind})</option>)}
      </select></label>}
      {mode !== "signal" && <label>{t("Shows")}<select value={item.result ? `result:${item.result}` : `role:${item.role ?? ""}`} onChange={(event) => {
        const at = event.target.value.indexOf(":");
        const [what, value] = [event.target.value.slice(0, at), event.target.value.slice(at + 1)];
        onChange(what === "result" ? { label: item.label, asset_id: item.asset_id, result: value } : { label: item.label, asset_id: item.asset_id, role: value, ...(value === ALL_ROLES ? { roles: [] } : {}) });
      }}>
        <option value={`role:${ALL_ROLES}`}>{t("Every signal of the asset")}</option>
        {!item.result && item.role && item.role !== ALL_ROLES && !roles.includes(item.role) && <option value={`role:${item.role}`}>{item.role.toUpperCase()}</option>}
        <optgroup label={t("One signal, by role")}>{roles.map((role) => <option key={role} value={`role:${role}`}>{role.toUpperCase()}{asset ? ` · ${asset.signals[role]}` : ""}</option>)}</optgroup>
        {(results.length > 0 || item.result) && <optgroup label={t("Result of another app")}>
          {item.result && !results.includes(item.result) && <option value={`result:${item.result}`}>{resultLabel(item.result)}</option>}
          {results.map((name) => <option key={name} value={`result:${name}`}>{resultLabel(name)}</option>)}
        </optgroup>}
      </select></label>}
      {mode === "signal" && <label className="tc-grow">{t("Signal")}<SignalSearch value={item.signal_id ?? ""} onPick={(signal) => onChange({ ...item, signal_id: signal.id })} onText={(text) => { if (text.includes("$")) onChange({ ...item, signal_id: text }); }} /></label>}
      {!every && <label>{t("Label")}<input value={item.label ?? ""} maxLength={80} placeholder={t("Automatic")} onChange={(event) => onChange({ ...item, label: event.target.value })} /></label>}
    </div>
    {every && mode !== "signal" && roles.length > 0 && <div className="tc-roles" role="group" aria-label={t("Roles shown")}>
      <small>{t("Only these roles (none ticked: all of them):")}</small>
      {roles.map((role) => <Toggle key={role} label={role.toUpperCase()} checked={(item.roles ?? []).includes(role)} onChange={(on) => onChange({ ...item, roles: on ? [...(item.roles ?? []), role] : (item.roles ?? []).filter((found) => found !== role) })} />)}
    </div>}
  </div>;
}

/** The first step of a new card, and the "Visualization" button's list. */
function KindPicker({ value, onPick, onClose, kinds = KINDS }: { value?: Kind; onPick: (kind: Kind) => void; onClose?: () => void; kinds?: readonly Kind[] }) {
  return <div className="tc-kind-picker">
    <header><h3>{t("Choose a visualization")}</h3>{onClose && <button type="button" className="icon-button" aria-label={t("Close")} onClick={onClose}><X size={16} /></button>}</header>
    <div className="tc-kinds" role="radiogroup" aria-label={t("Panel type")}>
      {kinds.map((kind) => {
        const Icon = KIND_ICONS[kind];
        return <button type="button" role="radio" aria-checked={value === kind} key={kind} className={value === kind ? "on" : ""} onClick={() => onPick(kind)}><Icon size={22} /><b>{t(KIND_LABELS[kind])}</b><small>{t(KIND_HINTS[kind])}</small></button>;
      })}
    </div>
  </div>;
}

/** A card turned into another kind: what still applies is kept (Grafana's "change visualization"). */
export function changeKind(current: Card, kind: Kind): Card {
  const old = defaultCard(current.kind, []);
  const fresh = defaultCard(kind, []);
  return {
    ...current, kind,
    window: current.window === old.window ? fresh.window : current.window,
    items: current.items.slice(0, maxItemsOf(kind)),
    text: kind === "text" ? current.text ?? "" : current.text,
    diagram_id: kind === "diagram" ? current.diagram_id ?? "" : current.diagram_id,
    height: current.height === old.height ? fresh.height : Math.max(minHeight(kind), current.height),
    width: current.width === old.width ? fresh.width : current.width,
  };
}

const COLUMN_WORDS: Record<TableColumn, string> = { last: "Last", mean: "Mean", min: "Min", max: "Max", std: "Std dev", unit: "Unit", time: "Time", state: "State" };

export function CardEditor({ initial, isNew = false, variables = [], values = {}, texts = {}, pages = [], period, onSave, onClose }: {
  initial: Card; isNew?: boolean; variables?: Variable[]; values?: Record<string, string[]>; texts?: Record<string, string[]>;
  pages?: Page[];
  /** A report's card: it reads the report's period (no window of its own), has no layout on a
   * grid and no text kind (a report writes notes in text sections). */
  period?: string;
  onSave: (card: Card) => void; onClose: () => void;
}) {
  const inReport = period !== undefined;
  const [card, setCard] = useState<Card>(initial);
  const [picking, setPicking] = useState(isNew);
  // A new card's first pick starts it; a later one (the "Visualization" button) changes its kind.
  const [fresh, setFresh] = useState(isNew);
  const [kinds, setKinds] = useState<AssetKind[]>([]);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [results, setResults] = useState<ResultKind[]>([]);
  const [preview, setPreview] = useState<CardData | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [q, setQ] = useState("");
  const [diagrams, setDiagrams] = useState<DiagramSummary[] | null>(null);
  const isDiagram = card.kind === "diagram";
  useEffect(() => {
    if (isDiagram && diagrams === null) diagramsApi.list().then(setDiagrams).catch((err) => { setDiagrams([]); setLoadError(message(err)); });
  }, [isDiagram, diagrams]);
  useEffect(() => {
    Promise.all([api.assetKinds(), api.assets()]).then(([k, a]) => { setKinds(k); setAssets(a); }).catch((err) => setLoadError(message(err)));
    // App results are optional: no producer installed is an empty list, not an error.
    api.resultKinds().then(setResults).catch(() => setResults([]));
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && !picking) onClose(); };
    globalThis.addEventListener("keydown", close);
    return () => globalThis.removeEventListener("keydown", close);
  }, [onClose, picking]);
  const assetVariable = variables.find((variable) => variable.type === "asset");
  // A new card starts with one item: every signal of the dashboard's first asset variable, else of an asset.
  useEffect(() => {
    const withSignals = assets.find((asset) => Object.keys(asset.signals).length);
    if (picking || card.items.length || NO_ITEM_KINDS.includes(card.kind) || (!assetVariable && !withSignals)) return;
    // Charts and tables start with every signal of the asset; a number or a dial with one.
    const every = ["trend", "bar", "table"].includes(card.kind);
    const firstRole = assetVariable ? kinds.find((kind) => kind.kind === assetVariable.asset_kind)?.roles[0] ?? "pv" : Object.keys(withSignals!.signals)[0];
    const first: CardItem = { asset_id: assetVariable ? `$${assetVariable.name}` : withSignals!.id, role: every ? ALL_ROLES : firstRole, roles: [], label: "" };
    setCard((current) => ({ ...current, items: [first] }));
  }, [assets, kinds, assetVariable, card.items.length, card.kind, picking]);
  const text = card.kind === "text";
  // Text and diagram panels show no signal: no field, threshold, mapping or override options.
  const noItems = NO_ITEM_KINDS.includes(card.kind);
  const complete = text ? Boolean(card.text?.trim()) : isDiagram ? Boolean(card.diagram_id) : card.items.length > 0 && (card.kind !== "scatter" || card.items.length === 2) && card.items.every((item) => (item.signal_id ? true : Boolean(item.asset_id && (item.role || item.result))));
  const previewKey = JSON.stringify({ ...card, x: 0, y: 0, title: "", description: "" });
  const valuesKey = JSON.stringify(values);
  useEffect(() => {
    if (!complete || text || picking) { setPreview(null); return; }
    const timer = window.setTimeout(() => {
      api.preview(card, variables, values, period ?? null).then((data) => { setPreview(data); setPreviewError(""); }).catch((err) => { setPreview(null); setPreviewError(message(err)); });
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey, valuesKey, complete, picking]);

  const set = <K extends keyof Card>(key: K, value: Card[K]) => setCard((current) => ({ ...current, [key]: value }));
  const options = optionsOf(card);
  const setOption = <K extends keyof CardOptions>(key: K, value: CardOptions[K]) => setCard((current) => ({ ...current, options: { ...current.options, [key]: value } }));
  const field = card.field ?? {};
  const setField = (next: FieldConfig) => set("field", next);
  const maxItems = maxItemsOf(card.kind);
  const intervals = variables.filter((variable) => variable.type === "interval");
  const windowOptions = useMemo(() => {
    const listed = [...WINDOWS, ...intervals.map((variable) => `$${variable.name}`)];
    return listed.includes(card.window) ? listed : [card.window, ...listed];
  }, [card.window, intervals]);
  const resultNames = results.filter((item) => (card.kind === "trend" ? item.history > 0 : item.count > 0)).map((item) => item.result);
  const kind = card.kind;
  const charted = kind === "trend" || kind === "bar";
  const keys: FieldKey[] = ["unit", "min", "max", "decimals", "display_name", "no_value", "color_mode", "color", "thresholds", "mappings", ...(kind === "trend" ? STYLE_KEYS : [])];

  if (picking) return <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={t("New panel")}>
    <div className="dialog tc-editor-pick">
      <KindPicker kinds={inReport ? KINDS.filter((kind) => !NO_ITEM_KINDS.includes(kind)) : KINDS} value={fresh ? undefined : card.kind} onClose={fresh ? onClose : () => setPicking(false)} onPick={(next) => { setCard((current) => (fresh ? { ...defaultCard(next, []), card_id: current.card_id, page_id: current.page_id } : changeKind(current, next))); setFresh(false); setPicking(false); }} />
    </div>
  </div>;

  const KindIcon = KIND_ICONS[kind];
  return <div className="tc-editor-screen" role="dialog" aria-modal="true" aria-label={isNew ? t("New panel") : t("Edit panel")}>
    <form className="tc-editor" onSubmit={(event) => { event.preventDefault(); if (complete) onSave(card); }}>
      <header className="tc-editor-head">
        <h2>{isNew ? t("New panel") : t("Edit panel")}</h2>
        <button type="button" className="button button-secondary" onClick={() => setPicking(true)} title={t("Change the type of panel; what still applies is kept.")}><KindIcon size={15} /> {t(KIND_LABELS[kind])} <ChevronDown size={14} /></button>
        <span className="tc-editor-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>{t("Discard")}</button>
          <button type="submit" className="button button-primary" disabled={!complete}>{t("Apply")}</button>
        </span>
      </header>
      {loadError && <div className="notice notice-error">{loadError}</div>}
      <div className="tc-editor-main">
        <div className="tc-editor-left">
          <div className="tc-editor-preview">
            <article className={`tc-card tc-preview${card.height === 1 ? " tc-h1" : ""}`} style={{ "--tc-px": `${cardPixels(card.height)}px`, width: `min(100%, ${Math.round((card.width / 12) * 100)}% + 240px)` } as CSSProperties} data-kind={kind}>
              <header><h2>{cardTitle(card, texts) || t(KIND_LABELS[kind])}</h2><span className="tc-card-meta">{!["stat", "gauge", "text"].includes(kind) && <small>{windowLabel(period ?? (card.window.startsWith("$") ? values[card.window.slice(1)]?.[0] ?? card.window : card.window))}</small>}</span></header>
              <div className="tc-card-body">
                {text ? <CardBody card={card} data={{ card_id: card.card_id, kind: "text", window: card.window, read_at: "" }} texts={texts} />
                  : previewError ? <div className="tc-card-error">{previewError}</div>
                  : preview ? <CardBody card={card} data={preview} texts={texts} />
                  : <p className="muted">{isDiagram ? t("Choose the process display to see the panel.") : t("Choose the signals to see the panel.")}</p>}
              </div>
            </article>
          </div>
          <div className="tc-editor-data">
            {isDiagram ? <label className="tc-text-input">{t("Process display")}
                <select aria-label={t("Process display")} value={card.diagram_id ?? ""} onChange={(event) => set("diagram_id", event.target.value)}>
                  <option value="">{diagrams === null ? t("Loading…") : diagrams.length ? t("Choose a process display") : t("No process display yet: draw one in View › Process.")}</option>
                  {card.diagram_id && diagrams && !diagrams.some((item) => item.diagram_id === card.diagram_id) && <option value={card.diagram_id}>{t("Not available ({id})", { id: card.diagram_id })}</option>}
                  {(diagrams ?? []).map((item) => <option key={item.diagram_id} value={item.diagram_id}>{item.name}</option>)}
                </select>
                <small className="muted">{t("Shown live, scaled to the panel, with the dashboard's time window (else the panel's). Viewers who may not see the process display's folder see that it is not available.")}</small>
              </label>
              : text ? <label className="tc-text-input">{t("Text (Markdown; ${variable} is replaced by its value)")}<textarea rows={8} maxLength={2000} value={card.text ?? ""} onChange={(event) => set("text", event.target.value)} placeholder={t("What this dashboard is for, what to watch, who to call.")} /></label>
              : <>
                <h3>{kind === "scatter" ? t("Signals: x, then y") : t("Signals")} <small className="muted">{t("{n} of at most {max}", { n: card.items.length, max: maxItems })}</small></h3>
                {card.items.map((item, index) => <ItemRow key={index} item={item} index={index} variables={variables} kinds={kinds} assets={assets} results={resultNames}
                  onChange={(next) => set("items", card.items.map((old, i) => (i === index ? next : old)))}
                  onRemove={card.items.length > 1 ? () => set("items", card.items.filter((_, i) => i !== index)) : undefined} />)}
                {card.items.length < maxItems && <button type="button" className="button button-secondary" onClick={() => set("items", [...card.items, card.items[card.items.length - 1] ? { ...card.items[card.items.length - 1], label: "" } : { asset_id: assetVariable ? `$${assetVariable.name}` : "", role: ALL_ROLES }])}><Plus size={15} /> {t("Add a signal")}</button>}
              </>}
          </div>
        </div>
        <SearchContext.Provider value={q}>
          <aside className="tc-editor-options" aria-label={t("Panel options")}>
            <label className="tc-find tc-options-find"><Search size={15} /><input aria-label={t("Search options")} placeholder={t("Search options")} value={q} onChange={(event) => setQ(event.target.value)} /></label>
            <Group title={t("Panel")}>
              <Opt label={t("Title")} hint={t("Empty: what it shows. ${variable} is replaced by its value.")}><input value={card.title} maxLength={120} placeholder={cardTitle({ ...card, title: "" }, texts) || t("Automatic")} onChange={(event) => set("title", event.target.value)} /></Opt>
              <Opt label={t("Description")} hint={t("Shown when the pointer rests on the title.")}><textarea rows={2} maxLength={500} value={card.description ?? ""} onChange={(event) => set("description", event.target.value)} /></Opt>
              {VALUE_KINDS.includes(kind) && <Opt label={t("Value")} hint={t("What one number sums up of the window.")} words="aggregation calculation reduce"><select value={card.agg} onChange={(event) => set("agg", event.target.value as Aggregation)}>{(Object.keys(AGG_LABELS) as Aggregation[]).map((agg) => <option key={agg} value={agg}>{t(AGG_LABELS[agg])}</option>)}</select></Opt>}
              {!text && inReport && <Opt label={t("Period")} words="time window period interval" hint={t("Every panel of a report reads the report's period.")}><input aria-label={t("Period")} value={windowLabel(period ?? "")} readOnly /></Opt>}
              {!text && !inReport && <Opt label={charted || kind === "scatter" ? t("Time span") : t("Window")} words="time window period interval"><select value={card.window} onChange={(event) => set("window", event.target.value)}>{windowOptions.map((window) => <option key={window} value={window}>{window.startsWith("$") ? t("Variable {name}", { name: window }) : windowLabel(window)}</option>)}</select></Opt>}
            </Group>
            {kind === "stat" && <Group title={t("Stat")}>
              <Opt label={t("Graph")} words="sparkline area line"><Select value={options.graph} onChange={(value) => setOption("graph", value)} label={t("Graph")} options={[["none", t("None: the number only")], ["area", t("Its line over the window")]]} /></Opt>
              <Opt label={t("Colour")} words="color mode background"><Select value={options.color_by} onChange={(value) => setOption("color_by", value)} label={t("Colour")} options={[["value", t("The value")], ["background", t("The background")], ["none", t("None")]]} /></Opt>
              <Opt label={t("Layout")} words="orientation"><Select value={options.orientation} onChange={(value) => setOption("orientation", value)} label={t("Layout")} options={[["auto", t("Automatic")], ["horizontal", t("Side by side")], ["vertical", t("One under the other")]]} /></Opt>
              <Opt label={t("Names")}><Toggle label={t("Show each signal's name")} checked={options.show_name} onChange={(value) => setOption("show_name", value)} /></Opt>
            </Group>}
            {kind === "gauge" && <Group title={t("Gauge")}>
              <Opt label={t("Style")} words="isa-101 isa101 analog indicator bar dial" hint={t("Analog indicator (ISA-101): a grey bar with the normal range, the LL, L, H and HH limits from the thresholds and the setpoint (a signal of role SP of the same asset); the pointer takes a colour only out of normal.")}><Select value={options.gauge_style} onChange={(value) => setOption("gauge_style", value)} label={t("Style")} options={[["dial", t("Dial")], ["analog", t("Analog indicator (ISA-101)")]]} /></Opt>
              <Opt label={t("Layout")} words="orientation"><Select value={options.orientation} onChange={(value) => setOption("orientation", value)} label={t("Layout")} options={[["auto", t("Automatic")], ["horizontal", t("Side by side")], ["vertical", t("One under the other")]]} /></Opt>
              <Opt label={t("Threshold bands")} words="markers"><Toggle label={t("Colour the dial's threshold bands")} checked={options.threshold_markers} onChange={(value) => setOption("threshold_markers", value)} /></Opt>
              <Opt label={t("Threshold labels")}><Toggle label={t("Write each threshold's value")} checked={options.threshold_labels} onChange={(value) => setOption("threshold_labels", value)} /></Opt>
            </Group>}
            {kind === "bar" && <Group title={t("Bar chart")}>
              <Opt label={t("Style")} words="bar gauge"><Select value={options.bar_style} onChange={(value) => setOption("bar_style", value)} label={t("Style")} options={[["bars", t("Bars on axes")], ["gauge", t("Bar gauges (filled to the value)")]]} /></Opt>
              <Opt label={t("Orientation")} words="horizontal vertical"><Select value={options.orientation} onChange={(value) => setOption("orientation", value)} label={t("Orientation")} options={[["auto", t("Automatic")], ["horizontal", t("Horizontal")], ["vertical", t("Vertical")]]} /></Opt>
              <Opt label={t("Value labels")}><Select value={options.value_labels} onChange={(value) => setOption("value_labels", value)} label={t("Value labels")} options={[["auto", t("Automatic")], ["always", t("Always")], ["never", t("Never")]]} /></Opt>
              <Opt label={t("Sort")}><Select value={options.sort} onChange={(value) => setOption("sort", value)} label={t("Sort")} options={[["none", t("As listed")], ["asc", t("Smallest first")], ["desc", t("Largest first")]]} /></Opt>
              <Opt label={t("Axis label")} words="y label"><input maxLength={40} value={options.y_label} onChange={(event) => setOption("y_label", event.target.value)} /></Opt>
            </Group>}
            {kind === "trend" && <>
              <Group title={t("Legend")}>
                <Opt label={t("Mode")} words="legend"><Select value={options.legend} onChange={(value) => setOption("legend", value)} label={t("Legend mode")} options={[["list", t("List")], ["table", t("Table")], ["hidden", t("Hidden")]]} /></Opt>
                <Opt label={t("Placement")} words="legend"><Select value={options.legend_place} onChange={(value) => setOption("legend_place", value)} label={t("Legend placement")} options={[["bottom", t("Bottom")], ["right", t("Right")]]} /></Opt>
                <Opt label={t("Values")} words="legend last mean min max" hint={t("Shown beside each line's name.")}>
                  <span className="tc-checks">{(["last", "mean", "min", "max"] as const).map((value) => <Toggle key={value} label={t(COLUMN_WORDS[value])} checked={options.legend_values.includes(value)} onChange={(on) => setOption("legend_values", on ? [...options.legend_values, value] : options.legend_values.filter((found) => found !== value))} />)}</span>
                </Opt>
              </Group>
              <Group title={t("Axis")}>
                <Opt label={t("Label")} words="axis y"><input maxLength={40} value={options.y_label} onChange={(event) => setOption("y_label", event.target.value)} /></Opt>
                <Opt label={t("Scale")} words="log linear"><Select value={options.y_scale} onChange={(value) => setOption("y_scale", value)} label={t("Scale")} options={[["linear", t("Linear")], ["log", t("Logarithmic")]]} /></Opt>
                <Opt label={t("Soft min")} hint={t("The axis starts at least here, lower when a value is lower.")}><NumberInput label={t("Soft min")} value={options.soft_min} onChange={(value) => setOption("soft_min", value)} /></Opt>
                <Opt label={t("Soft max")} hint={t("The axis ends at least here, higher when a value is higher.")}><NumberInput label={t("Soft max")} value={options.soft_max} onChange={(value) => setOption("soft_max", value)} /></Opt>
              </Group>
              <Group title={t("Graph")}>
                <Opt label={t("Tooltip")} words="hover"><Select value={options.tooltip} onChange={(value) => setOption("tooltip", value)} label={t("Tooltip")} options={[["all", t("All lines")], ["single", t("The nearest line")], ["hidden", t("Hidden")]]} /></Opt>
                <Opt label={t("Stack")} words="stacking"><Select value={options.stack} onChange={(value) => setOption("stack", value)} label={t("Stack")} options={[["none", t("Off")], ["normal", t("Normal")], ["percent", t("100%")]]} /></Opt>
                <Opt label={t("Gaps")} words="connect null"><Toggle label={t("Join the line over missing samples")} checked={options.connect_gaps} onChange={(value) => setOption("connect_gaps", value)} /></Opt>
              </Group>
              <Group title={t("Graph styles")} open={false}>
                {STYLE_KEYS.map((key) => <Opt key={key} label={t(FIELD_LABELS[key])} words="line"><FieldInput name={key} config={field} onChange={setField} lines /></Opt>)}
              </Group>
            </>}
            {kind === "table" && <Group title={t("Table")}>
              <Opt label={t("Columns")} words="column">
                <span className="tc-checks">{(Object.keys(COLUMN_WORDS) as TableColumn[]).map((column) => <Toggle key={column} label={t(COLUMN_WORDS[column])} checked={options.columns.includes(column)} onChange={(on) => { const next = on ? [...options.columns, column] : options.columns.filter((found) => found !== column); if (next.length) setOption("columns", next); }} />)}</span>
              </Opt>
              <Opt label={t("Last value cell")} words="cell colour color background bar"><Select value={options.cell} onChange={(value) => setOption("cell", value)} label={t("Last value cell")} options={[["text", t("Plain")], ["color_text", t("Coloured text")], ["color_background", t("Coloured background")], ["bar", t("Bar gauge")]]} /></Opt>
              <Opt label={t("Rows")} words="row colour state alarm"><Toggle label={t("Colour a row in alarm or warning")} checked={options.row_color} onChange={(value) => setOption("row_color", value)} /></Opt>
            </Group>}
            {kind === "scatter" && <Group title={t("Scatter")}>
              <Opt label={t("Point size")}><NumberInput label={t("Point size")} value={options.point_size} onChange={(value) => setOption("point_size", Math.max(2, Math.min(20, Math.round(value ?? 5))))} /></Opt>
              <Opt label={t("Axis label")} words="y label"><input maxLength={40} value={options.y_label} onChange={(event) => setOption("y_label", event.target.value)} /></Opt>
            </Group>}
            {!noItems && <Group title={t("Standard options")}>
              {(["unit", "min", "max", "normal_low", "normal_high", "decimals", "display_name", "no_value", "color_mode", "color"] as FieldKey[]).filter((key) => kind !== "scatter" || ["unit", "decimals"].includes(key)).filter((key) => !key.startsWith("normal_") || kind === "gauge" || kind === "stat").map((key) => <Opt key={key} label={t(FIELD_LABELS[key])}
                hint={key === "normal_low" || key === "normal_high" ? t("Where the value should run: a darker band on the analog indicator and under a stat's line. Empty: between the thresholds' normal step and the next.") : key === "min" || key === "max" ? t("Of the dial, the bars and the axis; empty: the signal's range.") : key === "display_name" ? t("Instead of the signal's name (one signal; use overrides for several).") : key === "no_value" ? t("Shown when there is no value.") : undefined}>
                <FieldInput name={key} config={field} onChange={setField} lines={charted} />
              </Opt>)}
            </Group>}
            {!noItems && kind !== "scatter" && <Group title={t("Thresholds")} count={Math.max(0, (field.thresholds?.steps.length ?? 1) - 1)}>
              <Opt label={t("Steps")} wide words="thresholds limits alarm warning colour color" hint={t("A value from a step up takes its colour and level; alarm and warning also colour tables and stats.")}><ThresholdsEditor value={field.thresholds} lines={charted} onChange={(thresholds) => setField({ ...field, thresholds })} /></Opt>
            </Group>}
            {!noItems && ["stat", "gauge", "bar", "table"].includes(kind) && <Group title={t("Value mappings")} open={Boolean(field.mappings?.length)} count={field.mappings?.length}>
              <Opt label={t("Mappings")} wide words="mapping text value range" hint={t("Show a value, a range or a text as words, a colour and a state (1 as Open, 0 as Closed).")}><MappingsEditor value={field.mappings} onChange={(mappings) => setField({ ...field, mappings })} /></Opt>
            </Group>}
            {!noItems && kind !== "scatter" && <Group title={t("Overrides")} open={Boolean(card.overrides?.length)} count={card.overrides?.length}>
              <Opt label={t("Rules")} wide words="override role signal name" hint={t("Other options for some signals: the SP dashed, one signal on the right axis, its own thresholds.")}><OverridesEditor card={card} keys={keys} onChange={(overrides) => set("overrides", overrides)} /></Opt>
            </Group>}
            <Group title={t("Layout")} open={false}>
              {!inReport && <Opt label={t("Width")}><select value={card.width} onChange={(event) => set("width", Number(event.target.value))}>{WIDTHS.map((width) => <option key={width} value={width}>{t("{n} of 12 columns", { n: width })}</option>)}</select></Opt>}
              <Opt label={t("Height")}><select value={card.height} onChange={(event) => set("height", Number(event.target.value))}>{HEIGHTS.filter((rows) => rows >= minHeight(kind)).map((rows) => <option key={rows} value={rows}>{rows === 1 ? t("1 row") : t("{n} rows", { n: rows })}</option>)}</select></Opt>
              {pages.length > 1 && <Opt label={t("Page")}><select value={card.page_id ?? pages[0].page_id} onChange={(event) => set("page_id", event.target.value)}>{pages.map((page) => <option key={page.page_id} value={page.page_id}>{page.name}</option>)}</select></Opt>}
            </Group>
            {variables.length > 0 && !isDiagram && <Group title={t("Repeat options")} open={Boolean(card.repeat)}>
              <Opt label={t("Repeat for")} words="repeat variable" hint={t("One copy of the panel for each value picked.")}>
                <select value={card.repeat?.variable ?? ""} onChange={(event) => set("repeat", event.target.value ? { variable: event.target.value, direction: card.repeat?.direction ?? "h", max_per_row: card.repeat?.max_per_row ?? 4 } : null)}>
                  <option value="">{t("Off")}</option>
                  {variables.filter((variable) => variable.type !== "interval").map((variable) => <option key={variable.name} value={variable.name}>${variable.name}</option>)}
                </select>
              </Opt>
              {card.repeat && <>
                <Opt label={t("Direction")} words="repeat"><Select value={card.repeat.direction} onChange={(direction) => set("repeat", { ...card.repeat!, direction })} label={t("Direction")} options={[["h", t("Side by side")], ["v", t("One under the other")]]} /></Opt>
                {card.repeat.direction === "h" && <Opt label={t("Most per row")} words="repeat"><select value={card.repeat.max_per_row} onChange={(event) => set("repeat", { ...card.repeat!, max_per_row: Number(event.target.value) })}>{[1, 2, 3, 4, 6].map((n) => <option key={n} value={n}>{n}</option>)}</select></Opt>}
              </>}
            </Group>}
          </aside>
        </SearchContext.Provider>
      </div>
    </form>
  </div>;
}
