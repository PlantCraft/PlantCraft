/** Assets › Types: the type catalog (everyone reads it, admins edit it). */
import { AssetTabs } from "./AssetsPage";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useAssistantPage } from "@plantcraft/ui";
import { AlertTriangle, BookOpen, LoaderCircle, Plus, Save, Search, Trash2, X } from "lucide-react";
import { DATA_TYPE_LABELS, ICON_GROUPS, modelApi, TYPE_ICONS, TypeIcon, typeIndex, type AssetType, type DataType, type TypeAttribute, type TypeCatalog, type TypeDefinition, type TypeRole } from "./assetModel";
import { t } from "./i18n";
import { navigate } from "./nav";
import { ADMIN_ONLY, useIsAdmin } from "./session";
import "./assets.css";
import { Modal } from "./Modal";

/** A row as the type stores it: without the "from" the catalog adds. */
function withoutFrom<T extends { from?: string }>(item: T): Omit<T, "from"> {
  const copy = { ...item };
  delete copy.from;
  return copy;
}

function Go({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  return <a href={to} className={className} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); navigate(to); }}>{children}</a>;
}

const CORE = ["site", "unit", "area", "equipment", "loop"];

/** Parents before children, each with its depth in the inheritance. */
function inheritanceOrder(types: AssetType[]) {
  const ids = new Set(types.map((item) => item.id));
  const kids = new Map<string | null, AssetType[]>();
  for (const item of types) {
    const parent = item.parent && ids.has(item.parent) ? item.parent : null;
    kids.set(parent, [...(kids.get(parent) ?? []), item]);
  }
  const ordered: Array<{ type: AssetType; depth: number }> = [];
  const walk = (parent: string | null, depth: number) => {
    for (const item of kids.get(parent) ?? []) {
      if (ordered.some((row) => row.type.id === item.id)) continue;
      ordered.push({ type: item, depth });
      walk(item.id, depth + 1);
    }
  };
  walk(null, 0);
  return ordered;
}

function draftOf(type: AssetType | null): TypeDefinition {
  if (!type) return { name: "", description: "", icon: "box", parent: "equipment", attributes: [], roles: [], children: [] };
  return {
    name: type.name,
    description: type.description,
    icon: type.icon,
    parent: type.parent,
    attributes: type.attributes.filter((item) => item.from === type.id).map(withoutFrom),
    roles: type.roles.filter((item) => item.from === type.id).map(withoutFrom),
    children: type.own_children ?? type.children,
  };
}

export function AssetTypesPage({ selected }: { selected: string | null }) {
  const isAdmin = useIsAdmin();
  const [catalog, setCatalog] = useState<TypeCatalog | null>(null);
  const [error, setError] = useState("");
  const load = () => modelApi.types().then((value) => { setCatalog(value); setError(""); }).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load.")));
  useEffect(() => { void load(); }, []);
  const rows = useMemo(() => inheritanceOrder(catalog?.types ?? []), [catalog]);
  // The assistant's work here (assistant_works/platform.py): explain the catalog.
  useAssistantPage({ place: t("Plant › Types"), page: "processcraft:asset-types", facts: { types: catalog?.types.length ?? 0, open: selected ?? "" } });
  if (!catalog) return error ? <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div> : <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading the types…")}</span></div>;
  const { byId } = typeIndex(catalog.types);
  const current = selected && selected !== "new" ? byId.get(selected) ?? null : null;
  return <>
    <div className="page-heading"><div><span className="eyebrow">{t("Plant")}</span><h1>{t("Assets")}</h1><p>{t("What each type of asset records: its attributes, the signals it takes by role and what may sit inside it. A type inherits everything from its parent.")}</p></div>
      <div className="heading-actions"><button type="button" className="button button-primary" disabled={!isAdmin} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => navigate("/asset-types/new")}><Plus size={16} /> {t("New type")}</button></div></div>
    <AssetTabs current="types" />
    <div className="ty-layout">
      <article className="panel ty-list" aria-label={t("Asset types")}>
        <div className="ty-row ty-head" role="row"><span>{t("Type")}</span><span>{t("Attributes")}</span><span>{t("Roles")}</span><span>{t("Assets")}</span></div>
        {rows.map(({ type, depth }) => <Go key={type.id} to={`/asset-types/${encodeURIComponent(type.id)}`} className={`ty-row ${type.id === selected ? "ty-active" : ""}`}>
          <span className="ty-name" style={{ paddingLeft: depth * 16 }}><TypeIcon icon={type.icon} kind={type.id} /><span><strong>{type.name}</strong><small>{type.id}</small></span></span>
          <span>{type.attributes.length}</span>
          <span>{type.roles.length}</span>
          <span title={t("{count} of this type, {total} with its subtypes", { count: type.count ?? 0, total: type.total ?? 0 })}>{type.total ?? 0}</span>
        </Go>)}
      </article>
      {selected ? <TypeEditor key={selected} type={current} isNew={selected === "new"} catalog={catalog} canEdit={isAdmin} onSaved={(saved) => { void load(); navigate(`/asset-types/${encodeURIComponent(saved)}`); }} onRemoved={() => { void load(); navigate("/asset-types"); }} />
        : <article className="panel ty-empty"><p className="muted">{t("Choose a type to see its attributes and signal roles.")}</p></article>}
    </div>
  </>;
}

