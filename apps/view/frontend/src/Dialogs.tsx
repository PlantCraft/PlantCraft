import { Dialog, confirmAction, DataTable, PageTabs, errorMessage as message, saveFile } from "@plantcraft/ui";
/** Dialogs of the dashboard page: its config, and its public links. */
import { ArrowDown, ArrowUp, Check, Copy, Download, Globe2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { FolderSelect } from "./FolderDialogs";
import { ALL_VALUES, exportDashboard, PAGE_SECONDS, pageSecondsLabel, REFRESH, refreshLabel, usesVariable, when, WINDOWS, windowLabel } from "./model";
import type { AssetKind, Dashboard, DashboardDraft, Folder, ShareLink, ShareTarget, Variable, VariableOption, Version } from "./types";

type SettingsTab = "general" | "time" | "display" | "variables" | "versions" | "json";

function Versions({ dashboardId, onRestored }: { dashboardId: string; onRestored: (dashboard: Dashboard) => void }) {
  const [items, setItems] = useState<Version[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.versions(dashboardId).then(setItems).catch((err) => setError(message(err))); }, [dashboardId]);
  async function restore(item: Version) {
    if (!await confirmAction(t("Restore version {n}? It is saved again as the newest version; nothing is lost.", { n: item.version }), { confirm: t("Restore") })) return;
    try { onRestored(await api.restore(dashboardId, item.version)); } catch (err) { setError(message(err)); }
  }
  if (error) return <div className="notice notice-error">{error}</div>;
  if (!items) return <p className="muted">{t("Reading the versions…")}</p>;
  return <DataTable rows={items} rowKey={(item) => String(item.version)} label={t("Versions")} empty={t("No saved version yet.")} columns={[
    { key: "version", label: t("Version"), sort: (item) => item.version, render: (item) => <b>{item.version}{item === items[0] ? ` · ${t("current")}` : ""}</b> },
    { key: "saved", label: t("Saved"), sort: (item) => item.saved_at, render: (item) => <>{when(item.saved_at)}<small>{item.saved_by}</small></> },
    { key: "content", label: t("Content"), render: (item) => <>{item.name}<small>{t("{count} panels", { count: item.cards })}{item.pages > 1 ? ` · ${t("{n} pages", { n: item.pages })}` : ""}</small></> },
    { key: "restore", label: <span className="sr-only">{t("Restore")}</span>, render: (item) => item === items[0] ? null : <button type="button" className="button button-secondary button-small" onClick={() => void restore(item)}><RotateCcw size={13} /> {t("Restore")}</button> },
  ]} />;
}

const NAME = /^[A-Za-z][A-Za-z0-9_]{0,29}$/;

/** What is wrong with the variables, in words (none: nothing). */
export function variablesProblem(variables: Variable[]): string {
  const seen = new Set<string>();
  for (const [index, variable] of variables.entries()) {
    if (!NAME.test(variable.name)) return t("A variable's name starts with a letter and has letters, digits and _ only (like loop or unit_2).");
    if (seen.has(variable.name)) return t("Two variables are named {name}.", { name: variable.name });
    seen.add(variable.name);
    if (variable.type === "asset" && !variable.asset_kind) return t("Variable {name}: choose the kind of asset it lists.", { name: variable.name });
    if (variable.type !== "asset" && !(variable.options ?? []).length) return t("Variable {name}: type at least one value.", { name: variable.name });
    if (variable.type === "interval" && (variable.options ?? []).some((option) => !/^\d{1,5}[smhd]$/.test(option))) return t("Variable {name}: time spans look like 15m, 8h or 7d.", { name: variable.name });
    if (variable.parent && !variables.slice(0, index).some((found) => found.name === variable.parent && found.type === "asset")) return t("Variable {name}: its parent must be an asset variable above it.", { name: variable.name });
  }
  return "";
}

