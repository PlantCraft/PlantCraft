/**
 * Tracking (M3): a model simulated against the plant on a schedule. Each tracking runs the model
 * over the last window of plant data, writes model minus plant for every compared variable as a
 * signal in PlantCraft and, when a limit is set, opens "Model off the plant" while the mean
 * absolute error stays above it. The page lists them, starts one now, pauses, and adds new ones.
 */
import { DataTable, confirmAction, type DataColumn } from "@plantcraft/ui";
import { Play, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { formatAgo, t } from "./i18n";
import { runPath } from "./paths";
import type { Me, ModelItem, Tracking, TrackingBody } from "./types";
import { Dialog, ErrorBox, Heading, Link, Loading, message, Pill, reading } from "./ui";

const POLL_MS = 10_000;

/** "a = b" lines as a map (blank lines and lines without "=" are left out). */
export function pairs(text: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at < 1) continue;
    const name = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    if (name && value) found[name] = value;
  }
  return found;
}

/** The limits as numbers; a line whose value is not a positive number is an error. */
export function limitsOf(text: string): Record<string, number> {
  const found: Record<string, number> = {};
  for (const [name, value] of Object.entries(pairs(text))) {
    const limit = Number(value);
    if (!Number.isFinite(limit) || limit <= 0) throw new Error(t("A limit is a positive number: {name}", { name }));
    found[name] = limit;
  }
  return found;
}

export function bodyOf(tracking: Tracking, change: Partial<TrackingBody> = {}): TrackingBody {
  return { project_id: tracking.project_id, model: tracking.model, name: tracking.name, enabled: tracking.enabled, ...tracking.config, ...change };
}

const STATUS_WORDS: Record<string, string> = { queued: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled" };

function LastResult({ tracking }: { tracking: Tracking }) {
  const last = tracking.last;
  if (!last.status) return <small>{t("Not run yet")}</small>;
  const status = last.status === "done" ? "run-done" : last.status === "queued" ? "run-running" : "run-failed";
  return <>
    <span className="nowrap"><Pill status={status} label={t(STATUS_WORDS[last.status] ?? last.status)} />{last.at && <small> {formatAgo(last.at)}</small>}</span>
    {last.detail && <small className="danger">{last.detail}</small>}
    {last.run_id && <small><Link to={runPath({ id: last.run_id })}>{t("Open the simulation")}</Link></small>}
  </>;
}

function Errors({ tracking }: { tracking: Tracking }) {
  const metrics = tracking.last.metrics ?? {};
  const names = Object.keys(tracking.config.compare);
  return <>{names.map((name) => {
    const found = metrics[name];
    const limit = tracking.config.limits[name];
    const off = tracking.open.includes(name);
    return <span key={name} className="nowrap" title={tracking.signals[name]}>
      <b>{name.split(".").slice(-2).join(".")}</b>{" "}
      {found && found.mae !== null ? t("MAE {mae} · bias {bias}", { mae: reading(found.mae), bias: reading(found.bias ?? 0) }) : t("no value")}
      {limit !== undefined && <small className={off ? "danger" : ""}> {off ? t("off the plant (limit {limit})", { limit: reading(limit) }) : t("limit {limit}", { limit: reading(limit) })}</small>}
    </span>;
  })}</>;
}

export function TrackingPage({ me }: { me: Me }) {
  const [trackings, setTrackings] = useState<Tracking[] | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const read = useCallback(() => { api.trackings().then((found) => { setTrackings(found); setError(""); }).catch((err) => setError(message(err))); }, []);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, POLL_MS);
    return () => window.clearInterval(timer);
  }, [read]);
  const act = (work: Promise<unknown>) => { work.then(read).catch((err) => setError(message(err))); };
  const remove = async (tracking: Tracking) => {
    if (await confirmAction(t("Its error signals stay in PlantCraft."), { title: t("Delete the tracking {name}?", { name: tracking.name }), confirm: t("Delete"), danger: true })) act(api.deleteTracking(tracking.id));
  };
  const columns: DataColumn<Tracking>[] = [
    { key: "name", label: t("Tracking"), sort: (item) => item.name.toLowerCase(), render: (item) => <><b>{item.name}</b><small>{item.model.split(".").pop()} · {t("last {window} min every {every} min", { window: reading(item.config.window_minutes), every: reading(item.config.every_minutes) })}</small></> },
    { key: "errors", label: t("Model minus plant"), render: (item) => <Errors tracking={item} /> },
    { key: "last", label: t("Last run"), className: "hide-narrow", sort: (item) => item.last.at ?? "", render: (item) => <LastResult tracking={item} /> },
    { key: "state", label: t("State"), sort: (item) => (item.enabled ? 0 : 1), render: (item) => me.can_edit
      ? <label className="nowrap"><input type="checkbox" checked={item.enabled} onChange={(event) => act(api.saveTracking(item.id, bodyOf(item, { enabled: event.target.checked })))} /> {item.enabled ? t("On") : t("Paused")}</label>
      : <span>{item.enabled ? t("On") : t("Paused")}</span> },
    ...(me.can_edit ? [{ key: "actions", label: "", render: (item: Tracking) => <span className="nowrap">
      <button type="button" className="button button-secondary button-small" onClick={() => act(api.runTracking(item.id))}><Play />{t("Run now")}</button>{" "}
      <button type="button" className="button button-secondary button-small" aria-label={t("Delete")} onClick={() => void remove(item)}><Trash2 /></button>
    </span> }] : []),
  ];
  if (trackings === null) return error ? <ErrorBox text={error} /> : <Loading />;
  return <div className="page">
    <Heading title={t("Tracking")} actions={me.can_edit ? <button type="button" className="button button-primary" onClick={() => setAdding(true)}><Plus />{t("New tracking")}</button> : undefined} />
    <p className="muted">{t("A tracking simulates a model over the last window of plant data on a schedule. Model minus plant is written as a signal in PlantCraft for each compared variable, and an optional limit on its mean absolute error raises \"Model off the plant\".")}</p>
    {error && <ErrorBox text={error} />}
    {trackings.length === 0 ? <div className="panel empty"><h2>{t("No tracking yet")}</h2></div>
      : <DataTable rows={trackings} columns={columns} rowKey={(item) => item.id} label={t("Trackings")} />}
    {adding && <NewTrackingDialog onClose={() => setAdding(false)} onCreated={() => { setAdding(false); read(); }} />}
  </div>;
}