function TypeEditor({ type, isNew, catalog, canEdit, onSaved, onRemoved }: { type: AssetType | null; isNew: boolean; catalog: TypeCatalog; canEdit: boolean; onSaved: (id: string) => void; onRemoved: () => void }) {
  const [draft, setDraft] = useState<TypeDefinition>(() => draftOf(type));
  const [newId, setNewId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { byId, under } = typeIndex(catalog.types);
  if (!isNew && !type) return <article className="panel ty-empty"><p className="muted">{t("This type does not exist.")}</p></article>;
  const own = type?.id ?? newId;
  const parent = draft.parent ? byId.get(draft.parent) : undefined;
  const inheritedAttributes = parent?.attributes ?? [];
  const inheritedRoles = parent?.roles ?? [];
  const below = type ? under(type.id) : new Set<string>();
  const parents = catalog.types.filter((item) => !below.has(item.id) && item.id !== own);
  const core = type ? CORE.includes(type.id) : false;
  const set = (patch: Partial<TypeDefinition>) => { setDraft((current) => ({ ...current, ...patch })); setNotice(""); };
  const setAttribute = (index: number, patch: Partial<TypeAttribute>) => set({ attributes: draft.attributes.map((item, at) => (at === index ? { ...item, ...patch } : item)) });
  const setRole = (index: number, patch: Partial<TypeRole>) => set({ roles: draft.roles.map((item, at) => (at === index ? { ...item, ...patch } : item)) });
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const payload = { ...draft, ...(isNew && newId.trim() ? { id: newId.trim() } : {}) };
      const saved = isNew ? await modelApi.createType(payload) : await modelApi.updateType(type!.id, payload);
      setError("");
      setNotice(t("Saved."));
      onSaved(saved.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Could not save."));
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!type || !window.confirm(t("Remove the type {name}?", { name: type.name }))) return;
    try { await modelApi.deleteType(type.id); onRemoved(); } catch (err) { setError(err instanceof Error ? err.message : t("Could not remove the type.")); }
  }
  return <form className="panel ty-editor" onSubmit={save} aria-label={t("Type editor")}>
    <header className="ty-editor-head">
      <div><span className="eyebrow"><TypeIcon icon={draft.icon} kind={own} size={13} /> {(type?.path ?? [draft.parent ?? "", own]).filter(Boolean).map((item) => byId.get(item)?.name ?? item).join(" › ")}</span><h2>{isNew ? t("New type") : type!.name}</h2>
        {type && <p>{t("{count} assets of this type, {total} with its subtypes.", { count: type.count ?? 0, total: type.total ?? 0 })}{type.updated_by ? ` ${t("Last changed by {who}.", { who: type.updated_by })}` : ""}</p>}</div>
      <div className="heading-actions">
        {!isNew && !core && <button type="button" className="button button-secondary" disabled={!canEdit} title={canEdit ? undefined : ADMIN_ONLY} onClick={() => void remove()}><Trash2 size={15} /> {t("Remove")}</button>}
        <button className="button button-primary" disabled={!canEdit || busy || !draft.name.trim()} title={canEdit ? undefined : ADMIN_ONLY}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} {t("Save")}</button>
      </div>
    </header>
    {!canEdit && <p className="ty-note">{t("Only admins edit types. Engineers fill each asset's record on its page.")}</p>}
    {error && <div className="form-error">{error}</div>}
    {notice && <p className="ty-saved">{notice}</p>}
    <fieldset disabled={!canEdit} className="ty-fields">
      <div className="form-grid ty-grid">
        <label>{t("Name")}<input required maxLength={60} value={draft.name} onChange={(event) => set({ name: event.target.value })} /></label>
        {isNew ? <label>{t("Id")}<input maxLength={31} placeholder={t("From the name")} value={newId} onChange={(event) => setNewId(event.target.value.toLowerCase())} /></label> : <label>{t("Id")}<input value={type!.id} readOnly /></label>}
        <label className="field-span">{t("Description")}<textarea rows={2} maxLength={600} value={draft.description} onChange={(event) => set({ description: event.target.value })} /></label>
        <label>{t("Parent type")}<select value={draft.parent ?? ""} disabled={core} onChange={(event) => set({ parent: event.target.value || null })}><option value="">{t("None")}</option>{parents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <IconField value={draft.icon} onChange={(icon) => set({ icon })} />
      </div>

      <h3 className="ty-section">{t("Attributes")}</h3>
      <p className="ty-hint">{t("Master data each asset of this type records. Choice attributes take their options separated by commas.")}</p>
      <AttributeGuide />
      <div className="ty-table" role="table" aria-label={t("Attributes")}>
        <div className="ty-attr ty-th" role="row"><span>{t("Key")}</span><span>{t("Name")}</span><span>{t("Data type")}</span><span>{t("Unit")}</span><span>{t("Options")}</span><span>{t("Required")}</span><span /></div>
        {inheritedAttributes.map((item) => <div key={`i-${item.key}`} className="ty-attr ty-inherited" role="row"><code>{item.key}</code><span>{item.name}</span><span>{DATA_TYPE_LABELS[item.data_type]}</span><span>{item.unit || "—"}</span><span className="ty-options" title={item.options.join(", ")}>{item.options.join(", ") || "—"}</span><span>{item.required ? t("yes") : ""}</span><small>{t("from {type}", { type: byId.get(item.from ?? "")?.name ?? item.from ?? "" })}</small></div>)}
        {draft.attributes.map((item, index) => <div key={index} className="ty-attr" role="row">
          <input aria-label={t("Key")} value={item.key} maxLength={40} onChange={(event) => setAttribute(index, { key: event.target.value })} />
          <input aria-label={t("Name")} value={item.name} maxLength={60} onChange={(event) => setAttribute(index, { name: event.target.value })} />
          <select aria-label={t("Data type")} value={item.data_type} onChange={(event) => setAttribute(index, { data_type: event.target.value as DataType, options: event.target.value === "choice" ? item.options : [] })}>{catalog.data_types.map((kind) => <option key={kind} value={kind}>{DATA_TYPE_LABELS[kind]}</option>)}</select>
          <input aria-label={t("Unit")} value={item.unit} maxLength={30} disabled={item.data_type !== "number"} onChange={(event) => setAttribute(index, { unit: event.target.value })} />
          <OptionsInput value={item.options} disabled={item.data_type !== "choice"} onChange={(options) => setAttribute(index, { options })} />
          <input aria-label={t("Required")} type="checkbox" checked={item.required} onChange={(event) => setAttribute(index, { required: event.target.checked })} />
          <button type="button" className="icon-button" aria-label={t("Remove attribute")} onClick={() => set({ attributes: draft.attributes.filter((_, at) => at !== index) })}><X size={14} /></button>
        </div>)}
      </div>
      <button type="button" className="button button-secondary ty-add" onClick={() => set({ attributes: [...draft.attributes, { key: "", name: "", data_type: "text", unit: "", required: false, default: null, options: [] }] })}><Plus size={14} /> {t("Add attribute")}</button>

      <h3 className="ty-section">{t("Signal roles")}</h3>
      <p className="ty-hint">{t("Slots for measured signals. A required role left empty marks the asset's record as incomplete.")}</p>
      <div className="ty-table" role="table" aria-label={t("Signal roles")}>
        <div className="ty-role ty-th" role="row"><span>{t("Key")}</span><span>{t("Name")}</span><span>{t("Unit")}</span><span>{t("Required")}</span><span /></div>
        {inheritedRoles.map((item) => <div key={`i-${item.key}`} className="ty-role ty-inherited" role="row"><code>{item.key}</code><span>{item.name}</span><span>{item.unit || "—"}</span><span>{item.required ? t("yes") : ""}</span><small>{t("from {type}", { type: byId.get(item.from ?? "")?.name ?? item.from ?? "" })}</small></div>)}
        {draft.roles.map((item, index) => <div key={index} className="ty-role" role="row">
          <input aria-label={t("Key")} value={item.key} maxLength={40} onChange={(event) => setRole(index, { key: event.target.value })} />
          <input aria-label={t("Name")} value={item.name} maxLength={60} onChange={(event) => setRole(index, { name: event.target.value })} />
          <input aria-label={t("Unit")} value={item.unit} maxLength={30} onChange={(event) => setRole(index, { unit: event.target.value })} />
          <input aria-label={t("Required")} type="checkbox" checked={item.required} onChange={(event) => setRole(index, { required: event.target.checked })} />
          <button type="button" className="icon-button" aria-label={t("Remove role")} onClick={() => set({ roles: draft.roles.filter((_, at) => at !== index) })}><X size={14} /></button>
        </div>)}
      </div>
      <button type="button" className="button button-secondary ty-add" onClick={() => set({ roles: [...draft.roles, { key: "", name: "", unit: "", required: false }] })}><Plus size={14} /> {t("Add role")}</button>

      <h3 className="ty-section">{t("May contain")}</h3>
      <p className="ty-hint">{t("The types offered first when adding an asset inside one of this type (their subtypes too).")}</p>
      <div className="as-kinds">{catalog.types.filter((item) => item.id !== "site").map((item) => <button type="button" key={item.id} aria-pressed={draft.children.includes(item.id)} className={draft.children.includes(item.id) ? "active" : ""} onClick={() => set({ children: draft.children.includes(item.id) ? draft.children.filter((child) => child !== item.id) : [...draft.children, item.id] })}><TypeIcon icon={item.icon} kind={item.id} size={13} />{item.name}</button>)}</div>
    </fieldset>
  </form>;
}

