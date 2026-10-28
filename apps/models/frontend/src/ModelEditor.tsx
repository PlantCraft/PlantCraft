/**
 * `/editor/<project>/<class>`: a model's diagram editor in a window of its own, as Link's
 * algorithm editor (owner, 2026-10-24). The palette holds the blocks of the libraries; wires go
 * from an output to an input, feedback loops included; the simulation settings sit beside the
 * diagram. Save writes the diagram into the model's Modelica text and tells the model's page.
 * A model written as code shows its one block here; its code is changed in the code editor.
 */
import { AppMark } from "@plantcraft/ui";
import { BlockEditor, type BlockCatalog } from "@plantcraft/ui/blockEditor";
import "@xyflow/react/dist/style.css";
import "@plantcraft/ui/blockEditor.css";
import { Code2, LoaderCircle, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href } from "./nav";
import { announceSaved, modelView } from "./modelView";
import { blockPath, codePath, modelPath } from "./paths";
import { checkDiagram, settingsProblem, SimulationSettings } from "./SimulationSettings";
import type { BlockDiagram, Me, ModelDetail, SimSettings } from "./types";
import { ErrorBox, Loading, message } from "./ui";

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function ModelEditorWindow({ projectId, model, me }: { projectId: string; model: string; me: Me }) {
  const [found, setFound] = useState<ModelDetail | null>(null);
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null);
  const [diagram, setDiagram] = useState<BlockDiagram | null>(null);
  const [settings, setSettings] = useState<SimSettings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    Promise.all([api.model(projectId, model), api.catalog()]).then(([detail, blocks]) => {
      setFound(detail); setCatalog(blocks); setDiagram(detail.diagram); setSettings(detail.settings);
      document.title = t("{name} · Editor · Models", { name: detail.name });
    }).catch((err) => setError(message(err)));
  }, [projectId, model]);
  const view = useMemo(() => (found && catalog ? modelView(found, catalog) : null), [found, catalog]);
  const check = useMemo(() => (diagram && catalog && found && !view?.code ? checkDiagram(diagram, catalog, found.problems) : null), [diagram, catalog, found, view]);
  // Leaving with changes not saved asks first.
  const dirty = Boolean(found && diagram && settings && (!same(diagram, found.diagram) || !same(settings, found.settings)));
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  if (error && !found) return <div className="mc-window mc-window-state"><ErrorBox text={error} /></div>;
  if (!found || !view || !diagram || !settings) return <div className="mc-window mc-window-state"><Loading /></div>;
  const readOnly = view.code || found.example || !me.can_edit || !found.editable;
  const settingsError = settingsProblem(settings);
  const save = async () => {
    setSaving(true); setError(""); setNotice("");
    try {
      const saved = await api.saveModel(projectId, model, diagram, settings, found.updated_at);
      setFound(saved); setDiagram(saved.diagram); setSettings(saved.settings);
      announceSaved(projectId, model);
      setNotice(t("Saved."));
    } catch (err) { setError(message(err)); } finally { setSaving(false); }
  };
  const state = view.code ? t("Written in Modelica code") : found.example ? t("An example, read-only") : !found.editable ? t("Read-only: change it in the code") : dirty ? t("Changed, not saved") : t("Saved");
  return <div className="mc-window">
    <header className="mc-window-bar">
      <a href={href(modelPath(projectId, model))} className="mc-window-brand" title={t("The model's page")}><AppMark app="modelcraft" size={22} /><span>{t("Models")}</span></a>
      <span className="mc-window-title"><b>{found.name}</b><small>{state}</small></span>
      <span className="mc-window-actions">
        {(view.code || !found.editable) && <a href={href(codePath(projectId, model))} className="button button-secondary"><Code2 size={16} />{t("Edit the code")}</a>}
        {!readOnly && <button type="button" className="button button-primary" disabled={saving || !dirty || Boolean(settingsError)} title={settingsError || undefined} onClick={() => void save()}>
          {saving ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}{t("Save")}</button>}
      </span>
    </header>
    {(error || notice) && <div className={`mc-window-notice notice ${error ? "notice-error" : "notice-ok"}`} role={error ? "alert" : "status"}>{error || notice}</div>}
    {found.example && !view.code && <div className="mc-window-notice notice">{t("An example: it stays as Models ships it. Duplicate it on its page to change it.")}</div>}
    <BlockEditor key={`${projectId}/${model}`} catalog={view.catalog} diagram={view.code ? view.diagram : diagram} allowLoops check={check ?? undefined}
      onChange={readOnly ? undefined : setDiagram} readOnly={readOnly} blockHref={(blockId) => (blockId.startsWith("modelica:") ? href(codePath(projectId, model)) : href(blockPath(blockId)))}
      className="mc-window-editor" aside={<SimulationSettings settings={settings} readOnly={readOnly} onChange={setSettings} />} />
  </div>;
}
