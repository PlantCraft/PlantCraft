import { confirmAction } from "@plantcraft/ui";
import { BookOpen, ChevronRight, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { methodLabel } from "./labels";
import type { DefaultsVersion, Me, MethodSpec } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

function referenceText(reference: Record<string, unknown>) {
  const parts = [reference.authors, reference.year ? `(${reference.year})` : "", reference.title, reference.venue ?? reference.source ?? reference.journal].filter(Boolean);
  return parts.length ? parts.join(" ") : JSON.stringify(reference);
}

export function MethodPage({ methodId, me }: { methodId: string; me: Me }) {
  const [method, setMethod] = useState<MethodSpec | null>(null);
  const [source, setSource] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [description, setDescription] = useState("");
  const [versions, setVersions] = useState<DefaultsVersion[] | null>(null);
  const loadVersions = () => api.methodDefaultsVersions(methodId).then(setVersions).catch(() => setVersions([]));
  useEffect(() => { void loadVersions(); }, [methodId]);
  useEffect(() => {
    api.methods().then((items) => {
      const found = items.find((item) => item.method_id === methodId);
      if (!found) { setError(t("Method not found.")); return; }
      setMethod(found);
      setValues(Object.fromEntries(Object.entries(found.parameters.properties ?? {}).map(([key, schema]) => [key, String(found.configured_defaults?.[key] ?? schema.default ?? "")])));
    }).catch((err: Error) => setError(err.message));
  }, [methodId]);
  if (error) return <ErrorBox text={error} />;
  if (!method) return <Loading />;
  const properties = Object.entries(method.parameters.properties ?? {});
  const signal = method.application === "signal_quality";
  const label = method.label ?? methodLabel(method.method_id);
  // Saving is always a new version with what changed (owner, 2026-10-27); the history stays below.
  async function store(parameters: Record<string, unknown>, note: string) {
    setMessage(""); setError("");
    try {
      await api.saveMethodDefaults(methodId, parameters, note);
      setMessage(t("Saved as a new version: every algorithm that does not set these uses them."));
      setDescription("");
      setValues(Object.fromEntries(Object.entries(parameters).map(([key, value]) => [key, String(value ?? "")])));
      void loadVersions();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function save() {
    const parameters = Object.fromEntries(properties.map(([key, schema]) => [key, schema.type === "number" || schema.type === "integer" ? Number(values[key]) : schema.type === "boolean" ? values[key] === "true" : values[key]]));
    await store(parameters, description.trim());
  }
  async function remove(number: number) {
    if (!(await confirmAction(t("Delete version {number} of these defaults? This cannot be undone.", { number }), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteMethodDefaultsVersion(methodId, number); void loadVersions(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  const shipped = Object.fromEntries(properties.map(([key, schema]) => [key, schema.default ?? null]));
  const changed = (parameters: Record<string, unknown>) => properties.filter(([key]) => JSON.stringify(parameters[key] ?? null) !== JSON.stringify(shipped[key])).map(([key, schema]) => `${String(schema.title ?? key)} = ${JSON.stringify(parameters[key])}`).join(" · ") || t("as PlantCraft ships them");
  return <>
    <nav className="breadcrumb"><Link to="/blocks">{t("Blocks")}</Link><ChevronRight size={12} />{method.block_id && <><Link to={`/blocks/${encodeURIComponent(method.block_id)}`}>{label}</Link><ChevronRight size={12} /></>}<span>{t("Defaults and source code")}</span></nav>
    <Heading eyebrow={`${signal ? t("Data quality method") : method.gate ? t("Loop data gate") : t("Control loop performance")} · ${method.method_id} · v${method.version}`} title={label} detail={method.description}
      actions={<><Link to={`/help/methods/${method.method_id}`} className="button button-secondary"><BookOpen size={16} />{t("Help page")}</Link></>} />
    {message && <div className="notice notice-ok">{message}</div>}
    <div className="pc-grid pc-grid-2">
      <section className="panel"><div className="panel-header"><div><h2>{t("How it works")}</h2></div></div>
        {method.formula && <p className="pc-mono formula">{method.formula}</p>}
        <h3>{t("Signals")}</h3><p className="pc-mono">{signal ? t("Every signal, in the Signal quality algorithm") : method.required_signals.map((item) => item.toUpperCase()).join(", ") || "—"}</p>
        {!!method.assumptions?.length && <><h3>{t("Assumptions")}</h3><ul>{method.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></>}
        {!!method.limitations?.length && <><h3>{t("Limitations")}</h3><ul>{method.limitations.map((item) => <li key={item}>{item}</li>)}</ul></>}
        {!!method.references.length && <><h3>{t("References")}</h3><ul>{method.references.map((item, index) => <li key={index}>{referenceText(item)}</li>)}</ul></>}
      </section>
      <section className="panel"><div className="panel-header"><div><h2>{t("Parameters")}</h2><p>{me.is_admin ? (signal ? t("Defaults for every signal; a signal can override them.") : t("Defaults for every loop; an algorithm or a loop can override them.")) : t("Only admins change the defaults.")}</p></div></div>
        {properties.length ? <div className="form-grid">{properties.map(([key, schema]) => <label key={key}>{String(schema.title ?? key)}<input value={values[key] ?? ""} disabled={!me.is_admin} onChange={(event) => setValues({ ...values, [key]: event.target.value })} /><small>{String(schema.description ?? "")}</small></label>)}</div> : <p className="muted">{t("No parameters.")}</p>}
        {me.is_admin && properties.length > 0 && <div className="form-grid">
          <label>{t("What changed (required)")}<input id="defaults-description" value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} placeholder={t("Looser limit: fewer false alarms on slow loops")} /></label>
          <div className="row-actions"><button className="button button-primary" disabled={!description.trim()} onClick={() => void save()}>{t("Save as a new version")}</button></div>
        </div>}
        <details className="source" onToggle={(event) => { if ((event.target as HTMLDetailsElement).open && !source) api.methodSource(methodId).then((item) => setSource(item.source)).catch(() => setSource(t("Source not available."))); }}>
          <summary>{t("Source code")}</summary><pre>{source || t("Loading…")}</pre>
        </details>
      </section>
    </div>
    {properties.length > 0 && <section className="panel">
      <div className="panel-header"><div><h2>{t("Versions of the defaults")}</h2><p>{t("Each save is a version with what changed. The newest is the one in use; the others can go back into use or be deleted.")}</p></div></div>
      {versions === null ? <p className="muted">{t("Loading…")}</p> : <div className="table-wrap"><table>
        <thead><tr><th>{t("Version")}</th><th>{t("What changed")}</th><th>{t("Values")}</th><th>{t("Saved")}</th><th /></tr></thead>
        <tbody>
          {versions.map((item) => <tr key={item.number}>
            <td>{t("Version {number}", { number: item.number })}{item.current && <> <span className="tag">{t("in use")}</span></>}</td>
            <td>{item.description}</td>
            <td className="pc-mono small">{changed(item.parameters)}</td>
            <td className="small">{[item.saved_by, formatDate(item.saved_at)].join(" · ")}</td>
            <td className="row-actions">{me.is_admin && !item.current && <>
              <button type="button" className="button button-secondary button-small" onClick={() => void store(item.parameters, t("Back to version {number}", { number: item.number }))}><RotateCcw size={14} />{t("Use again")}</button>
              <button type="button" className="button button-secondary button-small" onClick={() => void remove(item.number)}><Trash2 size={14} />{t("Delete")}</button>
            </>}</td>
          </tr>)}
          <tr>
            <td>{t("PlantCraft's")}{!versions.length && <> <span className="tag">{t("in use")}</span></>}</td>
            <td className="muted">{t("The defaults PlantCraft ships")}</td>
            <td className="pc-mono small">{changed(shipped)}</td>
            <td />
            <td className="row-actions">{me.is_admin && versions.length > 0 && <button type="button" className="button button-secondary button-small" onClick={() => void store(shipped, t("Back to PlantCraft's defaults"))}><RotateCcw size={14} />{t("Use again")}</button>}</td>
          </tr>
        </tbody>
      </table></div>}
    </section>}
  </>;
}
