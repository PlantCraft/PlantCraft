/**
 * `/models`: every model, the examples first, in the suite's table (search, group filter, sort), with
 * the site's folders on the left (round 9 M5, as Link's).
 * Every model opens its page (one kind of model, owner 2026-10-24: one written as code is the
 * one block of its diagram). New model starts an empty diagram with the default settings.
 */
import { chosenFolder, DataTable, FolderColumn, folderName, inFolder, newInFolder, rememberFolder, useAssistantPage, useFolders, type DataColumn } from "@plantcraft/ui";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatAgo, t } from "./i18n";
import { Link, navigate } from "./nav";
import { modelPath } from "./paths";
import { SOLVER_NAMES } from "./SimulationSettings";
import type { Me, ModelItem } from "./types";
import { Dialog, ErrorBox, Heading, Loading, message, reading } from "./ui";

/** The group a model is listed under: its own, "Examples" for the examples, else "Other". */
export function groupOf(model: Pick<ModelItem, "group" | "example">): string {
  return model.group || (model.example ? t("Examples") : t("Other"));
}

export function NewModelDialog({ groups, onClose, like }: { groups: string[]; onClose: () => void; like?: { projectId: string; model: string; name: string; group: string } }) {
  const [name, setName] = useState(like ? t("{name} (copy)", { name: like.name }) : "");
  const [description, setDescription] = useState("");
  const [group, setGroup] = useState(like?.group ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const model = like ? await api.duplicateModel(like.projectId, like.model, name.trim(), group.trim())
        : await api.createModel(name.trim(), description.trim(), group.trim());
      navigate(modelPath(model.project_id, model.model));
    } catch (err) { setError(message(err)); setBusy(false); }
  };
  return <Dialog title={like ? t("Duplicate the model") : t("New model")} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !name.trim()} onClick={() => void create()}>{like ? t("Duplicate") : t("Create")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void create(); }}>
      <label>{t("Name")}<input value={name} maxLength={120} autoFocus onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Feed tank level")} /></label>
      <label>{t("Category")} <small>{t("optional")}</small><input list="mc-model-groups" value={group} maxLength={60} onChange={(event) => setGroup(event.target.value)} placeholder={t("e.g. Utilities")} />
        <datalist id="mc-model-groups">{groups.map((item) => <option key={item} value={item} />)}</datalist></label>
      {!like && <label className="pc-span-all">{t("Description")} <small>{t("optional")}</small><input value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>}
    </form>
  </Dialog>;
}

export function ModelsPage({ me }: { me: Me }) {
  const [models, setModels] = useState<ModelItem[] | null>(null);
  const [error, setError] = useState("");
  // Folders (round 9, M5), as Link's: the left column picks one, kept in ?folder=.
  const [folders, reloadFolders] = useFolders("model");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  useEffect(() => { api.models().then(setModels).catch((err) => setError(message(err))); }, []);
  // Models' work here (app.toml): which model fits a question.
  useAssistantPage({ place: t("Models › Models"), page: "modelcraft:models", platformUrl: me.processcraft_url, facts: { models: models?.length ?? 0 },
    view: { models: (models ?? []).slice(0, 40).map((model) => `${model.name.slice(0, 80)}${model.description ? `: ${model.description.slice(0, 100)}` : ""}`) } });
  if (error) return <ErrorBox text={error} />;
  if (!models) return <Loading />;
  const groups = [...new Set(models.map(groupOf))].sort();
  const columns: DataColumn<ModelItem>[] = [
    { key: "name", label: t("Model"), sort: (model) => model.name, render: (model) => <><strong>{model.name}</strong>{model.description && <small>{model.description}</small>}</> },
    { key: "group", label: t("Category"), sort: (model) => groupOf(model), render: (model) => groupOf(model), filter: { value: (model) => groupOf(model), options: groups.map((value) => ({ value, label: value })) } },
    { key: "blocks", label: t("Blocks"), numeric: true, sort: (model) => (model.diagram ? model.blocks : 1), render: (model) => (model.diagram ? model.blocks : <span title={t("Written in Modelica code: one block")}>{t("1 (code)")}</span>) },
    { key: "time", label: t("Simulated time"), numeric: true, sort: (model) => model.settings.stop - model.settings.start,
      render: (model) => <span className="nowrap">{reading(model.settings.stop - model.settings.start, "s")}<small>{SOLVER_NAMES[model.settings.solver] ?? model.settings.solver} · {t("step {step} s", { step: reading(model.settings.interval) })}</small></span> },
    { key: "updated", label: t("Changed"), sort: (model) => model.updated_at, render: (model) => <span className="nowrap">{formatAgo(model.updated_at)}<small>{model.updated_by}</small></span> },
  ];
  const newModel = newInFolder("/models/new", folder);
  const shown = models.filter((model) => inFolder(folders, `${model.project_id}/${model.model}`, folder));
  return <>
    <Heading title={t("Models")} actions={me.can_edit ? <Link to={newModel} className="button button-primary"><Plus />{t("New model")}</Link> : undefined} />
    {models.length === 0 ? <div className="panel empty"><h2>{t("No model yet")}</h2>{me.can_edit && <Link to={newModel} className="button button-primary">{t("New model")}</Link>}</div>
      : <div className="pc-folder-layout">
      <FolderColumn kind="model" list={folders} chosen={folder} onChoose={(value) => { setFolder(value); rememberFolder("/models", value); }} total={models.length} canEdit={me.can_edit} onChanged={reloadFolders} />
      <section>
      {folder && <div className="pc-folder-head"><h2>{folderName(folders, folder)}</h2></div>}
      <DataTable rows={shown} columns={columns} rowKey={(model) => `${model.project_id}/${model.model}`} label={t("Models")}
        searchText={(model) => [model.name, model.model, model.description, groupOf(model)].join(" ")} searchPlaceholder={t("Search models")}
        empty={folder ? t("No model in this folder.") : t("No model matches these filters.")}
        onRowClick={(model) => navigate(modelPath(model.project_id, model.model))} />
      </section></div>}
  </>;
}