/** What each column of an attribute means: the format is what files, apps and the API read. */
function AttributeGuide() {
  const [open, setOpen] = useState(false);
  return <div className="ty-guide">
    <button type="button" className="as-link-button" aria-expanded={open} onClick={() => setOpen(!open)}><BookOpen size={13} /> {open ? t("Hide how attributes work") : t("How attributes work")}</button>
    {open && <dl>
      <dt>{t("Key")}</dt><dd>{t("The attribute's permanent id: lowercase letters, digits and _ (rated_flow). Files, the API and the apps read values by it, so it does not change once assets have values.")}</dd>
      <dt>{t("Name")}</dt><dd>{t("What people read on the asset's page and in the tables. It can change at any time.")}</dd>
      <dt>{t("Data type")}</dt><dd>{t("Text; Number (with a unit); Choice (one of a list of options); Date (YYYY-MM-DD); Asset (the id of another asset, a link to its page).")}</dd>
      <dt>{t("Unit")}</dt><dd>{t("For numbers only: the engineering unit the value is in (m³/h, kW, bar g).")}</dd>
      <dt>{t("Required")}</dt><dd>{t("An asset without it shows as an incomplete record; nothing is blocked.")}</dd>
      <dt>{t("Inherited")}</dt><dd>{t("A type has its parent's attributes and roles too (shown in grey); change them on the parent and every child type follows.")}</dd>
      <dt>{t("Signal roles")}</dt><dd>{t("Not values but slots for measured signals (flow, discharge pressure). The same signal may fill a role on several assets: a loop's PV is also its transmitter's measurement.")}</dd>
    </dl>}
  </div>;
}

