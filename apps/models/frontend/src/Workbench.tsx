/**
 * `/code/<project>`: the Modelica code of a model or a block library (the workbench). The project's classes and the library on the left;
 * the selected class's text, diagram or documentation in the middle; the selected component's
 * parameters on the right; omc's messages below. Check, Simulate, New study and Export FMU in the
 * toolbar. `?model=` opens that class.
 */
import { AlertTriangle, CheckCircle2, ChevronRight, Copy, Download, FilePlus2, FlaskConical, Library, Package, Play, RotateCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, CopyPrompt, confirmAction } from "@plantcraft/ui";
import { api } from "./api";
import { DiagramView, rotated, type DiagramChange, type Selection } from "./Diagram";
import { Editor } from "./Editor";
import { IconPreview } from "./Graphics";
import { BlocksBrowser, CLASS_DRAG, LibraryBrowser } from "./Library";
import { classPath, classText, placeable, RESTRICTIONS, templateLabel, templatesFor, withOrder } from "./templates";
import { FmuDialog, SimulateDialog } from "./RunDialogs";
import { t } from "./i18n";
import { navigate } from "./nav";
import { codePath, modelPath, newStudyPath, runPath } from "./paths";
import type { ClassInfo, ComponentInfo, Diagram, LibraryClass, Me, Message, Project, ProjectFile, RunnerState } from "./types";
import { ClassBadge, Dialog, ErrorBox, LevelPill, Link, Loading, message } from "./ui";

type View = "text" | "diagram" | "documentation";
type Opened = { path: string; content: string; draft: string; updatedAt: string | null };

/** Documentation HTML from a class, shown in a sandbox: no script, no form, no link out. */
export function DocumentationFrame({ html, title }: { html: string; title: string }) {
  const page = `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:"><style>body{font:14px/1.55 system-ui,sans-serif;margin:16px;color:#1d1d1f}pre,code{font-size:12px}table{border-collapse:collapse}td,th{border:1px solid #d2d2d7;padding:3px 6px}</style>${html}`;
  return <iframe className="mc-doc" title={title} sandbox="" srcDoc={page} />;
}

function LibraryClassDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const [found, setFound] = useState<LibraryClass | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"about" | "documentation" | "text">("about");
  useEffect(() => { api.libraryClass(name).then(setFound).catch((err) => setError(message(err))); }, [name]);
  return <Dialog title={name} onClose={onClose} wide footer={<button type="button" className="button button-secondary" onClick={onClose}>{t("Close")}</button>}>
    {error ? <ErrorBox text={error} /> : !found ? <Loading /> : <>
      <div className="mc-class-head">
        <IconPreview layer={found.icon} name={found.short} type={found.name} size={96} />
        <div>
          <p className="eyebrow"><ClassBadge restriction={found.restriction} partial={found.partial} /> {found.restriction}</p>
          <p>{found.comment || t("No description.")}</p>
          <p className="muted small">{t("Drag it from the library onto a diagram to use it.")}</p>
        </div>
      </div>
      <div className="segmented" role="tablist">
        {(["about", "documentation", "text"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? "on" : ""} onClick={() => setTab(item)}>
          {item === "about" ? t("Parameters and connectors") : item === "documentation" ? t("Documentation") : t("Modelica text")}
        </button>)}
      </div>
      {tab === "about" && <div className="mc-class-body">
        {found.parameters.length ? <table className="table">
          <thead><tr><th>{t("Parameter")}</th><th>{t("Default")}</th><th>{t("Description")}</th></tr></thead>
          <tbody>{found.parameters.map((item) => <tr key={item.name}><td className="pc-mono">{item.name}</td><td className="pc-mono">{item.default ?? "–"}{item.unit ? ` ${item.unit}` : ""}</td><td>{item.comment}</td></tr>)}</tbody>
        </table> : <p className="muted">{t("No parameters.")}</p>}
        {(found.inputs.length > 0 || found.outputs.length > 0) && <p className="small"><strong>{t("Inputs")}:</strong> {found.inputs.join(", ") || "–"} · <strong>{t("Outputs")}:</strong> {found.outputs.join(", ") || "–"}</p>}
      </div>}
      {tab === "documentation" && (found.documentation.info ? <DocumentationFrame title={name} html={found.documentation.info} /> : <p className="muted">{t("No documentation.")}</p>)}
      {tab === "text" && <pre className="mc-source">{found.source ?? t("The text is not available.")}</pre>}
    </>}
  </Dialog>;
}

