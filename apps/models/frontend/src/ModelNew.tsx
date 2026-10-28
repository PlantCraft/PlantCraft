/**
 * `/models/new` (owner, 2026-10-25, round 9): a new model the way Link makes a new block or
 * algorithm. Import a Modelica file, or fill in the form (its name, group and what it is) and go
 * on in the diagram's editor; the assistant's button beside the title opens it on designing a
 * model of blocks.
 */
import { chosenFolder, FolderField, putInFolder, useAssistantPage } from "@plantcraft/ui";
import { ChevronRight, FileUp, FormInput } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { Link, navigate } from "./nav";
import { openEditor } from "./ModelPage";
import { modelPath } from "./paths";
import type { Me } from "./types";
import { ErrorBox, Heading, message } from "./ui";

type Way = "import" | "form";

/** The model a ``.mo`` file holds is its first ``model`` class: refuse a file without one here. */
export function modelFileProblem(name: string, text: string): string {
  if (!/\.mo$/i.test(name)) return t("Choose a Modelica file (.mo).");
  if (!/(^|\n)\s*(partial\s+)?model\s+[A-Za-z_]/.test(text)) return t("The file has no Modelica model in it.");
  return "";
}

function ImportStart({ group }: { group: string }) {
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const read = (name: string, text: string) => {
    const problem = modelFileProblem(name, text);
    setError(problem); setFile(problem ? null : { name, text });
  };
  async function create() {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const model = await api.importModel(file.name, file.text, group);
      await putInFolder("model", `${model.project_id}/${model.model}`, chosenFolder(window.location.search));
      navigate(modelPath(model.project_id, model.model));
    } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <section className="panel mc-new-step">
    <h2>{t("Import a Modelica file")}</h2>
    <p className="muted">{t("A .mo file with one model, as the Modelica code button gives it or another tool writes it. Models opens its first model: as a diagram when it can draw it, else as one block of code.")}</p>
    <label className="button button-secondary mc-new-upload"><FileUp size={16} />{t("Choose a file…")}<input type="file" accept=".mo" onChange={(event) => { const chosen = event.target.files?.[0]; if (chosen) chosen.text().then((text) => read(chosen.name, text)).catch((err: Error) => setError(err.message)); }} /></label>
    {file && <p className="mc-new-ok small">{t("{name} is ready. It is saved as the first version of a new model.", { name: file.name })}</p>}
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <div className="row-actions"><button type="button" className="button button-primary" disabled={!file || busy} onClick={() => void create()}>{busy ? t("Saving…") : t("Create the model")}</button></div>
  </section>;
}

function FormStart({ groups }: { groups: string[] }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [group, setGroup] = useState("");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create() {
    setBusy(true); setError("");
    try {
      const model = await api.createModel(name.trim(), description.trim(), group.trim());
      await putInFolder("model", `${model.project_id}/${model.model}`, folder);
      navigate(modelPath(model.project_id, model.model, "diagram"));
      openEditor(model.project_id, model.model);
    } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <section className="panel mc-new-step">
    <h2>{t("Fill in the form")}</h2>
    <p className="muted">{t("Name it and say what it is; the blocks are then placed and wired in the diagram's editor, and each save is a new version.")}</p>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void create(); }}>
      <label>{t("Name")}<input id="mcn-name" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Feed tank level")} /></label>
      <label>{t("Category")} <small>{t("optional")}</small><input id="mcn-group" list="mc-new-groups" value={group} maxLength={60} onChange={(event) => setGroup(event.target.value)} placeholder={t("e.g. Utilities")} />
        <datalist id="mc-new-groups">{groups.map((item) => <option key={item} value={item} />)}</datalist></label>
      <FolderField kind="model" value={folder} onChange={setFolder} />
      <label className="pc-span-all">{t("Description")} <small>{t("optional")}</small><textarea id="mcn-description" rows={2} value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>
      <div className="row-actions pc-span-all"><button className="button button-primary" disabled={busy || !name.trim()}>{busy ? t("Saving…") : t("Create and open the editor")}</button></div>
    </form>
  </section>;
}

export function NewModelPage({ me }: { me: Me }) {
  const [way, setWay] = useState<Way | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  useEffect(() => {
    api.models().then((items) => setGroups([...new Set(items.filter((item) => !item.example).map((item) => item.group).filter(Boolean))].sort())).catch(() => setGroups([]));
  }, []);
  // Models' work on this page (app.toml: design a new model).
  useAssistantPage({
    page: "modelcraft:model-new", title: t("A new model"), place: t("Models › New model"), platformUrl: me.processcraft_url,
    context: t("The person is creating a new process model in Models: a diagram of blocks (sources, process units, controllers, scopes) simulated with Modelica."),
  });
  if (!me.can_edit) return <ErrorBox text={t("Only editors make models.")} />;
  const ways: Array<{ id: Way; icon: React.ReactNode; title: string; text: string }> = [
    { id: "import", icon: <FileUp size={20} />, title: t("Import a file"), text: t("A Modelica file (.mo) with the model.") },
    { id: "form", icon: <FormInput size={20} />, title: t("Fill in the form"), text: t("Its name and what it is; then the diagram.") },
  ];
  return <>
    <nav className="breadcrumb"><Link to="/models">{t("Models")}</Link><ChevronRight size={12} /><span>{t("New model")}</span></nav>
    <Heading title={t("New model")} />
    <div className="pc-grid mc-new-ways">{ways.map((item) => <button key={item.id} type="button" className={`panel card mc-new-way${way === item.id ? " active" : ""}`} aria-pressed={way === item.id} onClick={() => setWay(item.id)}>
      <span className="mc-new-way-icon">{item.icon}</span><strong>{item.title}</strong><p>{item.text}</p>
    </button>)}</div>
    {way === "import" && <ImportStart group="" />}
    {way === "form" && <FormStart groups={groups} />}
  </>;
}