/** The values a variable offers now, as its picker shows them. */
function OptionsPreview({ variable }: { variable: Variable }) {
  const [found, setFound] = useState<VariableOption[] | null>(null);
  const key = JSON.stringify(variable);
  useEffect(() => {
    if (variable.type !== "asset" || !variable.asset_kind) { setFound(null); return; }
    const timer = window.setTimeout(() => { api.variableOptions(variable, []).then(setFound).catch(() => setFound([])); }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (variable.type !== "asset") return null;
  if (!found) return <small className="muted">{t("Reading its values…")}</small>;
  return <small className="muted">{found.length ? t("{n} values: {names}", { n: found.length, names: found.slice(0, 6).map((option) => option.text).join(", ") + (found.length > 6 ? "…" : "") }) : t("No asset of this kind yet.")}{variable.parent ? ` ${t("(all of them; on the dashboard, only those under the {parent} picked)", { parent: variable.parent })}` : ""}</small>;
}

/** Dashboard variables (Grafana's): pickers at the top that the cards name as $name. */
export function VariablesEditor({ variables, kinds, cards, onChange }: { variables: Variable[]; kinds: AssetKind[]; cards: DashboardDraft["cards"]; onChange: (variables: Variable[]) => void }) {
  const setAt = (index: number, next: Variable) => onChange(variables.map((old, n) => (n === index ? next : old)));
  const move = (index: number, step: -1 | 1) => {
    const target = index + step;
    if (target < 0 || target >= variables.length) return;
    const next = [...variables];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };
  function add() {
    const used = new Set(variables.map((variable) => variable.name));
    const first = kinds[0]?.kind ?? "";
    let name = first.replace(/[^A-Za-z0-9_]/g, "_").replace(/^[^A-Za-z]+/, "") || "asset";
    for (let n = 2; used.has(name); n += 1) name = `${name.replace(/_\d+$/, "")}_${n}`;
    onChange([...variables, { name, label: first, type: "asset", asset_kind: first || null, multi: false, include_all: false, default: "", options: [] }]);
  }
  async function remove(index: number) {
    const variable = variables[index];
    if (usesVariable(cards, variable.name) && !await confirmAction(t("Panels use ${name}: they will ask for a value it no longer gives. Remove it?", { name: variable.name }), { confirm: t("Remove"), danger: true })) return;
    onChange(variables.filter((_, n) => n !== index));
  }
  return <div className="tc-variables">
    <p className="muted">{t("A variable is a picker at the top of the dashboard: a cooling loop, a unit, a time span. Panels use it as $name (a panel's signals from \"Variable\", ${name} in titles and texts), so one dashboard serves every asset of a kind. A variable may hold several values or All, and a panel can repeat for each value.")}</p>
    {variables.map((variable, index) => {
      const parents = variables.slice(0, index).filter((found) => found.type === "asset");
      return <fieldset key={index} className="tc-variable">
        <legend>${variable.name || "…"}</legend>
        <div className="form-grid">
          <label>{t("Name")}<input required maxLength={30} pattern="[A-Za-z][A-Za-z0-9_]*" value={variable.name} onChange={(event) => setAt(index, { ...variable, name: event.target.value.trim() })} /><small>{t("Panels write it as ${name}.", { name: variable.name || "name" })}</small></label>
          <label>{t("Label")}<input maxLength={60} value={variable.label ?? ""} placeholder={variable.name} onChange={(event) => setAt(index, { ...variable, label: event.target.value })} /><small>{t("Above the picker.")}</small></label>
          <label>{t("Type")}<select value={variable.type} onChange={(event) => {
            const type = event.target.value as Variable["type"];
            setAt(index, { ...variable, type, asset_kind: type === "asset" ? variable.asset_kind ?? kinds[0]?.kind ?? null : null, parent: type === "asset" ? variable.parent : null, options: type === "interval" ? ["1h", "8h", "24h", "7d"] : type === "custom" ? variable.options ?? [] : [], default: "" });
          }}>
            <option value="asset">{t("Assets of a kind")}</option>
            <option value="custom">{t("A list of values")}</option>
            <option value="interval">{t("Time spans")}</option>
          </select></label>
          {variable.type === "asset" && <label>{t("Kind of asset")}<select value={variable.asset_kind ?? ""} onChange={(event) => setAt(index, { ...variable, asset_kind: event.target.value || null, label: !variable.label || variable.label === variable.asset_kind ? event.target.value : variable.label })}>
            {!variable.asset_kind && <option value="">{t("Choose…")}</option>}
            {variable.asset_kind && !kinds.some((kind) => kind.kind === variable.asset_kind) && <option value={variable.asset_kind}>{variable.asset_kind}</option>}
            {kinds.map((kind) => <option key={kind.kind} value={kind.kind}>{t("{kind} ({count} in the plant)", { kind: kind.kind || t("asset"), count: kind.count })}</option>)}
          </select></label>}
          {variable.type === "asset" && parents.length > 0 && <label>{t("Under")}<select value={variable.parent ?? ""} onChange={(event) => setAt(index, { ...variable, parent: event.target.value || null })}>
            <option value="">{t("Any: every asset of the kind")}</option>
            {parents.map((found) => <option key={found.name} value={found.name}>{t("The {label} picked (${name})", { label: found.label || found.name, name: found.name })}</option>)}
          </select><small>{t("Chained pickers: a unit, then its loops.")}</small></label>}
          {variable.type !== "asset" && <label className="tc-wide">{variable.type === "interval" ? t("Time spans") : t("Values")}<input required value={(variable.options ?? []).join(", ")} placeholder={variable.type === "interval" ? "1h, 8h, 24h, 7d" : "FIC-101, FIC-102"} onChange={(event) => setAt(index, { ...variable, options: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /><small>{variable.type === "interval" ? t("Separated by commas: 15m, 8h, 7d. Panels use it as their time span.") : t("Separated by commas. Panels use it inside a signal id, like ${name}.PV.", { name: variable.name })}</small></label>}
          <label>{t("Default")}<input maxLength={300} value={variable.default ?? ""} placeholder={t("The first value")} onChange={(event) => setAt(index, { ...variable, default: event.target.value.trim() })} /><small>{variable.include_all ? t("{all} for All.", { all: ALL_VALUES }) : t("An asset id or a value.")}</small></label>
          {variable.type !== "interval" && <div className="tc-wide tc-inline">
            <label className="tc-toggle"><input type="checkbox" checked={Boolean(variable.multi)} onChange={(event) => setAt(index, { ...variable, multi: event.target.checked })} /><span>{t("Several values at once")}</span></label>
            <label className="tc-toggle"><input type="checkbox" checked={Boolean(variable.include_all)} onChange={(event) => setAt(index, { ...variable, include_all: event.target.checked })} /><span>{t("Offer All")}</span></label>
          </div>}
          <div className="tc-wide"><OptionsPreview variable={variable} /></div>
        </div>
        <div className="tc-variable-tools">
          <button type="button" className="icon-button" aria-label={t("Move up")} title={t("Move up")} disabled={!index} onClick={() => move(index, -1)}><ArrowUp size={14} /></button>
          <button type="button" className="icon-button" aria-label={t("Move down")} title={t("Move down")} disabled={index === variables.length - 1} onClick={() => move(index, 1)}><ArrowDown size={14} /></button>
          <button type="button" className="icon-button danger" aria-label={t("Remove variable")} title={t("Remove variable")} onClick={() => remove(index)}><Trash2 size={14} /></button>
        </div>
      </fieldset>;
    })}
    <button type="button" className="button button-secondary" disabled={variables.length >= 10} onClick={add}><Plus size={15} /> {t("Add a variable")}</button>
  </div>;
}

/** The dashboard's Config: General, Time, Display, Variables, Versions and JSON. Outside the editor it
 * saves at once; inside, it changes the draft the editor saves. */
export function SettingsDialog({ draft, folders, dashboardId, onApply, onRestored, onClose }: {
  draft: DashboardDraft; folders: Folder[]; dashboardId: string | null;
  onApply: (draft: DashboardDraft) => void; onRestored: (dashboard: Dashboard) => void; onClose: () => void;
}) {
  const [value, setValue] = useState(draft);
  const [tab, setTab] = useState<SettingsTab>("general");
  const [kinds, setKinds] = useState<AssetKind[]>([]);
  const [tagText, setTagText] = useState(draft.tags.join(", "));
  const [error, setError] = useState("");
  useEffect(() => { api.assetKinds().then(setKinds).catch(() => setKinds([])); }, []);
  const tabs: Array<[SettingsTab, string]> = [["general", t("General")], ["time", t("Time")], ["display", t("Display")], ["variables", t("Variables")], ...(dashboardId ? [["versions", t("Versions")] as [SettingsTab, string]] : []), ["json", t("JSON")]];
  function download() {
    saveFile(`${value.name.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "") || "dashboard"}.json`, exportDashboard(value), "application/json");
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const problem = variablesProblem(value.variables);
    if (problem) { setTab("variables"); setError(problem); return; }
    // The old single asset picker is the first asset variable now (the server derives it too).
    const context_kind = value.variables.find((variable) => variable.type === "asset")?.asset_kind ?? null;
    onApply({ ...value, context_kind, tags: tagText.split(",").map((tag) => tag.trim()).filter(Boolean) });
  }
  return <Dialog title={t("Config of {name}", { name: draft.name })} onClose={onClose} onSubmit={submit}>
      <div className="tc-config">
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <PageTabs label={t("Config sections")} tabs={tabs.map(([to, label]) => ({ to, label, active: to === tab }))} href={(to) => `#${to}`} navigate={(to) => setTab(to as SettingsTab)} />
      {tab === "general" && <div className="form-grid tc-settings">
        <label>{t("Name")}<input required maxLength={120} value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} /></label>
        <label>{t("Folder")}<FolderSelect folders={folders} value={value.folder_id} onChange={(folder_id) => setValue({ ...value, folder_id })} /><small>{t("Its folder decides who sees and edits it.")}</small></label>
        <label className="tc-wide">{t("Description")}<input maxLength={500} value={value.description} onChange={(event) => setValue({ ...value, description: event.target.value })} /></label>
        <label className="tc-wide">{t("Labels")}<input maxLength={340} value={tagText} placeholder={t("Unit 100, shift, valves")} onChange={(event) => setTagText(event.target.value)} /><small>{t("Separated by commas; the list finds dashboards by them.")}</small></label>
      </div>}
      {tab === "time" && <div className="form-grid tc-settings">
        <label>{t("Opens with")}<select value={value.default_window ?? ""} onChange={(event) => setValue({ ...value, default_window: event.target.value || null })}>
          <option value="">{t("Each panel's own window")}</option>
          {WINDOWS.map((window) => <option key={window} value={window}>{t("Last {window}", { window: windowLabel(window) })}</option>)}
        </select><small>{t("The Time picker's first value; anyone can change it while looking.")}</small></label>
        <label>{t("Refresh")}<select value={value.refresh_seconds} onChange={(event) => setValue({ ...value, refresh_seconds: Number(event.target.value) })}>{REFRESH.map((seconds) => <option key={seconds} value={seconds}>{refreshLabel(seconds)}</option>)}</select></label>
        <label className="tc-wide">{t("Turn pages in full screen")}
          <select value={value.page_seconds} disabled={value.pages.length < 2} onChange={(event) => setValue({ ...value, page_seconds: Number(event.target.value) })}>{PAGE_SECONDS.map((seconds) => <option key={seconds} value={seconds}>{pageSecondsLabel(seconds)}</option>)}</select>
          <small>{value.pages.length < 2 ? t("With two pages or more (Edit › Add page), full screen and public links can go through them.") : t("In full screen and on public links, show the next page every so often: a control room screen goes through every page.")}</small>
        </label>
      </div>}
      {tab === "display" && <div className="form-grid tc-settings">
        <label className="tc-wide tc-check"><input type="checkbox" checked={value.shared_cursor} onChange={(event) => setValue({ ...value, shared_cursor: event.target.checked })} /><span><b>{t("Shared cursor")}</b><small>{t("Hovering a trend marks the same moment on the dashboard's other trends.")}</small></span></label>
        <label className="tc-wide tc-check"><input type="checkbox" checked={value.kiosk} onChange={(event) => setValue({ ...value, kiosk: event.target.checked })} /><span><b>{t("Kiosk in full screen")}</b><small>{t("Full screen and public links show the panels only, without the toolbar: a control room screen. Esc leaves it.")}</small></span></label>
      </div>}
      {tab === "variables" && <VariablesEditor variables={value.variables} kinds={kinds} cards={value.cards} onChange={(variables) => setValue({ ...value, variables })} />}
      {tab === "versions" && dashboardId && <Versions dashboardId={dashboardId} onRestored={onRestored} />}
      {tab === "json" && <div className="tc-json">
        <p className="muted">{t("The dashboard as a file: take it to another installation and start a new dashboard from it there (New dashboard › A dashboard file). Its panels name signals and assets by id, so they show the same data where the ids are the same.")}</p>
        <button type="button" className="button button-secondary" onClick={download}><Download size={15} /> {t("Download the file")}</button>
      </div>}
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>{!["versions", "json"].includes(tab) && <button className="button button-primary" type="submit">{dashboardId ? t("Save") : t("Apply")}</button>}</footer>
      </div>
  </Dialog>;
}

/** The public links of a dashboard, of a report (its HTML page, read when opened) or of a diagram. */
export function ShareDialog({ dashboardId, name, onClose, target = "dashboard", isAdmin = false }: { dashboardId: string; name: string; onClose: () => void; target?: ShareTarget; isAdmin?: boolean }) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [label, setLabel] = useState("");
  const [days, setDays] = useState<number | null>(90);
  const [created, setCreated] = useState<ShareLink | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.shares(dashboardId, target).then(setLinks).catch((err) => setError(message(err))); }, [dashboardId, target]);
  const url = created?.path ? `${window.location.origin}${created.path}` : "";

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const link = await api.createShare(dashboardId, label, target, days);
      setCreated(link);
      setCopied(false);
      setLinks([link, ...(links ?? [])]);
      setLabel("");
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // No clipboard (plain http): select the text for Ctrl+C.
      (document.getElementById("share-url") as HTMLInputElement | null)?.select();
    }
  }
  async function revoke(link: ShareLink) {
    if (!await confirmAction(t("Revoke this link? Screens showing it stop at once."), { confirm: t("Revoke"), danger: true })) return;
    try {
      await api.revokeShare(dashboardId, link.share_id, target);
      setLinks((links ?? []).filter((item) => item.share_id !== link.share_id));
      if (created?.share_id === link.share_id) setCreated(null);
    } catch (err) { setError(message(err)); }
  }
  return <Dialog wide title={<><Globe2 size={18} /> {t("Public links of {name}", { name })}</>} onClose={onClose}>
      <p className="muted">{target === "report"
        ? t("Anyone with a link reads this report as a web page, without signing in: its sections, its navigation and charts that show their values on hover, read again each time the link is opened. A link opens this report only, and stops working when you revoke it.")
        : target === "diagram"
        ? t("Anyone with a link sees this process display live, read-only and without signing in, and can play its window back on the time bar. Add ?screen=1 to the link for a control room screen: the process display alone. A link opens this process display only, and stops working when you revoke it.")
        : t("Anyone with a link sees this dashboard, read-only and without signing in: for a control room screen or a colleague without an account. A link opens this dashboard only, and stops working when you revoke it.")}</p>
      {error && <div className="notice notice-error">{error}</div>}
      {created && url && <div className="tc-share-new">
        <label>{t("Copy the link now: it is shown only once.")}<input id="share-url" readOnly value={url} onFocus={(event) => event.target.select()} /></label>
        <button type="button" className="button button-primary" onClick={copy}>{copied ? <><Check size={15} /> {t("Copied")}</> : <><Copy size={15} /> {t("Copy")}</>}</button>
      </div>}
      <form className="tc-share-form" onSubmit={create}>
        <input aria-label={t("Link label")} placeholder={t("Label, like Control room screen")} maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} />
        <select aria-label={t("Opens for")} value={days ?? ""} onChange={(event) => setDays(event.target.value ? Number(event.target.value) : null)}>
          {LINK_DAYS.map((value) => <option key={value} value={value}>{t("{count} days", { count: value })}</option>)}
          {isAdmin && <option value="">{t("Until revoked")}</option>}
        </select>
        <button className="button button-secondary" type="submit" disabled={busy}>{t("Create link")}</button>
      </form>
      {links && <DataTable rows={links} rowKey={(link) => link.share_id} label={t("Public links of {name}", { name })} initialSort={{ key: "created", descending: true }} empty={t("No links yet.")} columns={[
        { key: "label", label: t("Link"), sort: (link) => link.label, render: (link) => <b>{link.label || t("Untitled link")}</b> },
        { key: "created", label: t("Created"), className: "nowrap", sort: (link) => link.created_at, render: (link) => when(link.created_at) },
        { key: "by", label: t("Created by"), className: "nowrap", sort: (link) => link.created_by ?? "", render: (link) => link.created_by || "—", filter: { value: (link) => link.created_by ?? "" } },
        { key: "used", label: t("Last opened"), className: "nowrap", sort: (link) => link.last_used_at, render: (link) => (link.last_used_at ? when(link.last_used_at) : t("never")) },
        { key: "expires", label: t("Expires"), className: "nowrap", sort: (link) => link.expires_at ?? "9999", render: (link) => (link.expires_at ? when(link.expires_at) : t("when revoked")) },
        { key: "actions", label: <span className="sr-only">{t("Revoke")}</span>, render: (link) => <button className="icon-button danger" aria-label={t("Revoke")} title={t("Revoke")} onClick={() => revoke(link)}><Trash2 size={15} /></button> },
      ]} />}
  </Dialog>;
}

