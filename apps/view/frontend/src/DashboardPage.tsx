/** One dashboard: the grid of cards, the asset and time pickers, refresh, full screen and the editor.
 * The same page serves a public link (read-only, no sign-in) with `token`. */
import { ArrowLeft, ArrowRight, CopyPlus, FilePlus2, Globe2, Maximize2, Minimize2, Pencil, Plus, RefreshCw, Save, Settings2, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { confirmAction, ApiError, AssistantTitleButton, CardGrid, MultiSelect, PageTabs, errorMessage as message, formatDate, useAssistantPage, type GridCell } from "@plantcraft/ui";
import { api, publicApi, type CardSource } from "./api";
import { CardEditor } from "./CardEditor";
import { CardView } from "./CardView";
import { CursorContext, type SharedCursor } from "./cursor";
import { ShareDialog, SettingsDialog } from "./Dialogs";
import { dropNewDraft, takeNewDraft } from "./FolderDialogs";
import { t } from "./i18n";
import { addPage, ALL_VALUES, cardsOn, cellsOf, currentPage, defaultCard, draftOf, MAX_CARDS_PER_PAGE, MAX_PAGES, minHeight, movePage, pageSecondsLabel, placeNew, readView, refreshLabel, removePage, renamePage, repeatCards, usesVariable, WINDOWS, windowLabel, withCells, writeView, type ViewState } from "./model";
import { navigate } from "./nav";
import type { Card, Dashboard, DashboardDraft, Folder, Me, Variable, VariableOption } from "./types";
import { useVariables, variableLabel } from "./variables";
import { ErrorBox, Link, Loading } from "./ui";

// A new dashboard just saved: the page it opens on says so.
let justCreated = false;

/** The cursor shared by a dashboard's time charts, redrawn at most once a frame. */
function useCursor(enabled: boolean): SharedCursor | null {
  const [state, setState] = useState<{ at: string | null; from: string | null }>({ at: null, from: null });
  const frame = useRef(0);
  const set = useCallback((at: string | null, from: string) => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setState({ at, from }));
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  return useMemo(() => (enabled ? { ...state, set } : null), [enabled, state, set]);
}

function useView(): [ViewState, (next: Partial<ViewState>) => void] {
  const [view, setView] = useState(() => readView(window.location.search));
  const update = useCallback((next: Partial<ViewState>) => {
    setView((current) => {
      const merged = { ...current, ...next };
      window.history.replaceState({}, "", `${window.location.pathname}${writeView(merged)}`);
      return merged;
    });
  }, []);
  return [view, update];
}

/** A variable's picker at the top: one value (a list), or several (checkboxes), with All. */
function VariablePicker({ variable, options, picked, onChange }: { variable: Variable; options: VariableOption[]; picked: string[]; onChange: (values: string[]) => void }) {
  const label = variableLabel(variable);
  const groups = useMemo(() => {
    const byGroup = new Map<string, VariableOption[]>();
    for (const option of options) byGroup.set(option.group ?? "", [...(byGroup.get(option.group ?? "") ?? []), option]);
    return [...byGroup.entries()];
  }, [options]);
  const all = picked.includes(ALL_VALUES);
  if (variable.multi) {
    return <div className="tc-context tc-variable-picker"><span className="pc-overline">{label}</span>
      <MultiSelect label={label} allLabel={variable.include_all ? t("All") : t("Choose…")} options={options.map((option) => ({ id: option.value, label: option.group ? `${option.text} · ${option.group}` : option.text }))}
        value={all ? [] : picked} onChange={(values) => onChange(!values.length || (variable.include_all && values.length === options.length) ? (variable.include_all ? [ALL_VALUES] : options.slice(0, 1).map((option) => option.value)) : values)} />
    </div>;
  }
  const item = (option: VariableOption) => <option key={option.value} value={option.value}>{option.text}{option.description ? ` · ${option.description}` : ""}</option>;
  return <label className="tc-context tc-variable-picker">
    <span className="pc-overline">{label}</span>
    <select aria-label={label} value={picked[0] ?? ""} onChange={(event) => onChange(event.target.value ? [event.target.value] : [])}>
      {!options.length && <option value="">{t("None")}</option>}
      {variable.include_all && <option value={ALL_VALUES}>{t("All")}</option>}
      {groups.map(([group, items]) => (group ? <optgroup key={group} label={group}>{items.map(item)}</optgroup> : items.map(item)))}
    </select>
  </label>;
}

export function DashboardPage({ dashboardId, token, me }: { dashboardId?: string; token?: string; me?: Me }) {
  const isPublic = Boolean(token);
  // "new": the New dashboard dialog's draft, saved only when the editor saves it.
  const isNew = dashboardId === "new" && !isPublic;
  const mayEdit = Boolean(me?.can_edit) && !isPublic;
  const [saved, setSaved] = useState<Dashboard | null>(null);
  // A dashboard the suite keeps (Suite health) is read-only: copy it to change it; a folder's
  // editors are the only ones to change its dashboards.
  const canEdit = mayEdit && !saved?.builtin && saved?.can_edit !== false;
  const [folders, setFolders] = useState<Folder[]>([]);
  const [draft, setDraft] = useState<DashboardDraft | null>(null);
  const [view, setView] = useView();
  const [tick, setTick] = useState(0);
  const [stamp, setStamp] = useState(() => new Date());
  const [editing, setEditing] = useState<{ card: Card; isNew: boolean } | null>(null);
  const [settings, setSettings] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const source: CardSource | null = useMemo(() => {
    if (token) return publicApi.source(token);
    if (dashboardId === "new") return { card: () => Promise.reject(new Error(t("Panel not found."))), options: (variable, parents) => api.variableOptions(variable, parents) };
    return dashboardId ? api.source(dashboardId) : null;
  }, [token, dashboardId]);

  useEffect(() => {
    if (isNew) {
      const held = takeNewDraft();
      if (!held) { navigate("/dashboards"); return; }
      setSaved({ ...held, dashboard_id: "", can_edit: true });
      setDraft(held);
      return;
    }
    const load = token ? publicApi.dashboard(token) : api.dashboard(dashboardId ?? "");
    load.then((found) => {
      setSaved(found);
      if (justCreated) { justCreated = false; setNotice(t("Saved.")); }
      const asked = readView(window.location.search);
      if (asked.edit && mayEdit && !found.builtin && found.can_edit !== false) setDraft(draftOf(found));
      if (!asked.window && found.default_window) setView({ window: found.default_window });
    }).catch((err) => setError(message(err)));
  }, [token, dashboardId, mayEdit, isNew, setView]);
  useEffect(() => { if (mayEdit) api.folders().then(setFolders).catch(() => setFolders([])); }, [mayEdit]);

  const shown = useMemo(() => draft ?? (saved ? draftOf(saved) : null), [draft, saved]);
  const cursor = useCursor(Boolean(shown?.shared_cursor));
  // Leaving the browser's full screen (Esc) leaves the dashboard's too: a kiosk has no button.
  useEffect(() => {
    const left = () => { if (!document.fullscreenElement && readView(window.location.search).screen) setView({ screen: false }); };
    document.addEventListener("fullscreenchange", left);
    return () => document.removeEventListener("fullscreenchange", left);
  }, [setView]);
  // The pickers: a draft's variables (maybe unsaved) are read with the editor's token, a saved
  // dashboard's through its own page (or its public link).
  const editingVariables = Boolean(draft) || isNew;
  const fetchOptions = useMemo(() => (editingVariables ? (variable: Variable, parents: string[]) => api.variableOptions(variable, parents) : source ? source.options : null), [editingVariables, source]);
  const fixVars = useCallback((picked: Record<string, string[]>) => setView({ vars: picked }), [setView]);
  const variables = shown?.variables ?? [];
  const resolved = useVariables(variables, fetchOptions, view.vars, fixVars);

  const refresh = useCallback(() => { setTick((value) => value + 1); setStamp(new Date()); }, []);
  useEffect(() => {
    const seconds = shown?.refresh_seconds ?? 0;
    if (!seconds || draft) return;
    const timer = window.setInterval(refresh, seconds * 1000);
    return () => window.clearInterval(timer);
  }, [shown?.refresh_seconds, draft, refresh]);

  // Full screen and public links turn to the next page every `page_seconds` (a control room TV).
  const pageCount = shown?.pages.length ?? 0;
  const pageSeconds = shown?.page_seconds ?? 0;
  useEffect(() => {
    if (!pageSeconds || pageCount < 2 || draft || !(view.screen || isPublic) || !shown) return;
    const timer = window.setInterval(() => {
      const pages = shown.pages;
      const at = pages.findIndex((page) => page.page_id === currentPage(pages, readView(window.location.search).page)?.page_id);
      setView({ page: pages[(at + 1) % pages.length].page_id });
    }, pageSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [pageSeconds, pageCount, draft, view.screen, isPublic, shown, setView]);

  useEffect(() => {
    document.body.classList.toggle("tc-screen", view.screen || isPublic);
    return () => document.body.classList.remove("tc-screen");
  }, [view.screen, isPublic]);

  // While editing, cards are drawn from the draft with the editor's own token.
  const drawSource: CardSource | null = useMemo(() => {
    if (!draft) return source;
    return {
      card: (cardId, vars, window) => {
        const card = draft.cards.find((item) => item.card_id === cardId);
        return card ? api.preview(card, draft.variables, vars, window) : Promise.reject(new Error(t("Panel not found.")));
      },
      options: (variable, parents) => api.variableOptions(variable, parents),
    };
  }, [draft, source]);

  // What the assistant can do on this page (the button at the top opens it; not on a public screen).
  // View's works for a dashboard (app.toml: explain it, what changed in the period) and one task.
  useAssistantPage(shown && !isPublic && !view.screen ? {
    page: "dashcraft:dashboard", subject: isNew ? undefined : `dashboard:${dashboardId}`,
    view: { window: view.window ?? "each card's own", cards: shown.cards.slice(0, 30).map((card) => `${(card.title || card.kind).slice(0, 80)}: ${card.items.map((item) => item.signal_id || item.asset_id || "").filter(Boolean).slice(0, 8).join(", ")}`) },
    title: shown.name, place: t("Dashboards › {name}", { name: shown.name }),
    context: [`Dashboard ${shown.name}${shown.description ? `: ${shown.description}` : ""}.`,
      `Cards: ${shown.cards.map((card) => `${card.title || card.kind} (${card.items.map((item) => item.label || item.signal_id || item.asset_id || "").filter(Boolean).join(", ")})`).join("; ")}.`,
      `Time window: ${view.window ?? "each panel's own"}.`].join("\n"),
  } : null);
  if (error && !saved) return <ErrorBox text={error} />;
  if (!saved || !shown || !drawSource || !resolved.ready) return <Loading />;

  const startEditing = () => { setDraft(draftOf(saved)); setView({ edit: true, screen: false }); };
  const stopEditing = () => {
    if (isNew) { dropNewDraft(); navigate("/dashboards"); return; }
    setDraft(null); setView({ edit: false }); setNotice("");
  };
  const setCards = (cards: Card[]) => setDraft((current) => (current ? { ...current, cards } : current));

  async function save(force = false) {
    if (!draft || !dashboardId) return;
    setSaving(true);
    setError("");
    try {
      if (isNew) {
        const created = await api.create(draft);
        dropNewDraft();
        justCreated = true;
        navigate(`/d/${created.dashboard_id}${writeView({ ...view, edit: false })}`);
        return;
      }
      const result = await api.save(dashboardId, draft, force ? null : saved?.updated_at);
      setSaved(result);
      setDraft(null);
      setView({ edit: false });
      setNotice(t("Saved."));
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        if (await confirmAction(`${err.message}\n\n${t("Replace their version with yours?")}`, { confirm: t("Replace") })) return save(true);
      }
      setError(message(err));
    } finally { setSaving(false); }
  }
  /** Config outside the editor saves at once (the editor's own Config changes the draft). */
  async function applySettings(next: DashboardDraft) {
    if (draft) { setDraft(next); setSettings(false); return; }
    if (!saved || !dashboardId) return;
    try {
      const result = await api.save(dashboardId, { ...draftOf(saved), ...next, cards: saved.cards, pages: next.pages }, saved.updated_at);
      setSaved(result);
      setSettings(false);
      setNotice(t("Saved."));
      if (next.default_window !== saved.default_window) setView({ window: next.default_window });
    } catch (err) { setError(message(err)); }
  }
  function toggleScreen() {
    const next = !view.screen;
    setView({ screen: next });
    try {
      if (next) void document.documentElement.requestFullscreen?.();
      else if (document.fullscreenElement) void document.exitFullscreen();
    } catch { /* full screen is optional */ }
  }
  // An asset variable the cards use with nothing to pick: say why the cards are empty.
  const emptyPicker = variables.find((variable) => variable.type === "asset" && !(resolved.options[variable.name] ?? []).length && usesVariable(shown.cards, variable.name));
  const page = currentPage(shown.pages, view.page);
  const cards = cardsOn(shown, page);
  const pageFull = cards.length >= MAX_CARDS_PER_PAGE;
  const newCard = (existing: Card[]): Card => ({ ...defaultCard("stat", existing), ...(page && shown.pages.length ? { page_id: page.page_id } : {}) });
  // Editing shows each card once, to move and resize it; viewing repeats cards for their variable.
  const laid = draft ? { shown: cards.map((card) => ({ card, key: card.card_id, values: resolved.values, texts: resolved.texts })), cells: cellsOf(cards) } : repeatCards(cards, resolved.values, resolved.texts);
  const byKey = new Map(laid.shown.map((item) => [item.key, item]));
  const kindOf = new Map(cards.map((card) => [card.card_id, card.kind]));
  function duplicate(card: Card) {
    if (!draft) return;
    const onPage = cardsOn(draft, page);
    const copy = placeNew({ ...card, card_id: defaultCard(card.kind, draft.cards).card_id }, onPage);
    setCards([...draft.cards, copy]);
  }
  const editPages = (next: typeof draft) => setDraft(next);
  function newPage() {
    if (!draft) return;
    const [next, pageId] = addPage(draft);
    setDraft(next);
    setView({ page: pageId });
  }
  async function deletePage() {
    if (!draft || !page) return;
    const count = cardsOn(draft, page).length;
    if (count && !await confirmAction(t("Remove the page {name} and its {n} panels?", { name: page.name, n: count }), { confirm: t("Remove"), danger: true })) return;
    setDraft(removePage(draft, page.page_id));
    setView({ page: null });
  }

  const kiosk = shown.kiosk && (view.screen || isPublic) && !draft;
  return <CursorContext.Provider value={cursor}><div className={`tc-dashboard ${view.screen || isPublic ? "tc-dashboard-screen" : ""}${kiosk ? " tc-kiosk" : ""}`}>
    {kiosk && !isPublic && <button type="button" className="icon-button tc-kiosk-exit" title={t("Leave full screen")} aria-label={t("Leave full screen")} onClick={toggleScreen}><Minimize2 size={16} /></button>}
    <div className="tc-head">
      <div className="tc-title">
        {!isPublic && !view.screen && <Link to="/dashboards" className="breadcrumb">{t("Dashboards")}</Link>}
        <h1>{shown.name}{draft && <span className="tag">{t("Editing")}</span>}{!isPublic && !view.screen && <AssistantTitleButton />}</h1>
      </div>
      <div className="tc-toolbar">
        {variables.map((variable) => <VariablePicker key={variable.name} variable={variable} options={resolved.options[variable.name] ?? []} picked={resolved.picked[variable.name] ?? []}
          onChange={(values) => setView({ vars: { ...resolved.picked, [variable.name]: values } })} />)}
        <label className="tc-context"><span className="pc-overline">{t("Time")}</span>
          <select aria-label={t("Time window")} value={view.window ?? ""} onChange={(event) => setView({ window: event.target.value || null })}>
            <option value="">{t("Each panel's own")}</option>
            {view.window && !WINDOWS.includes(view.window) && <option value={view.window}>{t("Last {window}", { window: windowLabel(view.window) })}</option>}
            {WINDOWS.map((window) => <option key={window} value={window}>{t("Last {window}", { window: windowLabel(window) })}</option>)}
          </select>
        </label>
        <button className="button button-secondary button-icon" title={t("Refresh now ({auto})", { auto: refreshLabel(shown.refresh_seconds) })} aria-label={t("Refresh now")} onClick={refresh}><RefreshCw size={16} /></button>
        <button className="button button-secondary button-icon" title={view.screen ? t("Leave full screen") : t("Full screen")} aria-label={view.screen ? t("Leave full screen") : t("Full screen")} onClick={toggleScreen}>{view.screen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
        {mayEdit && !draft && !view.screen && <>
          {me?.public_links && (canEdit || saved.builtin) && <button className="button button-secondary" onClick={() => setSharing(true)}><Globe2 size={15} /> {t("Share")}</button>}
          {canEdit && <button className="button button-secondary" onClick={() => setSettings(true)}><Settings2 size={15} /> {t("Config")}</button>}
          {canEdit && <button className="button button-primary" onClick={startEditing}><Pencil size={15} /> {t("Edit")}</button>}
        </>}
        {draft && <>
          <button className="button button-secondary" onClick={() => setSettings(true)}><Settings2 size={15} /> {t("Config")}</button>
          <button className="button button-secondary" onClick={() => setEditing({ card: newCard(draft.cards), isNew: true })} disabled={pageFull} title={pageFull ? t("A page has at most {n} panels: add a page.", { n: MAX_CARDS_PER_PAGE }) : undefined}><Plus size={15} /> {t("Add panel")}</button>
          <button className="button button-secondary" onClick={stopEditing}><X size={15} /> {t("Cancel")}</button>
          <button className="button button-primary" onClick={() => save()} disabled={saving}><Save size={15} /> {saving ? t("Saving…") : t("Save")}</button>
        </>}
      </div>
    </div>
    {error && <ErrorBox text={error} />}
    {notice && !draft && <div className="notice notice-ok" role="status">{notice}</div>}
    {emptyPicker && <div className="notice">{t("PlantCraft has no asset of kind {kind} for {name}.", { kind: emptyPicker.asset_kind ?? "", name: variableLabel(emptyPicker) })}</div>}
    {(shown.pages.length > 1 || draft) && <div className="tc-pages">
      {shown.pages.length > 1 && <PageTabs label={t("Pages of {name}", { name: shown.name })} tabs={shown.pages.map((item) => ({ to: item.page_id, label: item.name, active: item.page_id === page?.page_id }))}
        href={(to) => `${window.location.pathname}${writeView({ ...view, page: to })}`} navigate={(to) => setView({ page: to })} />}
      {draft && <div className="tc-page-tools">
        {page && draft.pages.length > 0 && <>
          <label className="tc-page-name"><span className="sr-only">{t("Page name")}</span>
            <input aria-label={t("Page name")} maxLength={60} required value={page.name} onChange={(event) => editPages(renamePage(draft, page.page_id, event.target.value))} /></label>
          <button className="icon-button" aria-label={t("Move page earlier")} title={t("Move page earlier")} onClick={() => editPages(movePage(draft, page.page_id, -1))}><ArrowLeft size={14} /></button>
          <button className="icon-button" aria-label={t("Move page later")} title={t("Move page later")} onClick={() => editPages(movePage(draft, page.page_id, 1))}><ArrowRight size={14} /></button>
          <button className="icon-button danger" aria-label={t("Remove page")} title={t("Remove page")} onClick={deletePage}><Trash2 size={14} /></button>
        </>}
        <button className="button button-secondary" onClick={newPage} disabled={draft.pages.length >= MAX_PAGES}><FilePlus2 size={15} /> {t("Add page")}</button>
      </div>}
    </div>}
    {!cards.length && <div className="panel tc-empty-list">
      <h2>{shown.pages.length > 1 ? t("This page has no panels") : t("This dashboard has no panels")}</h2>
      <p className="muted">{canEdit ? t("Add KPIs, trends, bars and tables over any signal of the plant.") : t("An editor has not added panels yet.")}</p>
      {canEdit && !draft && <button className="button button-primary" onClick={() => { startEditing(); setEditing({ card: newCard([]), isNew: true }); }}><Plus size={15} /> {t("Add panel")}</button>}
      {draft && <button className="button button-primary" onClick={() => setEditing({ card: newCard(draft.cards), isNew: true })}><Plus size={15} /> {t("Add panel")}</button>}
    </div>}
    {cards.length > 0 && <CardGrid className="tc-grid" label={t("Panels")} cells={laid.cells} editing={Boolean(draft)}
      onChange={(cells: GridCell[]) => { if (draft) setCards(withCells(draft.cards, cells)); }}
      limits={(id) => ({ minW: 2, minH: minHeight(kindOf.get(id.split("~")[0]) ?? "trend") })}
      render={(id) => {
        const item = byKey.get(id);
        if (!item) return null;
        const card = item.card;
        return <CardView card={card} source={drawSource} vars={item.values} texts={item.texts} window={view.window} tick={tick} editing={Boolean(draft)} copy={item.key !== card.card_id}
          actions={draft && <span className="tc-card-actions pc-cards-nodrag">
            <button type="button" className="icon-button" aria-label={t("Duplicate")} title={t("Duplicate")} disabled={pageFull} onClick={() => duplicate(card)}><CopyPlus size={14} /></button>
            <button type="button" className="icon-button" aria-label={t("Edit panel")} title={t("Edit panel")} onClick={() => setEditing({ card, isNew: false })}><Pencil size={14} /></button>
            <button type="button" className="icon-button danger" aria-label={t("Remove panel")} title={t("Remove panel")} onClick={() => setCards(draft.cards.filter((found) => found.card_id !== card.card_id))}><Trash2 size={14} /></button>
          </span>} />;
      }} />}
    <footer className="tc-foot"><small>{isPublic ? t("Read-only dashboard shared from View.") : ""} {t("Read at {time}", { time: formatDate(stamp, { timeStyle: "medium" }) })} · {refreshLabel(shown.refresh_seconds)}{shown.pages.length > 1 && shown.page_seconds > 0 && (view.screen || isPublic) ? ` · ${t("Next page: {every}", { every: pageSecondsLabel(shown.page_seconds).toLowerCase() })}` : ""}</small></footer>
    {editing && draft && <CardEditor initial={editing.card} isNew={editing.isNew} variables={draft.variables} values={resolved.values} texts={resolved.texts} pages={draft.pages}
      onClose={() => setEditing(null)}
      onSave={(card) => {
        const exists = draft.cards.some((item) => item.card_id === card.card_id);
        if (exists) setCards(draft.cards.map((item) => (item.card_id === card.card_id ? card : item)));
        else {
          const target = draft.pages.length ? draft.pages.find((found) => found.page_id === card.page_id) ?? draft.pages[0] : null;
          setCards([...draft.cards, placeNew(card, cardsOn(draft, target))]);
        }
        setEditing(null);
      }} />}
    {settings && <SettingsDialog draft={draft ?? draftOf(saved)} folders={folders} dashboardId={isNew || draft ? null : dashboardId ?? null}
      onClose={() => setSettings(false)} onApply={(next) => void applySettings(next)}
      onRestored={(result) => { setSaved(result); setSettings(false); setNotice(t("Version restored.")); refresh(); }} />}
    {sharing && dashboardId && <ShareDialog dashboardId={dashboardId} name={saved.name} isAdmin={me?.is_admin} onClose={() => setSharing(false)} />}
  </div></CursorContext.Provider>;
}