/** A new class, as OpenModelica's "New Modelica Class" dialog asks for it: name, specialization,
 * description, base class, the package it goes in, partial; models and blocks may start from a template. */
function NewClassDialog({ classes, onClose, onCreate }: { classes: ClassInfo[]; onClose: () => void; onCreate: (path: string, content: string, packageFile?: string) => Promise<void> }) {
  const [name, setName] = useState("NewModel");
  const [restriction, setRestriction] = useState("model");
  const [template, setTemplate] = useState("empty");
  const [comment, setComment] = useState("");
  const [base, setBase] = useState("");
  const [within, setWithin] = useState("");
  const [partial, setPartial] = useState(false);
  const [libraryNames, setLibraryNames] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Only a package with its own folder (Package/package.mo) takes a new file.
  const packages = classes.filter((item) => item.restriction === "package" && item.file.endsWith("/package.mo"));
  const templates = templatesFor(restriction);
  const chosen = templates.find((item) => item.id === template) ?? templates[0];
  useEffect(() => {
    const prefix = base.trim();
    if (!prefix.startsWith("Modelica.")) return;
    const timer = window.setTimeout(() => api.libraryNames(prefix).then((names) => setLibraryNames(names.slice(0, 200))).catch(() => undefined), 200);
    return () => window.clearTimeout(timer);
  }, [base]);
  const ident = name.trim();
  const packageFile = packages.find((item) => item.name === within)?.file;
  const submit = async () => {
    const text = classText({ name: ident, restriction, comment, extends: base, partial, within, template: chosen.id });
    if (text === null) { setError(t("A name starts with a letter and has only letters, digits and _; a base class is a name like Modelica.Blocks.Interfaces.SISO.")); return; }
    setBusy(true);
    try { await onCreate(classPath(ident, packageFile), text, packageFile); } catch (err) { setError(message(err)); setBusy(false); }
  };
  return <Dialog title={t("New Modelica class")} onClose={onClose} wide footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !ident} onClick={() => void submit()}>{t("Create")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <div className="form-grid">
      <label>{t("Name")}<input value={name} onChange={(event) => setName(event.target.value)} autoFocus /></label>
      <label>{t("Specialization")}<select value={restriction} onChange={(event) => { setRestriction(event.target.value); setTemplate("empty"); }}>
        {RESTRICTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
      </select></label>
      <label className="field-span">{t("Description")} <small>{t("optional")}</small><input value={comment} maxLength={200} placeholder={chosen.comment || t("What it is, in a line: shown in the library and on hover")} onChange={(event) => setComment(event.target.value)} /></label>
      <label>{restriction === "type" ? t("Based on") : t("Extends")} <small>{t("optional")}</small>
        <input list="mc-base-classes" value={base} placeholder={restriction === "type" ? "Real" : "Modelica.Blocks.Interfaces.SISO"} onChange={(event) => setBase(event.target.value)} />
        <datalist id="mc-base-classes">{[...classes.filter((item) => item.restriction !== "package").map((item) => item.name), ...libraryNames].map((item) => <option key={item} value={item} />)}</datalist>
      </label>
      <label>{t("Insert in package")}<select value={within} onChange={(event) => setWithin(event.target.value)} disabled={!packages.length}>
        <option value="">{t("Top of the project")}</option>
        {packages.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
      </select></label>
      {templates.length > 1 && <label className="field-span">{t("Start from")}<select value={chosen.id} onChange={(event) => setTemplate(event.target.value)}>
        {templates.map((item) => <option key={item.id} value={item.id}>{templateLabel(item)}</option>)}
      </select></label>}
      {templates.length > 1 && <p className="form-note field-span">{t(chosen.detail)}</p>}
      <label className="check field-span"><input type="checkbox" checked={partial} onChange={(event) => setPartial(event.target.checked)} /> {t("Partial: a base for other classes, not used or simulated on its own")}</label>
      <p className="form-note field-span">{t("The class gets its own file, {file}. A model or block of the project is dragged into a system's diagram like a class of the library.", { file: classPath(ident || "Name", packageFile) })}</p>
    </div>
  </Dialog>;
}

/** The selected component's parameters, written as modifiers in the class's text. */
function Inspector({ component, editable, onApply }: { component: ComponentInfo; editable: boolean; onApply: (values: Record<string, string | null>) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => setValues({}), [component.name]);
  const changed = Object.keys(values).length > 0;
  return <div className="mc-inspector">
    <div className="mc-class-head">
      <IconPreview layer={component.icon} name={component.name} type={component.type} size={56} values={component.values} />
      <div>
        <strong>{component.name}</strong>
        <p className="muted small pc-mono">{component.type}</p>
        {component.comment && <p className="small">{component.comment}</p>}
        {component.inherited && <p className="small muted">{t("Inherited: change it in the base class.")}</p>}
      </div>
    </div>
    {component.parameters.length === 0 ? <p className="muted small">{t("No parameters.")}</p> : <form className="mc-param-form" onSubmit={(event) => { event.preventDefault(); onApply(Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim() === "" ? null : value.trim()]))); setValues({}); }}>
      {component.parameters.map((item) => <label key={item.name} title={item.comment}>
        <span>{item.name}{item.unit && <small> [{item.unit}]</small>}</span>
        <input value={values[item.name] ?? item.set ?? ""} placeholder={item.default ?? ""} disabled={!editable || component.inherited}
          onChange={(event) => setValues({ ...values, [item.name]: event.target.value })} />
        {item.comment && <small className="muted">{item.comment}</small>}
      </label>)}
      {editable && !component.inherited && <button type="submit" className="button button-primary button-small" disabled={!changed}>{t("Apply")}</button>}
    </form>}
  </div>;
}

