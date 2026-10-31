import { useEffect, useMemo, useState, type FormEvent, type ReactNode, useRef } from "react";
import { AlertTriangle, Bell, BellRing, ChevronDown, ChevronRight, CircleAlert, Download, ListTree, LoaderCircle, Pencil, Plus, Search, Table2, Upload, X } from "lucide-react";
import { deskApi } from "./deskApi";
import { ExportDialog } from "./AssetImport";
import { requestJson } from "./api";
import { modelApi, showValue, TypeIcon, typeIndex, type AssetRelations, type AssetType, type AttributeValue, type Missing, type TypeCatalog } from "./assetModel";
import { RecordForm, Relations, SignalTable, type RecordSignal } from "./AssetRecord";
import { AssetSituation } from "./AssetSituation";
import { ALL_LEVELS, openToLevel, saveTreeLevel, savedTreeLevel, TREE_LEVELS } from "./assetTree";
import { locale, t } from "./i18n";
import { assetPath } from "./assetLinks";
import { navigate } from "./nav";
import { AssistantTitleButton, DataTable, FollowUp, PageTabs, type DataColumn, useAssistantPage, Heading } from "@plantcraft/ui";
import { ADMIN_ONLY, useCanEdit, useIsAdmin } from "./session";
import type { SuiteAppCard } from "./types";
import "./assets.css";
import { useDialogKeys } from "./dialogKeys";

/** The plant's asset tree: the apps of the suite read it through API v1. */

export interface Asset {
  asset_id: string;
  parent_id: string | null;
  kind: string;
  kind_label?: string;
  name: string;
  description: string;
  origin: string;
  position: number;
  attributes?: Record<string, AttributeValue>;
}

interface PlatformEvent { event_id: number; at: string; kind: string; summary: string; actor: string }

export interface AssetKind { kind: string; label: string; builtin: boolean; count: number; parent?: string | null; icon?: string }
interface AssetTree { root_id: string; kinds: AssetKind[]; items: Asset[] }
interface ContentRow extends Asset { where: string; signals: number }
interface AssetContents { kinds: Record<string, number>; total: number; items: ContentRow[] }
interface AssetDetail {
  asset: Asset;
  type: AssetType | null;
  type_path: string[];
  attributes: Record<string, AttributeValue>;
  missing: Missing;
  relations: AssetRelations;
  path: Asset[];
  children: Asset[];
  signals: RecordSignal[];
  timeline: PlatformEvent[];
}