export function NewTrackingDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [chosen, setChosen] = useState("");
  const [name, setName] = useState("");
  const [compare, setCompare] = useState("");
  const [inputs, setInputs] = useState("");
  const [limits, setLimits] = useState("");
  const [windowMinutes, setWindowMinutes] = useState("60");
  const [everyMinutes, setEveryMinutes] = useState("15");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.models().then(setModels).catch((err) => setError(message(err))); }, []);
  const create = async () => {
    const model = models.find((item) => `${item.project_id}/${item.model}` === chosen);
    if (!model) return setError(t("Choose a model."));
    setBusy(true);
    try {
      await api.createTracking({
        project_id: model.project_id, model: model.model, name: name.trim() || model.name, enabled: true,
        compare: pairs(compare), inputs: pairs(inputs), limits: limitsOf(limits),
        window_minutes: Number(windowMinutes), every_minutes: Number(everyMinutes), intervals: 500, overrides: {},
      });
      onCreated();
    } catch (err) { setError(message(err)); setBusy(false); }
  };
  return <Dialog title={t("New tracking")} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !chosen || !compare.trim()} onClick={() => void create()}>{t("Create")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void create(); }}>
      <label>{t("Model")}<select value={chosen} onChange={(event) => setChosen(event.target.value)}>
        <option value="">{t("Choose a model")}</option>
        {models.map((item) => <option key={`${item.project_id}/${item.model}`} value={`${item.project_id}/${item.model}`}>{item.name} · {item.project}</option>)}
      </select></label>
      <label>{t("Name")} <small>{t("optional")}</small><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Feed tank against the plant")} /></label>
      <label>{t("Window (minutes up to now)")}<input type="number" min={5} max={10080} value={windowMinutes} onChange={(event) => setWindowMinutes(event.target.value)} /></label>
      <label>{t("Every (minutes)")}<input type="number" min={5} max={10080} value={everyMinutes} onChange={(event) => setEveryMinutes(event.target.value)} /></label>
      <label className="pc-span-all">{t("Compare with the plant")} <small>{t("one per line: variable = signal")}</small>
        <textarea rows={3} value={compare} onChange={(event) => setCompare(event.target.value)} placeholder="tank.level = plant:LT-101" /></label>
      <label className="pc-span-all">{t("Inputs from the plant")} <small>{t("optional, one per line: input = signal")}</small>
        <textarea rows={2} value={inputs} onChange={(event) => setInputs(event.target.value)} placeholder="qin = plant:FT-100" /></label>
      <label className="pc-span-all">{t("Alarm limits")} <small>{t("optional, one per line: variable = mean absolute error")}</small>
        <textarea rows={2} value={limits} onChange={(event) => setLimits(event.target.value)} placeholder="tank.level = 0.05" /></label>
    </form>
  </Dialog>;
}