/** The type's icon: the current one and the usual ones, and every icon, grouped, in a larger picker. */
function IconField({ value, onChange }: { value: string; onChange: (icon: string) => void }) {
  const [open, setOpen] = useState(false);
  const usual = ["box", "pump", "valve", "vessel", "column", "exchanger", "compressor", "tank", "instrument", "flame", "gauge", "factory"];
  const shown = usual.includes(value) || !value ? usual : [value, ...usual.slice(0, -1)];
  return <div className="ty-icon-field"><span>{t("Icon")}</span>
    <div className="ty-icons" role="radiogroup" aria-label={t("Icon")}>
      {shown.map((name) => <button key={name} type="button" role="radio" aria-checked={value === name} aria-label={name} title={name} className={value === name ? "active" : ""} onClick={() => onChange(name)}><TypeIcon icon={name} size={15} /></button>)}
      <button type="button" className="ty-icons-more" aria-label={t("More icons")} title={t("More icons")} onClick={() => setOpen(true)}><Plus size={15} /></button>
    </div>
    {open && <IconPicker value={value} onPick={(icon) => { onChange(icon); setOpen(false); }} onClose={() => setOpen(false)} />}
  </div>;
}

function IconPicker({ value, onPick, onClose }: { value: string; onPick: (icon: string) => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const groups = ICON_GROUPS.map((group) => ({ ...group, names: Object.keys(group.icons).filter((name) => !needle || name.includes(needle) || group.label.toLowerCase().includes(needle)) })).filter((group) => group.names.length);
  return <Modal label={t("Choose an icon")} eyebrow={t("Asset type")} title={t("Choose an icon")} description={t("{count} icons, with the process symbols first.", { count: Object.keys(TYPE_ICONS).length })} onClose={onClose} className="ty-icon-picker">
    <div className="ty-icon-search"><label className="as-search"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search icons (pump, flame, truck)")} aria-label={t("Search icons")} /></label></div>
    <div className="ty-icon-groups">{groups.map((group) => <section key={group.label}>
      <h3>{group.label}</h3>
      <div className="ty-icon-grid">{group.names.map((name) => <button key={name} type="button" className={value === name ? "active" : ""} onClick={() => onPick(name)} title={name}><TypeIcon icon={name} size={20} /><small>{name}</small></button>)}</div>
    </section>)}
      {!groups.length && <p className="muted">{t("No icon matches.")}</p>}
    </div>
  </Modal>;
}

/** Options as one comma-separated text, kept as typed until it loses focus. */
function OptionsInput({ value, disabled, onChange }: { value: string[]; disabled: boolean; onChange: (options: string[]) => void }) {
  const [text, setText] = useState(value.join(", "));
  useEffect(() => setText(value.join(", ")), [value]);
  return <input aria-label={t("Options")} value={disabled ? "" : text} disabled={disabled} placeholder={disabled ? "" : t("low, medium, high")} onChange={(event) => setText(event.target.value)} onBlur={() => onChange(text.split(",").map((item) => item.trim()).filter(Boolean))} />;
}