export const assetApi = {
  tree: () => requestJson<AssetTree>("/api/assets"),
  get: (id: string) => requestJson<AssetDetail>(`/api/assets/${encodeURIComponent(id)}`),
  contents: (id: string, kinds: string[], q: string) => requestJson<AssetContents>(`/api/assets/${encodeURIComponent(id)}/contents?${new URLSearchParams([...kinds.map((kind) => ["kind", kind]), ...(q ? [["q", q]] : [])])}`),
  create: (payload: { asset_id?: string; name: string; kind: string; parent_id: string | null; description: string }) => requestJson<Asset>("/api/assets", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: string, payload: { name?: string; kind?: string; description?: string }) => requestJson<Asset>(`/api/assets/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
};

export const KIND_LABELS: Record<string, string> = { site: t("Site"), unit: t("Unit"), area: t("Area"), equipment: t("Equipment"), loop: t("Loop") };
export const KIND_PLURALS: Record<string, string> = { site: t("Sites"), unit: t("Units"), area: t("Areas"), equipment: t("Equipment"), loop: t("Loops") };
const ORIGIN_LABELS: Record<string, string> = { platform: t("Platform"), manual: t("Entered by hand"), scenario: t("Scenario file"), map: t("Configuration file"), cpm: t("Scenario file") };

export function KindIcon({ kind, icon, size = 15 }: { kind: string; icon?: string; size?: number }) {
  return <TypeIcon icon={icon} kind={kind} size={size} />;
}

function Go({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  return <a href={to} className={className} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); navigate(to); }}>{children}</a>;
}

function fmtDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(date);
}

function State({ error, label }: { error?: string; label: string }) {
  return error
    ? <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>
    : <div className="module-state"><LoaderCircle className="spin" /><span>{label}</span></div>;
}

// --- The tree ------------------------------------------------------------------

function childrenOf(items: Asset[]) {
  const ids = new Set(items.map((item) => item.asset_id));
  const map = new Map<string | null, Asset[]>();
  for (const item of items) {
    const key = item.parent_id && ids.has(item.parent_id) ? item.parent_id : null;
    map.set(key, [...(map.get(key) ?? []), item]);
  }
  for (const list of map.values()) list.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name, locale));
  return map;
}

function TreeNode({ asset, tree, open, toggle, visible, depth, labels, icons }: { asset: Asset; tree: Map<string | null, Asset[]>; open: Set<string>; toggle: (id: string) => void; visible: Set<string> | null; depth: number; labels: Record<string, string>; icons: Record<string, string> }) {
  const kids = (tree.get(asset.asset_id) ?? []).filter((item) => !visible || visible.has(item.asset_id));
  const expanded = visible ? true : open.has(asset.asset_id);
  return <li>
    <div className="as-node" style={{ paddingLeft: 6 + depth * 18 }}>
      {kids.length ? <button className="as-toggle" onClick={() => toggle(asset.asset_id)} aria-label={expanded ? t("Collapse") : t("Expand")}>{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button> : <span className="as-toggle" />}
      <Go to={assetPath(asset.asset_id)} className={`as-link as-kind-${asset.kind}`}><KindIcon kind={asset.kind} icon={icons[asset.kind]} /><strong>{asset.name}</strong>{asset.name !== asset.asset_id && <small>{asset.asset_id}</small>}</Go>
      <span className="as-kind">{labels[asset.kind] ?? asset.kind}</span>
    </div>
    {expanded && kids.length > 0 && <ul>{kids.map((kid) => <TreeNode key={kid.asset_id} asset={kid} tree={tree} open={open} toggle={toggle} visible={visible} depth={depth + 1} labels={labels} icons={icons} />)}</ul>}
  </li>;
}

/** The types as filter chips (contents of one asset). */
function KindChips({ kinds, selected, onToggle }: { kinds: AssetKind[]; selected: string[]; onToggle: (kind: string | null) => void }) {
  return <div className="as-kinds" role="group" aria-label={t("Asset type")}>
    <button type="button" className={selected.length ? "" : "active"} onClick={() => onToggle(null)}>{t("All")}</button>
    {kinds.map((item) => <button type="button" key={item.kind} className={selected.includes(item.kind) ? "active" : ""} onClick={() => onToggle(item.kind)}><KindIcon kind={item.kind} icon={item.icon} size={13} />{item.label}<span>{item.count}</span></button>)}
  </div>;
}

/** Types in inheritance order, for a select: "Equipment", "— Valve", "—— Control valve". */
function typeOptions(types: AssetType[]) {
  return [...types].sort((a, b) => a.path.map((id) => types.find((item) => item.id === id)?.name ?? id).join("/").localeCompare(b.path.map((id) => types.find((item) => item.id === id)?.name ?? id).join("/"), locale));
}

function matches(value: AttributeValue | undefined, needle: string) {
  if (value === null || value === undefined || value === "") return false;
  return !needle || String(value).toLowerCase().includes(needle);
}

/** Assets and their types are one place: two tabs of the Assets page. */
export function AssetTabs({ current }: { current: "assets" | "types" }) {
  const isAdmin = useIsAdmin();
  if (!isAdmin && current === "assets") return null;
  return <PageTabs label={t("Assets")} href={(to) => to} navigate={navigate} tabs={[
    { to: "/assets", label: t("Assets"), active: current === "assets" },
    { to: "/asset-types", label: t("Asset types"), active: current === "types" },
  ]} />;
}

// The type of result assets (plantcraft_sdk.assets.RESULT_TYPE).
const RESULT_KIND = "result";

export function AssetsPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<AssetTree | null>(null);
  const [catalog, setCatalog] = useState<TypeCatalog | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [typeId, setTypeId] = useState(() => new URLSearchParams(window.location.search).get("type") ?? "");
  const [attribute, setAttribute] = useState("");
  const [attributeValue, setAttributeValue] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [level, setLevel] = useState<number | null>(() => savedTreeLevel());
  const [creating, setCreating] = useState(false);
  const [exporting, setExporting] = useState(false);
  // Result assets (what apps record about an asset, such as a Link schedule's outputs) stay
  // out of the tree unless asked for, or their type is chosen.
  const [showResults, setShowResults] = useState(false);
  const load = () => assetApi.tree().then((tree) => {
    setData(tree);
    // The tree opens to the level the person chose last (2 at first): the same depth in every branch.
    setOpen((current) => current.size ? current : openToLevel(childrenOf(tree.items), savedTreeLevel()));
  }).catch((err) => setError(err.message));
  useEffect(() => { void load(); modelApi.types().then(setCatalog).catch(() => undefined); }, []);
  const types = catalog?.types ?? [];
  const index = useMemo(() => typeIndex(types), [catalog]);
  const chosen = typeId ? index.byId.get(typeId) : undefined;
  const wantedKinds = useMemo(() => (typeId ? index.under(typeId) : null), [typeId, index]);
  // The attributes to filter on: the chosen type's, else every type's (by key).
  const filterAttributes = useMemo(() => {
    const found = new Map<string, string>();
    for (const item of chosen ? [chosen] : types) for (const entry of item.attributes) if (!found.has(entry.key)) found.set(entry.key, entry.name);
    return [...found.entries()].sort((a, b) => a[1].localeCompare(b[1], locale));
  }, [chosen, types]);
  const hasResults = useMemo(() => (data?.items ?? []).some((item) => item.kind === RESULT_KIND), [data]);
  const items = useMemo(() => {
    const all = data?.items ?? [];
    return showResults || (wantedKinds?.has(RESULT_KIND) ?? false) ? all : all.filter((item) => item.kind !== RESULT_KIND);
  }, [data, showResults, wantedKinds]);
  const tree = useMemo(() => childrenOf(items), [items]);
  const labels = useMemo(() => Object.fromEntries((data?.kinds ?? []).map((item) => [item.kind, item.label])), [data]);
  const icons = useMemo(() => Object.fromEntries(types.map((item) => [item.id, item.icon])), [types]);
  const needle = query.trim().toLowerCase();
  const valueNeedle = attributeValue.trim().toLowerCase();
  const kept = useMemo(() => items.filter((item) =>
    (!wantedKinds || wantedKinds.has(item.kind))
    && (!needle || `${item.asset_id} ${item.name} ${item.description}`.toLowerCase().includes(needle))
    && (!attribute || matches(item.attributes?.[attribute], valueNeedle))), [items, wantedKinds, needle, attribute, valueNeedle]);
  const visible = useMemo(() => {
    if ((!needle && !wantedKinds && !attribute) || !data) return null;
    const byId = new Map(data.items.map((item) => [item.asset_id, item]));
    const keep = new Set<string>();
    for (const item of kept) {
      let current: Asset | undefined = item;
      while (current && !keep.has(current.asset_id)) {
        keep.add(current.asset_id);
        current = current.parent_id ? byId.get(current.parent_id) : undefined;
      }
    }
    return keep;
  }, [kept, needle, wantedKinds, attribute, data]);
  // The assistant's works on this page (create an asset, ask about the tree); an asset it
  // created shows up in the tree at once.
  useEffect(() => { const reload = () => void load(); window.addEventListener("pc-assistant-created", reload); return () => window.removeEventListener("pc-assistant-created", reload); }, []);
  useAssistantPage(data && {
    place: t("Plant › Assets"), page: "processcraft:assets",
    facts: { assets: data.items.length, shown: visible ? visible.size : items.length },
    view: { search: query, type: typeId, attribute, value: attributeValue, results: showResults,
      kinds: data.kinds.map((item) => `${item.kind} (${item.count})`) },
  });
  if (!data) return <State error={error} label={t("Loading the assets…")} />;
  const roots = (tree.get(null) ?? []).filter((item) => !visible || visible.has(item.asset_id));
  const toggle = (id: string) => { setLevel(null); setOpen((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; }); };
  const showLevel = (next: number) => { setLevel(next); saveTreeLevel(next); setOpen(openToLevel(tree, next)); };
  const chooseType = (next: string) => {
    setTypeId(next);
    if (next && attribute && !index.byId.get(next)?.attributes.some((entry) => entry.key === attribute)) { setAttribute(""); setAttributeValue(""); }
    window.history.replaceState({}, "", next ? `/assets?type=${encodeURIComponent(next)}` : "/assets");
  };
  return <>
    <Heading title={t("Assets")} actions={<><button type="button" className="button button-secondary" disabled={!isAdmin} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => navigate("/asset-import")}><Upload size={16} /> {t("Import")}</button><button type="button" className="button button-secondary" onClick={() => setExporting(true)}><Download size={16} /> {t("Export")}</button><button type="button" className="button button-primary" disabled={!isAdmin} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => setCreating(true)}><Plus size={16} /> {t("New asset")}</button></>} />
    <AssetTabs current="assets" />
    <article className="panel as-tree-panel" data-tour="asset-tree">
      <div className="as-toolbar">
        <label className="as-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search assets by name or code")} /></label>
        <label className="as-filter"><span>{t("Type")}</span><select aria-label={t("Filter by type")} value={typeId} onChange={(event) => chooseType(event.target.value)}><option value="">{t("All types")}</option>{typeOptions(types).map((item) => <option key={item.id} value={item.id}>{"— ".repeat(item.path.length - 1)}{item.name} ({item.total ?? 0})</option>)}</select></label>
        <label className="as-filter"><span>{t("Attribute")}</span><select aria-label={t("Filter by attribute")} value={attribute} onChange={(event) => setAttribute(event.target.value)}><option value="">{t("Any")}</option>{filterAttributes.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
        {attribute && <label className="as-search as-search-small"><input aria-label={t("Attribute value")} value={attributeValue} onChange={(event) => setAttributeValue(event.target.value)} placeholder={t("Any value")} /></label>}
        {hasResults && <label className="as-results-toggle" title={t("What apps record about each asset, such as the outputs of an Analytics monitor")}><input type="checkbox" checked={showResults} onChange={(event) => setShowResults(event.target.checked)} /> {t("Show app results")}</label>}
        {(typeId || attribute || query) && <button type="button" className="as-link-button" onClick={() => { chooseType(""); setAttribute(""); setAttributeValue(""); setQuery(""); }}><X size={13} /> {t("Clear")}</button>}
        {chosen ? <span className="as-view-hint"><Table2 size={14} /> {t("Table of {type}", { type: chosen.name })}</span>
          : <div className="as-levels"><span className="as-view-hint"><ListTree size={14} /> {t("Open to level")}</span>
            <div className="segmented" role="group" aria-label={t("Open the tree to a level")}>
              {TREE_LEVELS.map((value) => <button key={value} type="button" className={level === value ? "on" : undefined} aria-pressed={level === value} title={t("Show {count} levels under the installation", { count: value })} onClick={() => showLevel(value)}>{value}</button>)}
              <button type="button" className={level === ALL_LEVELS ? "on" : undefined} aria-pressed={level === ALL_LEVELS} onClick={() => showLevel(ALL_LEVELS)}>{t("All")}</button>
            </div>
            <button type="button" className="button button-ghost button-small" disabled={visible !== null} onClick={() => { setLevel(0); setOpen(new Set()); }}>{t("Collapse all")}</button>
          </div>}
      </div>
      {chosen ? <TypeTable type={chosen} items={kept} all={data.items} labels={labels} icons={icons} />
        : roots.length ? <ul className="as-tree">{roots.map((root) => <TreeNode key={root.asset_id} asset={root} tree={tree} open={open} toggle={toggle} visible={visible} depth={0} labels={labels} icons={icons} />)}</ul> : <p className="muted">{t("No assets found.")}</p>}
    </article>
    {exporting && <ExportDialog items={data.items} rootId={data.root_id} onClose={() => setExporting(false)} />}
    {creating && <AssetForm kinds={data.kinds} types={types} assets={data.items} parentId={data.root_id} onClose={() => setCreating(false)} onSaved={(asset) => navigate(assetPath(asset.asset_id))} />}
  </>;
}

/** The assets of one type (and its subtypes) with one column per attribute. */
function TypeTable({ type, items, all, labels, icons }: { type: AssetType; items: Asset[]; all: Asset[]; labels: Record<string, string>; icons: Record<string, string> }) {
  const byId = useMemo(() => new Map(all.map((item) => [item.asset_id, item])), [all]);
  const where = (item: Asset) => {
    const names: string[] = [];
    let parent = item.parent_id ? byId.get(item.parent_id) : undefined;
    while (parent && names.length < 6) { names.push(parent.name); parent = parent.parent_id ? byId.get(parent.parent_id) : undefined; }
    return names.slice(0, -1).reverse().join(" › ");
  };
  const columns = type.attributes;
  const tableColumns: DataColumn<Asset>[] = [
    { key: "asset", label: t("Asset"), sort: (item) => item.asset_id, filter: { value: (item) => labels[item.kind] ?? item.kind, label: t("Type") }, render: (item) => <div className="as-cell-asset"><Go to={assetPath(item.asset_id)} className="as-link"><KindIcon kind={item.kind} icon={icons[item.kind]} /><strong>{item.asset_id}</strong>{item.name !== item.asset_id && <small>{item.name}</small>}</Go>{item.kind !== type.id && <span className="as-kind">{labels[item.kind] ?? item.kind}</span>}</div> },
    { key: "where", label: t("Where"), className: "muted", sort: (item) => where(item), filter: { value: (item) => where(item) }, render: (item) => where(item) || "—" },
    ...columns.map((column): DataColumn<Asset> => ({
      key: `attr:${column.key}`,
      label: <>{column.name}{column.unit && <small> ({column.unit})</small>}</>,
      numeric: column.data_type === "number",
      className: column.data_type === "number" ? "as-num" : undefined,
      sort: (item) => { const value = item.attributes?.[column.key]; return typeof value === "number" || typeof value === "string" ? value : value == null ? null : String(value); },
      filter: column.data_type === "number" ? undefined : { value: (item) => { const value = item.attributes?.[column.key]; return value == null ? "" : String(value); }, label: column.name },
      render: (item) => showValue(item.attributes?.[column.key], column),
    })),
  ];
  return <div className="as-type-table-wrap">
    <DataTable rows={items} columns={tableColumns} rowKey={(item) => item.asset_id} label={t("Assets of type {type}", { type: type.name })} className="as-type-table" initialSort={{ key: "asset", descending: false }} empty={t("No assets of this type match.")} />
    <p className="muted as-count">{items.length === 1 ? t("1 asset") : t("{count} assets", { count: items.length })}</p>
  </div>;
}

/** Create an asset under a parent, or rename and retype one. */
function AssetForm({ kinds, types, assets, parentId, asset, onClose, onSaved }: { kinds: AssetKind[]; types: AssetType[]; assets?: Asset[]; parentId?: string; asset?: Asset; onClose: () => void; onSaved: (asset: Asset) => void }) {
  const box = useRef<HTMLFormElement>(null);
  useDialogKeys(box, onClose);
  const [name, setName] = useState(asset?.name ?? "");
  const [tag, setTag] = useState("");
  const [kind, setKind] = useState(asset?.kind ?? "equipment");
  const [parent, setParent] = useState(parentId ?? "");
  const [description, setDescription] = useState(asset?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      onSaved(asset ? await assetApi.update(asset.asset_id, { name, kind, description }) : await assetApi.create({ ...(tag.trim() ? { asset_id: tag.trim() } : {}), name: name.trim() || tag.trim(), kind, parent_id: parent || null, description }));
    } catch (err) { setError(err instanceof Error ? err.message : t("Could not save.")); setBusy(false); }
  }
  const parents = (assets ?? []).filter((item) => item.kind !== "loop").sort((a, b) => a.name.localeCompare(b.name, locale));
  // The types the parent's type says may sit inside it come first.
  const parentKind = (assets ?? []).find((item) => item.asset_id === parent)?.kind;
  const allowed = new Set(types.find((item) => item.id === parentKind)?.children ?? []);
  const usual = kinds.filter((item) => allowed.has(item.kind) && item.kind !== "site");
  const rest = kinds.filter((item) => !allowed.has(item.kind) && item.kind !== "site");
  return <div className="modal-backdrop" onClick={onClose}>
    <form ref={box} className="modal" onClick={(event) => event.stopPropagation()} onSubmit={save} role="dialog" aria-modal="true" aria-label={asset ? t("Edit asset") : t("New asset")}>
      <header><div><span className="eyebrow">{t("Assets")}</span><h2>{asset ? t("Edit asset") : t("New asset")}</h2><p>{asset ? t("Name, type and description. An asset edited by hand is no longer changed by the scenario file.") : t("A plant asset: unit, area, equipment or a type you created.")}</p></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X /></button></header>
      {error && <div className="form-error">{error}</div>}
      <div className="form-grid">
        {!asset && <label>{t("Tag")}<input autoFocus maxLength={128} value={tag} placeholder={t("FV-2001")} onChange={(event) => setTag(event.target.value)} /></label>}
        <label className={asset ? "field-span" : ""}>{t("Name")}<input autoFocus={!!asset} required={!!asset} maxLength={120} value={name} placeholder={asset ? "" : t("Same as the tag")} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Type")}<select value={kind} onChange={(event) => setKind(event.target.value)}>
          {usual.length > 0 && <optgroup label={t("Usually inside this parent")}>{usual.map((item) => <option key={item.kind} value={item.kind}>{item.label}</option>)}</optgroup>}
          {usual.length > 0 ? <optgroup label={t("Other types")}>{rest.map((item) => <option key={item.kind} value={item.kind}>{item.label}</option>)}</optgroup> : rest.map((item) => <option key={item.kind} value={item.kind}>{item.label}</option>)}
          {kind === "site" && <option value="site">{kinds.find((item) => item.kind === "site")?.label ?? "site"}</option>}
        </select></label>
        {!asset && <label>{t("Inside")}<select value={parent} onChange={(event) => setParent(event.target.value)}>{parents.map((item) => <option key={item.asset_id} value={item.asset_id}>{item.name}</option>)}</select></label>}
        <label className="field-span">{t("Description")}<textarea rows={3} maxLength={600} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !(name.trim() || tag.trim())}>{busy ? <LoaderCircle className="spin" size={15} /> : null}{t("Save")}</button></footer>
    </form>
  </div>;
}

// --- One asset -------------------------------------------------------------------

/** What sits under an asset at any depth: a summary, then a filterable table. */
function AssetContents({ asset, kinds }: { asset: Asset; kinds: AssetKind[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [data, setData] = useState<AssetContents | null>(null);
  const [summary, setSummary] = useState<AssetContents | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      assetApi.contents(asset.asset_id, selected, query.trim())
        .then((result) => { if (!cancelled) { setData(result); setSummary((current) => current ?? result); setError(""); } })
        .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : t("Failed to load the contents.")); });
    }, query ? 200 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [asset.asset_id, selected, query]);
  if (!summary) return error ? <State error={error} label="" /> : null;
  if (!Object.keys(summary.kinds).length) return null;
  const present = kinds.filter((item) => summary.kinds[item.kind]).map((item) => ({ ...item, count: summary.kinds[item.kind] }));
  const toggle = (kind: string | null) => setSelected((current) => kind === null ? [] : current.includes(kind) ? current.filter((item) => item !== kind) : [...current, kind]);
  return <article className="panel as-contents pc-span-all">
    <header className="panel-header"><div><h2>{t("Contents")}</h2><p>{t("Everything inside {name}, at any level.", { name: asset.name })}</p></div></header>
    <div className="as-toolbar"><label className="as-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search inside this asset")} /></label><KindChips kinds={present} selected={selected} onToggle={toggle} /></div>
    <div className="as-table" role="table" aria-label={t("Asset contents")}>
      <div className="as-tr as-th" role="row"><span>{t("Asset")}</span><span>{t("Type")}</span><span>{t("Where")}</span><span>{t("Signals")}</span></div>
      {(data?.items ?? []).map((row) => <div key={row.asset_id} className="as-tr" role="row">
        <Go to={assetPath(row.asset_id)} className="as-link"><KindIcon kind={row.kind} icon={kinds.find((item) => item.kind === row.kind)?.icon} /><strong>{row.name}</strong>{row.name !== row.asset_id && <small>{row.asset_id}</small>}</Go>
        <span>{row.kind_label ?? row.kind}</span>
        <span className="muted">{row.where || "—"}</span>
        <span>{row.signals || "—"}</span>
      </div>)}
      {data && !data.items.length && <p className="muted">{t("Nothing found.")}</p>}
    </div>
    {data && data.total > data.items.length && <p className="muted">{t("Showing {count} of {total}; filter by type or search.", { count: data.items.length, total: data.total })}</p>}
  </article>;
}

type AssetTab = "overview" | "situation" | "signals" | "inside" | "relations" | "actions" | "history";
const ASSET_TABS: AssetTab[] = ["overview", "situation", "signals", "inside", "relations", "actions", "history"];

/** The tab in the address (?tab=signals), or the overview. */
export function tabOf(search: string): AssetTab {
  const value = new URLSearchParams(search).get("tab") as AssetTab | null;
  return value && ASSET_TABS.includes(value) ? value : "overview";
}

/** One asset, built from its type (redone, no links that lead nowhere): a
 * header, then tabs: an overview (record, main signals, what is inside), its situation (what
 * every app says about it, AssetSituation), the signals as one
 * table, the assets inside it, relations, follow-up actions and history. */
/** Follow an asset: its alarms and results come to the person's Desk. */
function FollowButton({ assetId }: { assetId: string }) {
  const ref = `asset:${assetId}`;
  const [following, setFollowing] = useState<boolean | null>(null);
  useEffect(() => { deskApi.following(ref).then((value) => setFollowing(value.following)).catch(() => setFollowing(null)); }, [ref]);
  if (following === null) return null;
  const toggle = () => { void (following ? deskApi.unfollow(ref) : deskApi.follow(ref)).then((value) => setFollowing(value.following)).catch(() => undefined); };
  return <button type="button" className="button button-secondary" aria-pressed={following} onClick={toggle}
    title={following ? t("Stop following: its alarms and results leave your Desk.") : t("Follow: its alarms and results come to your Desk.")}>
    {following ? <BellRing size={15} /> : <Bell size={15} />} {following ? t("Following") : t("Follow")}
  </button>;
}

export function AssetPage({ assetId }: { assetId: string; apps?: SuiteAppCard[] }) {
  const isAdmin = useIsAdmin();
  const canEdit = useCanEdit();
  const [data, setData] = useState<AssetDetail | null>(null);
  const [tree, setTree] = useState<AssetTree | null>(null);
  const [catalog, setCatalog] = useState<TypeCatalog | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<AssetTab>(() => tabOf(window.location.search));
  const load = () => assetApi.get(assetId).then((value) => { setData(value); setError(""); }).catch((err) => setError(err.message));
  useEffect(() => {
    setData(null);
    void load();
    assetApi.tree().then(setTree).catch(() => undefined);
    modelApi.types().then(setCatalog).catch(() => undefined);
  }, [assetId]);
  const choose = (next: AssetTab) => {
    setTab(next);
    window.history.replaceState(window.history.state, "", next === "overview" ? assetPath(assetId) : `${assetPath(assetId)}?tab=${next}`);
  };
  // What the assistant can do on this page (the button beside the title): PlantCraft's works for
  // an asset (assistant_works/platform.py).
  useAssistantPage(data && {
    page: "processcraft:asset", subject: `asset:${data.asset.asset_id}`, title: data.asset.name, place: t("Assets › {name}", { name: data.asset.name }),
    context: [`Asset ${data.asset.asset_id} (${data.asset.name}), type ${data.type_path.join(" › ") || data.asset.kind}: ${data.asset.description || "no description"}.`,
      `Signals: ${data.signals.map((item) => `${item.role || "-"} ${item.signal_id}${item.unit ? ` (${item.unit})` : ""}`).join("; ") || "none"}.`].join("\n"),
  });
  if (!data) return <State error={error} label={t("Loading the asset…")} />;
  const { asset, type } = data;
  const kinds = tree?.kinds ?? [];
  const names = new Map((catalog?.types ?? []).map((item) => [item.id, item.name]));
  const typePath = data.type_path.map((id) => names.get(id) ?? id);
  const assets = (tree?.items ?? []).map((item) => ({ asset_id: item.asset_id, name: item.name, kind: item.kind }));
  const missingRoles = type ? type.roles.filter((item) => data.missing.roles.includes(item.key)).map((item) => item.name) : [];
  const missingAttributes = type ? type.attributes.filter((item) => data.missing.attributes.includes(item.key)).map((item) => item.name) : [];
  const inside = insideCounts(tree?.items ?? [], asset.asset_id);
  const insideTotal = Object.values(inside).reduce((sum, count) => sum + count, 0);
  const relationCount = data.relations.outgoing.length + data.relations.incoming.length;
  const labels: Record<AssetTab, string> = {
    overview: t("Overview"),
    situation: t("Situation"),
    signals: t("Signals ({count})", { count: data.signals.length }),
    inside: t("Inside ({count})", { count: insideTotal }),
    relations: t("Relations ({count})", { count: relationCount }),
    actions: t("Actions"),
    history: t("History"),
  };
  return <>
    <nav className="as-breadcrumb"><Go to="/assets">{t("Assets")}</Go>{data.path.map((item) => <span key={item.asset_id}><ChevronRight size={13} />{item.asset_id === asset.asset_id ? <b>{item.name}</b> : <Go to={assetPath(item.asset_id)}>{item.name}</Go>}</span>)}</nav>
    <div className="page-heading as-head" data-tour="asset-head"><div>
      <span className="eyebrow"><KindIcon kind={asset.kind} icon={type?.icon} size={13} /> {typePath.join(" › ") || asset.kind} · {ORIGIN_LABELS[asset.origin] ?? asset.origin}</span>
      <div className="page-heading-title"><h1><span className="as-tag">{asset.asset_id}</span>{asset.name !== asset.asset_id && <span className="as-head-name">{asset.name}</span>}</h1><AssistantTitleButton /></div>
      {asset.description && <p className="pc-heading-keep">{asset.description}</p>}
    </div>
      <div className="heading-actions">
        <FollowButton assetId={asset.asset_id} />
        <button type="button" className="button button-secondary" disabled={!isAdmin} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => setEditing(true)}><Pencil size={15} /> {t("Edit")}</button>
      </div></div>
    {(missingRoles.length > 0 || missingAttributes.length > 0) && <div className="as-incomplete" role="status"><CircleAlert size={16} /><span><strong>{t("Incomplete record.")}</strong> {t("Missing: {items}.", { items: [...missingRoles, ...missingAttributes].join(", ") })}</span></div>}
    <PageTabs label={t("Asset")} href={(to) => to} navigate={(to) => choose(tabOf(to.slice(to.indexOf("?"))))} tabs={ASSET_TABS.map((id) => ({ to: `?tab=${id}`, label: labels[id], active: tab === id }))} />
    {tab === "overview" && <section className="as-overview" data-tour="asset-overview">
      <article className="panel"><header className="panel-header"><div><h2>{t("Record")}</h2><p>{type ? t("The attributes of this {type}", { type: type.name.toLowerCase() }) : t("This asset's type is not in the catalog.")}</p></div></header>
        {type && <RecordForm assetId={asset.asset_id} type={type} values={data.attributes} missing={data.missing} assets={assets} canEdit={canEdit} onSaved={() => void load()} />}
      </article>
      <div className="as-overview-side">
        <article className="panel"><header className="panel-header"><div><h2>{t("Signals")}</h2><p>{t("By role, with the last value")}</p></div></header>
          <SignalTable assetId={asset.asset_id} type={type} signals={data.signals} canEdit={false} onChanged={() => void load()} limit={6} onMore={() => choose("signals")} />
        </article>
        {insideTotal > 0 && <article className="panel"><header className="panel-header"><div><h2>{t("Inside")}</h2><p>{t("Everything inside {name}, at any level.", { name: asset.name })}</p></div></header>
          <div className="as-inside-counts">{kinds.filter((item) => inside[item.kind]).map((item) => <button type="button" key={item.kind} onClick={() => choose("inside")}><KindIcon kind={item.kind} icon={item.icon} size={14} /><b className="pc-num">{inside[item.kind]}</b><span>{item.label}</span></button>)}</div>
        </article>}
      </div>
    </section>}
    {tab === "situation" && <AssetSituation assetId={asset.asset_id} onActions={() => choose("actions")} />}
    {tab === "signals" && <article className="panel"><header className="panel-header"><div><h2>{t("Signals")}</h2><p>{type ? t("Each role of {type} and the signal that fills it, then the other signals of this asset.", { type: type.name }) : t("The signals of this asset.")}</p></div></header>
      <SignalTable assetId={asset.asset_id} type={type} signals={data.signals} canEdit={canEdit} onChanged={() => void load()} />
    </article>}
    {tab === "inside" && (insideTotal ? <AssetContents key={asset.asset_id} asset={asset} kinds={kinds} /> : <p className="muted">{t("Nothing inside {name}.", { name: asset.name })}</p>)}
    {tab === "relations" && <article className="panel"><header className="panel-header"><div><h2>{t("Relations")}</h2><p>{t("Links to other assets, outside the tree")}</p></div></header>
      <Relations assetId={asset.asset_id} relations={data.relations} kinds={catalog?.relations ?? []} assets={assets} canEdit={canEdit} onChanged={() => void load()} />
    </article>}
    {tab === "actions" && <FollowUp subject={`asset:${asset.asset_id}`} newTitle={asset.name !== asset.asset_id ? `${asset.asset_id}: ${asset.name}` : asset.asset_id} platformUrl="/" canCreate={canEdit} />}
    {tab === "history" && <article className="panel"><header className="panel-header"><div><h2>{t("History")}</h2><p>{t("What happened to this asset")}</p></div></header>
      <ol className="as-timeline">{data.timeline.map((event) => <li key={event.event_id}><time>{fmtDate(event.at)}</time><span>{event.summary || event.kind}</span>{event.actor && <small>{event.actor}</small>}</li>)}{!data.timeline.length && <p className="muted">{t("Nothing recorded yet.")}</p>}</ol>
    </article>}
    {editing && <AssetForm kinds={kinds} types={catalog?.types ?? []} asset={asset} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); void load(); }} />}
  </>;
}

/** How many assets of each kind sit inside one, at any depth. */
export function insideCounts(items: Pick<Asset, "asset_id" | "parent_id" | "kind">[], rootId: string): Record<string, number> {
  const kids = new Map<string, string[]>();
  const kindOf = new Map(items.map((item) => [item.asset_id, item.kind]));
  for (const item of items) if (item.parent_id) kids.set(item.parent_id, [...(kids.get(item.parent_id) ?? []), item.asset_id]);
  const counts: Record<string, number> = {};
  const stack = [...(kids.get(rootId) ?? [])];
  const seen = new Set<string>();
  while (stack.length) {
    const id = stack.pop() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    const kind = kindOf.get(id) ?? "";
    counts[kind] = (counts[kind] ?? 0) + 1;
    stack.push(...(kids.get(id) ?? []));
  }
  return counts;
}