function MessagesPanel({ messages, summary, ok, onOpen }: { messages: Message[]; summary: string; ok: boolean | null; onOpen: (message: Message) => void }) {
  const errors = messages.filter((item) => item.level === "error").length;
  const warnings = messages.filter((item) => item.level === "warning").length;
  return <section className="mc-messages" aria-label={t("Messages")}>
    <header>
      {ok === true ? <CheckCircle2 className="mc-ok" aria-hidden="true" /> : ok === false ? <AlertTriangle className="mc-bad" aria-hidden="true" /> : null}
      <strong>{t("Messages")}</strong>
      <span className="muted small">{summary || t("Check a model to see omc's messages here.")}</span>
      <span className="mc-counts small">{t("{errors} errors · {warnings} warnings", { errors, warnings })}</span>
    </header>
    {messages.length > 0 && <ul>
      {messages.map((item, index) => <li key={index}>
        <LevelPill level={item.level} />
        {item.file && item.line ? <button type="button" className="link-button pc-mono" onClick={() => onOpen(item)}>{item.file}:{item.line}</button> : null}
        <span className="mc-message-text">{item.text}</span>
      </li>)}
    </ul>}
  </section>;
}

export function Workbench({ projectId, me }: { projectId: string; me: Me }) {
  const [project, setProject] = useState<(Project & { files: ProjectFile[]; classes: ClassInfo[] }) | null>(null);
  const [runner, setRunner] = useState<RunnerState | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ kind: "ok" | "error" | "info"; text: string; link?: { to: string; label: string } } | null>(null);
  const [side, setSide] = useState<"project" | "library">("project");
  const [model, setModel] = useState("");
  const [opened, setOpened] = useState<Opened | null>(null);
  const [reveal, setReveal] = useState<{ line: number } | null>(null);
  const [view, setView] = useState<View>("text");
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [diagramError, setDiagramError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [summary, setSummary] = useState("");
  const [ok, setOk] = useState<boolean | null>(null);
  const [busy, setBusy] = useState("");
  const [dialog, setDialog] = useState<"" | "simulate" | "fmu" | "new">("");
  const [libraryClass, setLibraryClass] = useState("");
  const editable = me.can_edit && !project?.example;
  const openedRef = useRef(opened);
  openedRef.current = opened;

  const loadProject = useCallback(async () => {
    const found = await api.project(projectId);
    setProject(found);
    return found;
  }, [projectId]);

  useEffect(() => {
    loadProject().then((found) => {
      // The first class ready to run (an experiment annotation says so), as a person would pick it.
      const wanted = new URLSearchParams(window.location.search).get("model");
      const first = found.classes.find((item) => item.name === wanted)
        ?? found.classes.find((item) => item.simulable && item.experiment.StopTime !== undefined)
        ?? found.classes.find((item) => item.simulable) ?? found.classes[0];
      if (first) void openClass(first);
    }).catch((err) => setError(message(err)));
    const poll = () => api.runner().then(setRunner).catch(() => undefined);
    void poll();
    const timer = window.setInterval(poll, 15_000);
    return () => window.clearInterval(timer);
    // Opening the first class is part of loading the page, once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadProject]);

  const dirty = Boolean(opened && opened.draft !== opened.content);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useCallback(async (): Promise<boolean> => {
    const current = openedRef.current;
    if (!current || current.draft === current.content || !editable) return true;
    try {
      const saved = await api.saveFile(projectId, current.path, current.draft, current.updatedAt);
      setOpened((now) => (now && now.path === saved.path ? { ...now, content: saved.content, updatedAt: saved.updated_at } : now));
      void loadProject();
      return true;
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof ApiError && err.status === 409 ? t("Someone else saved this file meanwhile. Copy your change, reload the page and apply it again.") : message(err) });
      return false;
    }
  }, [editable, loadProject, projectId]);

  const openFile = async (path: string, line?: number) => {
    if (openedRef.current?.path !== path) {
      if (!(await save())) return;
      const file = await api.file(projectId, path);
      setOpened({ path, content: file.content, draft: file.content, updatedAt: file.updated_at });
    }
    if (line) setReveal({ line });
  };

  async function openClass(item: ClassInfo) {
    setModel(item.name);
    setSelection(null);
    try { await openFile(item.file, item.line); } catch (err) { setNotice({ kind: "error", text: message(err) }); }
  }

  const classes = useMemo(() => project?.classes ?? [], [project]);
  const info = classes.find((item) => item.name === model);

  const drawDiagram = useCallback(async () => {
    if (!model || !editable) return;
    setDrawing(true);
    setDiagramError("");
    try {
      if (!(await save())) return;
      const found = await api.diagram(projectId, model);
      setDiagram(found);
      if (found.messages?.length) setMessages(found.messages);
    } catch (err) {
      setDiagramError(message(err));
      const payload = (err as ApiError).payload as { detail?: { messages?: Message[] } } | undefined;
      if (payload?.detail?.messages) setMessages(payload.detail.messages);
    } finally {
      setDrawing(false);
    }
  }, [editable, model, projectId, save]);

  useEffect(() => {
    if ((view === "diagram" || view === "documentation") && model && diagram?.name !== model) void drawDiagram();
  }, [view, model, diagram?.name, drawDiagram]);

  const change = useCallback(async (edit: DiagramChange | { op: "modifiers"; name: string; values: Record<string, string | null> }) => {
    if (!info) return;
    if (!(await save())) return;
    setBusy("edit");
    try {
      const base = openedRef.current?.path === info.file ? openedRef.current.updatedAt : null;
      const saved = await api.edit(projectId, { model, file: info.file, base_updated_at: base, ...edit });
      if (openedRef.current?.path === saved.path) setOpened({ path: saved.path, content: saved.content, draft: saved.content, updatedAt: saved.updated_at });
      if (edit.op === "delete" || edit.op === "disconnect") setSelection(null);
      await loadProject();
      const found = await api.diagram(projectId, model);
      setDiagram(found);
      setDiagramError("");
    } catch (err) {
      setNotice({ kind: "error", text: message(err) });
    } finally {
      setBusy("");
    }
  }, [info, loadProject, model, projectId, save]);

  const check = async () => {
    if (!model) return;
    setBusy("check");
    try {
      if (!(await save())) return;
      const result = await api.check(projectId, model);
      setMessages(result.messages);
      setSummary(result.summary);
      setOk(result.ok);
    } catch (err) {
      setOk(false);
      setSummary(message(err));
      const payload = (err as ApiError).payload as { detail?: { messages?: Message[] } } | undefined;
      setMessages(payload?.detail?.messages ?? []);
    } finally {
      setBusy("");
    }
  };

  const createFile = async (path: string, content: string, packageFile?: string) => {
    await api.createFile(projectId, path, content);
    // A package with a package.order lists its classes there: the new one goes at its end.
    const order = packageFile ? packageFile.replace(/package\.mo$/, "package.order") : "";
    if (order && project?.files.some((file) => file.path === order)) {
      const current = await api.file(projectId, order);
      const name = path.split("/").pop()!.replace(/\.mo$/, "");
      if (withOrder(current.content, name) !== current.content) await api.saveFile(projectId, order, withOrder(current.content, name), current.updated_at);
    }
    setDialog("");
    const found = await loadProject();
    const created = found.classes.find((item) => item.file === path);
    if (created) await openClass(created);
  };

  const deleteFile = async (path: string) => {
    if (!(await confirmAction(t("Delete {path}? Its earlier versions go with it.", { path }), { confirm: t("Delete"), danger: true }))) return;
    try {
      await api.deleteFile(projectId, path);
      if (openedRef.current?.path === path) setOpened(null);
      await loadProject();
    } catch (err) {
      setNotice({ kind: "error", text: message(err) });
    }
  };

  const duplicate = async () => {
    if (!project) return;
    const name = window.prompt(t("Name of the copy"), t("{name} (copy)", { name: project.name }));
    if (!name) return;
    try { const copy = await api.duplicateProject(project.id, name); navigate(codePath(copy.id)); } catch (err) { setNotice({ kind: "error", text: message(err) }); }
  };

  const simulateClass = async (item: ClassInfo) => {
    await openClass(item);
    if (await save()) setDialog("simulate");
  };

  if (error) return <ErrorBox text={error} />;
  if (!project) return <Loading />;
  const selected = selection?.kind === "component" ? diagram?.components.find((item) => item.name === selection.name) : undefined;
  const byFile = new Map<string, ClassInfo[]>();
  for (const item of classes) byFile.set(item.file, [...(byFile.get(item.file) ?? []), item]);
  const runnerDown = runner !== null && !runner.available;
  // A block library is edited here too; it has no studies or exports of its own.
  const library = project.kind === "library";
  const fileMessages = messages.filter((item) => item.file === opened?.path);

  return <div className="mc-workbench">
    <div className="mc-topbar">
      <nav className="breadcrumb" aria-label={t("Breadcrumb")}>{library ? <><Link to="/blocks">{t("Blocks")}</Link><ChevronRight aria-hidden="true" /><span>{project.name}</span></>
        : <><Link to="/models">{t("Models")}</Link><ChevronRight aria-hidden="true" /><span>{project.name}</span></>}
        {info && <><ChevronRight aria-hidden="true" /><span className="pc-mono" title={info.name}>{info.short}</span></>}</nav>
      <div className="mc-actions">
        {editable && <button type="button" className="button button-secondary button-small" disabled={!dirty} onClick={() => void save()} title="Ctrl+S"><Save />{t("Save")}</button>}
        {me.can_edit && <button type="button" className="button button-secondary button-small" disabled={!model || runnerDown || busy === "check"} onClick={() => void check()} title={t("Checks the class: counts its equations and variables, without simulating")}><ShieldCheck />{busy === "check" ? t("Checking…") : t("Check")}</button>}
        {editable && <button type="button" className="button button-primary button-small" disabled={!info?.simulable || runnerDown} onClick={() => void save().then((saved) => saved && setDialog("simulate"))} title={info?.simulable ? t("Simulate {model}", { model: info.short }) : t("Open a model or block to simulate it")}><Play />{t("Simulate")}</button>}
        {editable && !library && <button type="button" className="button button-secondary button-small" disabled={!info?.simulable || runnerDown} onClick={() => void save().then((saved) => { if (saved && model) navigate(newStudyPath(projectId, model)); })} title={t("Simulates the model once or over a sweep of parameter values, in the background")}><FlaskConical />{t("New study")}</button>}
        {editable && !library && <button type="button" className="button button-secondary button-small" disabled={!info?.simulable || runnerDown} onClick={() => void save().then((saved) => saved && setDialog("fmu"))} title={t("Builds an FMU of the class, for Analytics or any FMI tool")}><Package />{t("Export FMU")}</button>}
        {project.example && editable && <button type="button" className="button button-secondary button-small" onClick={() => void duplicate()}><Copy />{t("Duplicate")}</button>}
        {model && <CopyPrompt build={(question) => api.classPrompt(projectId, model, question)} questions={[{ id: "explain", label: t("Explain this model") }, { id: "extend", label: t("Extend it with…") }, { id: "review", label: t("Review the model") }]} />}
        <a className="button button-secondary button-small" href={api.exportUrl(projectId)} download title={t("Every .mo file of the project in a .zip, to open in OpenModelica or keep a copy")}><Download />{t("Project .zip")}</a>
      </div>
    </div>
    {runnerDown && <div className="notice">{t("The Modelica runner is not available: {reason} Editing still works; checking and simulating wait for it.", { reason: runner.reason })}</div>}
    {!editable && <div className="notice">{t("Your access to Models is read-only: you can read the models and their simulations.")}</div>}
    {project.example && editable && <div className="notice mc-notice-info">{t("This is an example project, shared by everyone. Duplicate it to keep your own copy.")}</div>}
    {notice && <div className={`notice ${notice.kind === "error" ? "notice-error" : notice.kind === "ok" ? "notice-ok" : ""}`} role="status">
      {notice.text} {notice.link && <Link to={notice.link.to} className="text-link">{notice.link.label}</Link>}
      <button type="button" className="link-button mc-dismiss" onClick={() => setNotice(null)}>{t("Dismiss")}</button>
    </div>}
    <div className="mc-panes">
      <aside className="mc-side panel">
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={side === "project"} className={side === "project" ? "on" : ""} onClick={() => setSide("project")}>{t("Files")}</button>
          <button type="button" role="tab" aria-selected={side === "library"} className={side === "library" ? "on" : ""} onClick={() => { setSide("library"); void api.runner().then(setRunner).catch(() => undefined); }}>{t("Library")}</button>
        </div>
        {side === "project" ? <div className="mc-project-tree">
          {editable && <button type="button" className="link-button" onClick={() => setDialog("new")}><FilePlus2 />{t("New class")}</button>}
          {project.files.length === 0 && <p className="muted small">{t("No file yet: add a class.")}</p>}
          <ul className="mc-tree">
            {project.files.map((file) => <li key={file.path}>
              <div className={`mc-tree-row mc-file${opened?.path === file.path ? " on" : ""}`}>
                <button type="button" className="mc-tree-label pc-mono" onClick={() => void openFile(file.path)}>{file.path}</button>
                {editable && <button type="button" className="icon-button mc-row-action" aria-label={t("Delete {path}", { path: file.path })} onClick={() => void deleteFile(file.path)}><Trash2 /></button>}
              </div>
              <ul>{(byFile.get(file.path) ?? []).map((item) => <li key={item.name}>
                <div className={`mc-tree-row${item.name === model ? " on" : ""}${editable && placeable(item, model) ? " mc-draggable" : ""}`} style={{ paddingLeft: 10 + (item.name.split(".").length - 1) * 10 }}
                  draggable={editable && placeable(item, model)} title={editable && placeable(item, model) ? t("Drag it into the diagram of {model}", { model }) : undefined}
                  onDragStart={(event) => { event.dataTransfer.setData(CLASS_DRAG, item.name); event.dataTransfer.setData("text/plain", item.name); event.dataTransfer.effectAllowed = "copy"; }}>
                  <button type="button" className="mc-tree-label" onClick={() => void openClass(item)} title={item.comment || item.name}>
                    <ClassBadge restriction={item.restriction} partial={item.partial} /><span>{item.short}</span>
                  </button>
                  {item.simulable && editable && <button type="button" className="icon-button mc-row-action mc-simulable" disabled={runnerDown} title={t("Simulate {model}", { model: item.short })} aria-label={t("Simulate {model}", { model: item.short })} onClick={() => void simulateClass(item)}><Play /></button>}
                </div>
              </li>)}</ul>
            </li>)}
          </ul>
        </div> : <>
          {!library && <BlocksBrowser />}
          <LibraryBrowser ready={Boolean(runner?.library.ready)} onOpen={setLibraryClass} />
        </>}
      </aside>
      <main className="mc-center panel">
        <div className="mc-tabs">
          <div className="segmented" role="tablist">
            {(["text", "diagram", "documentation"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={view === item} className={view === item ? "on" : ""} onClick={() => { if (item !== "text") void save(); setView(item); }}>
              {item === "text" ? t("Text") : item === "diagram" ? t("Diagram") : t("Documentation")}
            </button>)}
          </div>
          {view === "text" && opened && <span className="muted small pc-mono">{opened.path}{dirty ? " •" : ""}</span>}
          {view === "diagram" && diagram && editable && <span className="muted small">{t("Drag classes from the project or the library; drag between connectors to connect; R rotates, Delete removes.")}</span>}
          {view === "diagram" && selected && editable && !selected.inherited && <span className="mc-tab-actions">
            <button type="button" className="icon-button" title={t("Rotate")} aria-label={t("Rotate")} onClick={() => void change({ op: "move", name: selected.name, ...rotated(selected.placement) })}><RotateCw /></button>
            <button type="button" className="icon-button" title={t("Delete")} aria-label={t("Delete")} onClick={() => void change({ op: "delete", name: selected.name })}><Trash2 /></button>
          </span>}
        </div>
        <div className="mc-view">
          {view === "text" && (opened ? <Editor file={opened.path} value={opened.draft} readOnly={!editable} messages={fileMessages} reveal={reveal}
            names={async () => [...classes.map((item) => item.name), ...(await api.libraryNames("Modelica.").catch(() => []))]}
            onChange={(text) => setOpened((now) => (now ? { ...now, draft: text } : now))} onSave={() => void save()} />
            : <p className="muted mc-center-note">{t("Open a class from the project.")}</p>)}
          {view === "diagram" && (!editable ? <p className="muted mc-center-note">{t("Drawing a diagram runs omc: it is open to editors.")}</p>
            : drawing && !diagram ? <Loading text={t("omc is reading the class…")} />
            : diagramError ? <div className="mc-center-note"><ErrorBox text={diagramError} /><button type="button" className="button button-secondary" onClick={() => void drawDiagram()}>{t("Try again")}</button></div>
            : diagram ? <div className={`mc-diagram-wrap${busy === "edit" || drawing ? " mc-busy" : ""}`}>
              <DiagramView diagram={diagram} editable={editable} selection={selection} onSelect={setSelection} onChange={(edit) => void change(edit)} />
              {diagram.components.length === 0 && <div className="mc-diagram-empty">
                <strong>{t("This diagram is empty")}</strong>
                <p>{t("Drag components onto it from the library (the Modelica Standard Library) or from your project, then drag between their connectors to connect them. Or write equations in Text.")}</p>
                {side !== "library" && <button type="button" className="button button-secondary button-small" onClick={() => { setSide("library"); void api.runner().then(setRunner).catch(() => undefined); }}><Library />{t("Open the library")}</button>}
              </div>}
            </div> : <p className="muted mc-center-note">{t("Choose a model.")}</p>)}
          {view === "documentation" && (diagram?.documentation.info ? <DocumentationFrame title={model} html={diagram.documentation.info} />
            : drawing ? <Loading /> : <p className="muted mc-center-note">{t("This class has no documentation. Write it in annotation(Documentation(info = \"<html>…</html>\")).")}</p>)}
        </div>
      </main>
      <aside className="mc-right panel">
        {view === "diagram" && selected ? <Inspector component={selected} editable={editable} onApply={(values) => void change({ op: "modifiers", name: selected.name, values })} />
          : info ? <div className="mc-inspector">
            <p className="eyebrow"><ClassBadge restriction={info.restriction} partial={info.partial} /> {info.restriction}</p>
            <strong className="mc-break">{info.name}</strong>
            <p className="small">{info.comment || t("No description.")}</p>
            {info.simulable ? <dl className="mc-facts">
              <dt>{t("Start")}</dt><dd>{info.experiment.StartTime ?? 0} s</dd>
              <dt>{t("Stop")}</dt><dd>{info.experiment.StopTime ?? 1} s</dd>
              {info.experiment.Interval !== undefined && <><dt>{t("Interval")}</dt><dd>{info.experiment.Interval} s</dd></>}
            </dl> : <p className="muted small">{info.partial ? t("A partial class is completed by others: it is not simulated.") : t("Only models and blocks are simulated.")}</p>}
            {!library && info.restriction === "model" && <Link to={modelPath(projectId, info.name)} className="text-link">{t("Open the model's page")}</Link>}
            {view === "diagram" && diagram && <p className="muted small">{t("Select a component to see and change its parameters.")}</p>}
          </div> : <p className="muted small">{t("Nothing selected.")}</p>}
      </aside>
    </div>
    <MessagesPanel messages={messages} summary={summary} ok={ok} onOpen={(item) => { setView("text"); if (item.file) void openFile(item.file, item.line ?? undefined); }} />
    {dialog === "simulate" && model && <SimulateDialog projectId={projectId} model={model} info={info} diagram={diagram?.name === model ? diagram : null}
      onClose={() => setDialog("")} onStarted={(run) => { setDialog(""); navigate(runPath(run)); }} />}
    {dialog === "fmu" && model && <FmuDialog projectId={projectId} model={model} onClose={() => setDialog("")}
      onStarted={(run) => { setDialog(""); setNotice({ kind: "info", text: t("The FMU is being built."), link: { to: runPath(run), label: t("Follow it") } }); }} />}
    {dialog === "new" && <NewClassDialog classes={classes} onClose={() => setDialog("")} onCreate={createFile} />}
    {libraryClass && <LibraryClassDialog name={libraryClass} onClose={() => setLibraryClass("")} />}
  </div>;
}