/** What a public link opens, in words. */
function kindOf(link: ShareLink): string {
  return link.target === "report" ? t("Report") : link.target === "diagram" ? t("Process display") : t("Dashboard");
}

/** How long a new link opens (2026-10-27): 90 days unless its author picks otherwise. */
const LINK_DAYS = [7, 30, 90, 365];

/** Every public link of the installation that still opens something, for an administrator to
 * review and revoke: a link forgotten in an old e-mail is found here. */
export function AllLinksDialog({ onClose }: { onClose: () => void }) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.allShares().then(setLinks).catch((err) => setError(message(err))); }, []);
  async function revoke(link: ShareLink) {
    if (!await confirmAction(t("Revoke this link? Screens showing it stop at once."), { confirm: t("Revoke"), danger: true })) return;
    try {
      await api.revokeAnyShare(link.share_id);
      setLinks((links ?? []).filter((item) => item.share_id !== link.share_id));
    } catch (err) { setError(message(err)); }
  }
  return <Dialog wide title={<><Globe2 size={18} /> {t("Public links of this installation")}</>} onClose={onClose}>
    <p className="muted">{t("Every link that opens a dashboard, a report or a process display without signing in, until it expires or is revoked.")}</p>
    {error && <div className="notice notice-error">{error}</div>}
    {links && <DataTable rows={links} rowKey={(link) => link.share_id} label={t("Public links of this installation")} initialSort={{ key: "created", descending: true }} empty={t("No public links.")} columns={[
      { key: "opens", label: t("Opens"), sort: (link) => link.name ?? "", render: (link) => <><b>{link.name}</b>{link.label ? <span className="muted"> · {link.label}</span> : null}</> },
      { key: "kind", label: t("Kind"), className: "nowrap", sort: (link) => kindOf(link), render: kindOf, filter: { value: kindOf } },
      { key: "created", label: t("Created"), className: "nowrap", sort: (link) => link.created_at, render: (link) => when(link.created_at) },
      { key: "by", label: t("Created by"), className: "nowrap", sort: (link) => link.created_by ?? "", render: (link) => link.created_by || "—", filter: { value: (link) => link.created_by ?? "" } },
      { key: "used", label: t("Last opened"), className: "nowrap", sort: (link) => link.last_used_at, render: (link) => (link.last_used_at ? when(link.last_used_at) : t("never")) },
      { key: "expires", label: t("Expires"), className: "nowrap", sort: (link) => link.expires_at ?? "9999", render: (link) => (link.expires_at ? when(link.expires_at) : t("when revoked")) },
      { key: "actions", label: <span className="sr-only">{t("Revoke")}</span>, render: (link) => <button className="icon-button danger" aria-label={t("Revoke")} title={t("Revoke")} onClick={() => revoke(link)}><Trash2 size={15} /></button> },
    ]} />}
  </Dialog>;
}
