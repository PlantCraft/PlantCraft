/**
 * A new study, on a page of its own (`/studies/new`, round 8 M2): one model simulated once or over
 * a sweep of its inputs and parameters. Each keeps the model's value, takes a fixed one, or varies
 * over a range (from, to, how many values) or a list; every combination is one simulation in the
 * queue. Beside the form, the page says how many simulations that is and about how long they take.
 * An optimization study instead changes a few of them within bounds, one simulation at a time,
 * until an indicator is as small, as large or as close to a target as it gets.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { formatDuration, t } from "./i18n";
import { SOLVERS, lastSolver } from "./RunDialogs";
import type { ClassInfo, ComputeOffer, ComputePlacement, DecisionVariable, Diagram, Goal, OptimizationConstraint, OptimizationSpec, Parameter, SimSettings, Study, StudyPreview, SweepItem } from "./types";
import { message } from "./ui";

type Mode = "model" | "fixed" | "range" | "list" | "optimize";
/** What a study does: compare every combination of values, or find the best ones. */
export type StudyType = "sweep" | "optimization";
/** The statistics an objective or a constraint reads (as the study's indicators). */
const STATISTIC_NAMES: Record<string, string> = {
  final: "Final value", overshoot: "Overshoot (%)", settling: "Settling time (s)", iae: "IAE (integral of |deviation|)",
  min: "Smallest", max: "Largest", mean: "Mean", integral: "Integral",
};
export const OPTIMIZERS: Array<{ id: "" | OptimizationSpec["method"]; label: string }> = [
  { id: "", label: "Automatic (Nelder-Mead, or COBYLA with constraints)" },
  { id: "nelder-mead", label: "Nelder-Mead (no constraints)" },
  { id: "cobyla", label: "COBYLA (constraints, no derivatives)" },
  { id: "slsqp", label: "SLSQP (constraints, finite differences)" },
];
/** How a study drives one of the model's inputs (round 9 M6). */
export type Shape = "constant" | "step" | "ramp";
interface Row { mode: Mode; value: string; start: string; stop: string; count: string; values: string; shape?: Shape; before?: string; at?: string; end?: string }
const EMPTY: Row = { mode: "model", value: "", start: "", stop: "", count: "5", values: "" };

/** The simulation's settings a study may vary as well (round 9 M7); their fixed value is the
 * Experiment's. Named with an @ so they never meet a parameter. */
export const SETTING_ROWS: Array<{ path: string; label: string; unit: string }> = [
  { path: "@stop", label: "Stop time", unit: "s" },
  { path: "@intervals", label: "Intervals", unit: "" },
  { path: "@tolerance", label: "Tolerance", unit: "" },
  { path: "@method", label: "Solver", unit: "" },
];
const SIZE_TEXT: Record<ComputePlacement["size"], string> = {
  small: "Small (1 CPU, 1 GB)",
  medium: "Medium (2 CPUs, 4 GB)",
  large: "Large (4 CPUs, 16 GB)",
};
const isSetting = (path: string) => path.startsWith("@");
/** What a person reads for a varied name: a setting's own words (Integrator), else the name. */
export function sweptLabel(name: string): string {
  const setting = SETTING_ROWS.find((item) => item.path === name);
  return setting ? t(setting.label) : name;
}

/** The parameters a study can set: the model's own and those of its components (tank.area). */
export function studyParameters(diagram: Diagram | null): Array<Parameter & { path: string }> {
  if (!diagram) return [];
  const own = diagram.parameters.filter((item) => !item.name.includes(".")).map((item) => ({ ...item, path: item.name }));
  const inner = diagram.components.filter((item) => !item.connector).flatMap((component) =>
    component.parameters.map((item) => ({ ...item, path: `${component.name}.${item.name}`, value: component.values[item.name] ?? item.value })));
  return [...own, ...inner];
}

function number(text: string, name: string): number | boolean {
  const value = text.trim();
  if (value === "true" || value === "false") return value === "true";
  if (value === "" || !Number.isFinite(Number(value))) throw new Error(t("{name}: write a number, true or false.", { name }));
  return Number(value);
}

export type InputShape = { shape: Shape; before?: number; at?: number; end?: number };

/** The rows as the API's sweep, fixed values and driven inputs (`inputs` names the model's
 * inputs: their rows say how each is driven). */
export function sweepOf(rows: Record<string, Row>, inputs: string[] = []): { sweep: SweepItem[]; overrides: Record<string, number | boolean>; inputs: Record<string, InputShape>; variables: DecisionVariable[] } {
  const sweep: SweepItem[] = [];
  const variables: DecisionVariable[] = [];
  const overrides: Record<string, number | boolean> = {};
  const driven: Record<string, InputShape> = {};
  for (const [name, row] of Object.entries(rows)) {
    if (name === "@method") {
      if (row.mode !== "list") continue;
      const values = row.values.split(/[;,\s]+/).filter(Boolean);
      if (!values.length) throw new Error(t("Solver: tick at least one."));
      const unknown = values.find((value) => !SOLVERS.some((item) => item.id === value));
      if (unknown) throw new Error(t("Solver: {name} is not one.", { name: unknown }));
      sweep.push({ name, mode: "list", values });
      continue;
    }
    if (inputs.includes(name) && row.mode !== "model") {
      const shape = row.shape ?? "constant";
      driven[name] = shape === "constant" ? { shape } : {
        shape, before: Number(number(row.before ?? "", t("{name} before", { name }))), at: Number(number(row.at ?? "", t("{name} at", { name }))),
        ...(shape === "ramp" ? { end: Number(number(row.end ?? "", t("{name} until", { name }))) } : {}),
      };
      if (shape === "ramp" && (driven[name].end as number) <= (driven[name].at as number)) throw new Error(t("{name}: the ramp ends after it starts.", { name }));
    }
    if (row.mode === "fixed" && row.value.trim()) overrides[name] = number(row.value, name);
    if (row.mode === "optimize") {
      const [min, max] = [Number(number(row.start, t("{name} smallest", { name }))), Number(number(row.stop, t("{name} largest", { name })))];
      const start = row.value.trim() ? Number(number(row.value, t("{name} start", { name }))) : (min + max) / 2;
      if (!(min < max)) throw new Error(t("{name}: the smallest value must be below the largest.", { name }));
      if (start < min || start > max) throw new Error(t("{name}: the start value must be within its bounds.", { name }));
      variables.push({ name, start, min, max });
    }
    if (row.mode === "range") {
      const count = Math.round(Number(row.count));
      if (!(count >= 1)) throw new Error(t("{name}: how many values?", { name }));
      sweep.push({ name, mode: "range", start: Number(number(row.start, name)), stop: Number(number(row.stop, name)), count });
    }
    if (row.mode === "list") {
      const values = row.values.split(/[;\s]+/).filter(Boolean).map((item) => number(item.replace(/,$/, ""), name));
      if (!values.length) throw new Error(t("{name}: the list has no values.", { name }));
      sweep.push({ name, mode: "list", values });
    }
  }
  return { sweep, overrides, inputs: driven, variables };
}

function rowsFrom(study: Study | undefined): Record<string, Row> {
  const spec = study?.spec;
  if (!spec || !("options" in spec)) return {};
  const rows: Record<string, Row> = {};
  for (const [name, value] of Object.entries(spec.options.overrides ?? {})) rows[name] = { ...EMPTY, mode: "fixed", value: String(value) };
  for (const [name, item] of Object.entries(spec.options.inputs ?? {})) {
    rows[name] = { ...EMPTY, mode: item.value !== undefined ? "fixed" : "model", value: String(item.value ?? ""), shape: item.shape,
      before: String(item.before ?? ""), at: String(item.at ?? ""), end: String(item.end ?? "") };
  }
  for (const item of spec.optimization?.variables ?? []) {
    rows[item.name] = { ...(rows[item.name] ?? EMPTY), mode: "optimize", value: String(item.start), start: String(item.min), stop: String(item.max) };
  }
  for (const item of spec.sweep ?? []) {
    const kept = rows[item.name] ?? EMPTY;
    rows[item.name] = item.mode === "range"
      ? { ...kept, mode: "range", start: String(item.start), stop: String(item.stop), count: String(item.count) }
      : { ...kept, mode: "list", values: (item.values ?? []).join(" ") };
  }
  return rows;
}

/** A parameter a study can set, as the dialog lists it. */
export type StudyParameter = { path: string; comment: string; value: string | null; unit: string };

export function StudyForm({ projectId, models, model: chosen, like, parameters: given, settings, indicators: suggested, modelField, onClose, onStarted }: {
  projectId: string; models: Array<Pick<ClassInfo, "name" | "short"> & Partial<ClassInfo>>; model?: string; like?: Study;
  /** The page's own choice of model (any model of any project), in place of this form's list. */
  modelField?: ReactNode;
  /** A diagram model's parameters and settings, read from its diagram (the code's are asked of omc). */
  parameters?: StudyParameter[]; settings?: SimSettings; indicators?: string[];
  onClose: () => void; onStarted: (study: Study) => void;
}) {
  const runnable = models.filter((item) => item.simulable !== false);
  const [model, setModel] = useState(like?.model ?? chosen ?? runnable[0]?.name ?? "");
  const info = runnable.find((item) => item.name === model);
  const spec = like?.spec && "options" in like.spec ? like.spec : undefined;
  const experiment = settings ? { StartTime: settings.start, StopTime: settings.stop, Tolerance: settings.tolerance } : info?.experiment ?? {};
  const [name, setName] = useState(like ? t("{name} (again)", { name: like.name }) : "");
  const [description, setDescription] = useState(like?.description ?? "");
  const [start, setStart] = useState(String(spec?.options.start ?? experiment.StartTime ?? 0));
  const [stop, setStop] = useState(String(spec?.options.stop ?? experiment.StopTime ?? 1));
  const [intervals, setIntervals] = useState(String(spec?.options.intervals ?? (settings ? Math.max(1, Math.round((settings.stop - settings.start) / settings.interval)) : 500)));
  const [tolerance, setTolerance] = useState(String(spec?.options.tolerance ?? experiment.Tolerance ?? 1e-6));
  const [method, setMethod] = useState(spec?.options.method ?? settings?.solver ?? lastSolver(model));
  const [limit, setLimit] = useState(spec?.options.time_limit ? String(spec.options.time_limit / 60) : "");
  const [environment, setEnvironment] = useState(spec?.options.compute?.environment ?? "standard");
  const [size, setSize] = useState<ComputePlacement["size"]>(spec?.options.compute?.size ?? "small");
  const [offer, setOffer] = useState<ComputeOffer | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>(() => rowsFrom(like));
  const [indicators, setIndicators] = useState<string[]>(spec?.indicators ?? suggested?.slice(0, 20) ?? []);
  const [indicator, setIndicator] = useState("");
  const kept = spec?.optimization;
  const [type, setType] = useState<StudyType>(kept ? "optimization" : "sweep");
  const [objective, setObjective] = useState({ variable: kept?.objective.variable ?? "", statistic: kept?.objective.statistic ?? "final", goal: (kept?.objective.goal ?? "minimize") as Goal, target: String(kept?.objective.target ?? "") });
  const [constraints, setConstraints] = useState<Array<{ variable: string; statistic: string; op: "<=" | ">="; value: string }>>(
    () => (kept?.constraints ?? []).map((item) => ({ ...item, value: String(item.value) })));
  const [optimizer, setOptimizer] = useState<"" | OptimizationSpec["method"]>(kept?.method ?? "");
  const [budget, setBudget] = useState(String(kept?.max_simulations ?? 60));
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [variables, setVariables] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [preview, setPreview] = useState<StudyPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The experiment of a newly chosen model, unless the study copies another.
  useEffect(() => { api.computeOffer().then(setOffer).catch(() => setOffer(null)); }, []);
  useEffect(() => {
    if (like || !info || settings) return;
    setStart(String(info.experiment?.StartTime ?? 0));
    setStop(String(info.experiment?.StopTime ?? 1));
    setMethod(lastSolver(info.name));
  }, [info, like]);
  useEffect(() => {
    if (!model) return;
    setDiagram(null);
    if (!given) api.diagram(projectId, model).then(setDiagram).catch(() => setDiagram(null));
    // What to measure: the variables of this model's last simulation, else its outputs.
    api.runs({ model, kind: "simulate", status: "done", limit: "1" })
      .then((found) => (found[0] ? api.variables(found[0].id) : []))
      .then((found) => setVariables(found.filter((item) => item.column !== null && !item.protected && !item.name.startsWith("der(") && !item.name.startsWith("$")).map((item) => item.name)))
      .catch(() => setVariables([]));
  }, [projectId, model, given]);

  const parameters: StudyParameter[] = useMemo(() => given ?? studyParameters(diagram).map((item) => ({
    path: item.path, comment: item.comment, value: item.value ?? item.default, unit: item.unit && item.unit !== "1" ? item.unit : "",
  })), [diagram, given]);
  const ready = Boolean(given) || diagram !== null;
  // The model's own inputs (a model written as code: u and d of a process), driven by the study.
  const inputNames = useMemo(() => (given ? [] : diagram?.inputs ?? []), [diagram, given]);
  const matches = (path: string, comment = "") => rows[path]?.mode && rows[path].mode !== "model"
    || !search || `${path} ${comment}`.toLowerCase().includes(search.toLowerCase());
  const shown = parameters.filter((item) => matches(item.path, item.comment));
  // Rows the study set that this model does not list (copied from another study).
  const extra = Object.keys(rows).filter((path) => !isSetting(path) && !inputNames.includes(path) && !parameters.some((item) => item.path === path));
  const experimentValue: Record<string, string> = { "@stop": `${stop} s`, "@intervals": intervals, "@tolerance": tolerance, "@method": SOLVERS.find((item) => item.id === method)?.label ?? method };

  let built: ReturnType<typeof sweepOf> | null = null;
  let rowError = "";
  try { built = sweepOf(rows, inputNames); } catch (err) { rowError = message(err); }
  const sweepKey = JSON.stringify(built?.sweep ?? null);
  useEffect(() => {
    if (!model || !built) { setPreview(null); return; }
    const timer = window.setTimeout(() => {
      api.previewStudy(projectId, model, built.sweep).then((found) => { setPreview(found); setPreviewError(""); })
        .catch((err) => { setPreview(null); setPreviewError(message(err)); });
    }, 300);
    return () => window.clearTimeout(timer);
    // The sweep is compared by value (sweepKey).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, model, sweepKey]);

  const optimizing = type === "optimization";
  let optimization: Record<string, unknown> | null = null;
  let optimizationError = "";
  if (optimizing && built) {
    try {
      if (!built.variables.length) throw new Error(t("Choose Optimize for at least one input or parameter."));
      if (built.sweep.length) throw new Error(t("An optimization varies no other value: set ranges and lists back to a value."));
      if (!objective.variable.trim()) throw new Error(t("Choose the variable the optimization makes best."));
      const found: OptimizationConstraint[] = constraints.map((item) => {
        if (!item.variable.trim()) throw new Error(t("A constraint needs a variable."));
        return { variable: item.variable.trim(), statistic: item.statistic, op: item.op, value: Number(number(item.value, item.variable)) };
      });
      if (optimizer === "nelder-mead" && found.length) throw new Error(t("Nelder-Mead takes no constraints: use COBYLA or SLSQP."));
      const most = Math.round(Number(budget));
      if (!(most >= 2)) throw new Error(t("Allow at least 2 simulations."));
      optimization = {
        variables: built.variables, constraints: found, max_simulations: most,
        objective: { variable: objective.variable.trim(), statistic: objective.statistic, goal: objective.goal,
          ...(objective.goal === "target" ? { target: Number(number(objective.target, t("Target"))) } : {}) },
        ...(optimizer ? { method: optimizer } : {}),
      };
    } catch (err) { optimizationError = message(err); }
  }
  const set = (path: string, change: Partial<Row>) => setRows({ ...rows, [path]: { ...(rows[path] ?? EMPTY), ...change } });
  const addIndicator = (value: string) => {
    const clean = value.trim();
    if (clean && !indicators.includes(clean) && indicators.length < 20) setIndicators([...indicators, clean]);
    setIndicator("");
  };
  const tooMany = preview !== null && (optimizing ? Number(budget) > preview.limit : preview.count > preview.limit);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const { sweep, overrides, inputs, variables: optimized } = sweepOf(rows, inputNames);
      const settings: Record<string, unknown> = {
        model, name: name.trim() || (optimizing ? t("Optimization of {names}", { names: optimized.map((item) => item.name.split(".").pop()).join(", ") }) : sweep.length ? t("Sweep of {names}", { names: sweep.map((item) => item.name.split(".").pop()).join(", ") }) : t("Simulation of {model}", { model: info?.short ?? model })),
        description: description.trim(), start: Number(start), stop: Number(stop), intervals: Number(intervals),
        tolerance: Number(tolerance), method, overrides, sweep, indicators: indicator.trim() ? [...indicators, indicator.trim()] : indicators,
      };
      if (Object.keys(inputs).length) settings.inputs = inputs;
      if (optimizing && optimization) settings.optimization = optimization;
      if (limit.trim()) settings.time_limit = Number(limit) * 60;
      if (environment !== "standard" || size !== "small") settings.compute = { environment, size };
      onStarted(await api.createStudy(projectId, settings));
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };

  /** One row of the table: an input, a parameter or a simulation setting (round 9 M6, M7). */
  const sweepRow = (item: { path: string; comment: string; model: string }, kind: "input" | "parameter" | "setting") => {
    const row = rows[item.path] ?? EMPTY;
    const shape = row.shape ?? "constant";
    const integrator = item.path === "@method";
    const ticked = row.values.split(/[;,\s]+/).filter(Boolean);
    return <tr key={item.path}>
      <td>{kind === "setting" ? <strong>{item.comment}</strong> : <strong className="pc-mono">{item.path}</strong>}{kind !== "setting" && item.comment && <small>{item.comment}</small>}</td>
      <td className="pc-mono">{item.model}</td>
      <td><select aria-label={t("How {name} is set", { name: kind === "setting" ? item.comment : item.path })} value={row.mode} onChange={(event) => set(item.path, { mode: event.target.value as Mode })}>
        <option value="model">{kind === "setting" ? t("Simulation settings value") : kind === "input" ? t("Not driven") : t("Model's value")}</option>
        {kind !== "setting" && <option value="fixed">{t("Fixed")}</option>}
        {optimizing ? kind !== "setting" && <option value="optimize">{t("Optimize")}</option> : <>
          {!integrator && <option value="range">{t("Range")}</option>}
          <option value="list">{t("List")}</option>
        </>}
        {/* A study copied from another type keeps what it set, until it is changed. */}
        {optimizing && (row.mode === "range" || row.mode === "list") && <option value={row.mode}>{t(row.mode === "range" ? "Range" : "List")}</option>}
        {!optimizing && row.mode === "optimize" && <option value="optimize">{t("Optimize")}</option>}
      </select></td>
      <td className="mc-sweep-values">
        {integrator && row.mode === "list" ? <span className="mc-ticks" role="group" aria-label={t("Solvers to compare")}>
          {SOLVERS.map((solver) => <label key={solver.id} className="check"><input type="checkbox" checked={ticked.includes(solver.id)}
            onChange={(event) => set(item.path, { values: (event.target.checked ? [...ticked, solver.id] : ticked.filter((other) => other !== solver.id)).join(" ") })} /> {t(solver.label)}</label>)}
        </span> : <>
        {row.mode === "fixed" && <input aria-label={t("Value of {name}", { name: item.path })} value={row.value} onChange={(event) => set(item.path, { value: event.target.value })} />}
        {row.mode === "range" && <span className="mc-range">
          <input aria-label={t("From value of {name}", { name: item.path })} placeholder={t("from")} value={row.start} onChange={(event) => set(item.path, { start: event.target.value })} />
          <input aria-label={t("To value of {name}", { name: item.path })} placeholder={t("to")} value={row.stop} onChange={(event) => set(item.path, { stop: event.target.value })} />
          <input aria-label={t("How many values of {name}", { name: item.path })} type="number" min={1} max={1000} value={row.count} onChange={(event) => set(item.path, { count: event.target.value })} title={t("How many values, evenly spaced")} />
        </span>}
        {row.mode === "optimize" && <span className="mc-range">
          <input aria-label={t("Smallest value of {name}", { name: item.path })} placeholder={t("smallest")} value={row.start} onChange={(event) => set(item.path, { start: event.target.value })} />
          <input aria-label={t("Largest value of {name}", { name: item.path })} placeholder={t("largest")} value={row.stop} onChange={(event) => set(item.path, { stop: event.target.value })} />
          <input aria-label={t("Start value of {name}", { name: item.path })} placeholder={t("start")} value={row.value} onChange={(event) => set(item.path, { value: event.target.value })} title={t("Where the optimizer starts; the middle of the bounds when empty")} />
        </span>}
        {row.mode === "list" && <input aria-label={t("Values of {name}", { name: item.path })} placeholder={t("e.g. 1 2.5 4")} value={row.values} onChange={(event) => set(item.path, { values: event.target.value })} />}
        </>}
        {kind === "input" && row.mode !== "model" && <span className="mc-input-shape">
          <select aria-label={t("Shape of {name}", { name: item.path })} value={shape} onChange={(event) => set(item.path, { shape: event.target.value as Shape })}>
            <option value="constant">{t("Held at the value")}</option>
            <option value="step">{t("Step to the value")}</option>
            <option value="ramp">{t("Ramp to the value")}</option>
          </select>
          {shape !== "constant" && <>
            <label>{t("from")}<input aria-label={t("{name} before", { name: item.path })} value={row.before ?? ""} onChange={(event) => set(item.path, { before: event.target.value })} /></label>
            <label>{t("at")}<input aria-label={t("{name} at", { name: item.path })} value={row.at ?? ""} onChange={(event) => set(item.path, { at: event.target.value })} /> s</label>
          </>}
          {shape === "ramp" && <label>{t("until")}<input aria-label={t("{name} until", { name: item.path })} value={row.end ?? ""} onChange={(event) => set(item.path, { end: event.target.value })} /> s</label>}
        </span>}
      </td>
    </tr>;
  };
  const count = preview && <p className={`mc-study-count${tooMany ? " danger" : preview.count > preview.warn_above ? " mc-warn" : ""}`}>
    <b className="pc-num">{preview.count}</b> {preview.count === 1 ? t("simulation") : t("simulations")}
    {preview.seconds_total !== null && <small>{t("about {time}", { time: formatDuration(Math.max(1, preview.seconds_total)) })}</small>}
  </p>;
  return <div className="mc-study-form">
    <div className="mc-study-sections">
    {error && <div className="notice notice-error">{error}</div>}
    <section className="panel mc-study-section" aria-label={t("What it studies")}>
      <h2>{t("What it studies")}</h2>
      <div className="mc-study-type" role="radiogroup" aria-label={t("Type of study")}>
        {([["sweep", "Compare values", "Every combination of the values its inputs and parameters take, side by side."],
          ["optimization", "Find the best values", "The values of a few inputs or parameters that make an indicator smallest, largest or closest to a target."]] as const).map(([value, label, detail]) =>
          <label key={value} className={`mc-study-type-option${type === value ? " active" : ""}`}>
            <input type="radio" name="study-type" value={value} checked={type === value} onChange={() => { setType(value); if (!objective.variable) setObjective({ ...objective, variable: indicators[0] ?? variables[0] ?? "" }); }} />
            <strong>{t(label)}</strong><small>{t(detail)}</small>
          </label>)}
      </div>
      <div className="form-grid">
      {modelField ?? <label>{t("Model")}
        <select value={model} onChange={(event) => setModel(event.target.value)} disabled={Boolean(like)}>
          {runnable.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
      </label>}
      <label>{t("Name")} <small>{t("optional")}</small><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Controller tuning")} /></label>
      <label className="pc-span-all">{t("Description")} <small>{t("optional")}</small><input value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} placeholder={t("What the study answers")} /></label>
      </div>
    </section>
    <section className="panel mc-study-section" aria-label={t("Simulation settings")}>
      <h2>{t("Simulation settings")}</h2>
    <div className="form-grid">
      <label>{t("Start time")} <small>{t("seconds")}</small><input type="number" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label>{t("Stop time")} <small>{t("seconds")}</small><input type="number" value={stop} onChange={(event) => setStop(event.target.value)} /></label>
      <label>{t("Intervals")}<input type="number" min={1} value={intervals} onChange={(event) => setIntervals(event.target.value)} /></label>
      <label>{t("Tolerance")}<input type="number" step="any" value={tolerance} onChange={(event) => setTolerance(event.target.value)} /></label>
      <label>{t("Solver")}
        <select value={method} onChange={(event) => setMethod(event.target.value)}>
          {SOLVERS.map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}
        </select>
      </label>
      <label>{t("Time limit per simulation")} <small>{t("minutes, optional")}</small><input type="number" min={1} value={limit} onChange={(event) => setLimit(event.target.value)} placeholder={t("e.g. 30")} /></label>
      {offer?.suite && <>
        <label>{t("Environment")} <small>{t("where it runs")}</small>
          <select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
            {[...new Set(["standard", environment, ...offer.environments])].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>{t("Size")} <small>{t("CPUs and memory per simulation")}</small>
          <select value={size} onChange={(event) => setSize(event.target.value as ComputePlacement["size"])}>
            {(Object.keys(SIZE_TEXT) as ComputePlacement["size"][]).map((item) => <option key={item} value={item}>{t(SIZE_TEXT[item])}</option>)}
          </select>
        </label>
      </>}
    </div>
    {offer?.suite && offer.workers > 0 && (!offer.environments.includes(environment) || !offer.sizes.includes(size)) && <p className="muted small">{t("No compute worker online offers this now: the simulations wait until one does.")}</p>}
    </section>
    <section className="panel mc-study-section" aria-label={t("Inputs and parameters")}>
    <h2>{t("Inputs and parameters")}</h2>
    <p className="muted small">{optimizing ? t("Keep the model's value, fix another, or let the optimizer change it between its smallest and largest value.")
      : t("Keep the model's value, fix another, or vary it over a range (from, to, how many values) or a list. Every combination is one simulation.")}</p>
    {!ready ? <p className="muted small">{t("Reading the model's parameters…")}</p> : <>
      {parameters.length > 8 && <input type="search" className="mc-param-search" value={search} placeholder={t("Search parameters")} aria-label={t("Search parameters")} onChange={(event) => setSearch(event.target.value)} />}
      <div className="mc-params-table">
        <table className="table mc-sweep-table">
          <thead><tr><th>{t("Name")}</th><th>{t("In the model")}</th><th>{t("In the study")}</th><th>{t("Values")}</th></tr></thead>
          <tbody>
            {inputNames.length > 0 && <tr className="mc-sweep-group"><th colSpan={4}>{t("Inputs")}<small>{t("Each one held at a value, or a step or a ramp to it from a value before.")}</small></th></tr>}
            {inputNames.filter((path) => matches(path)).map((path) => sweepRow({ path, comment: "", model: t("Its start value") }, "input"))}
            {(shown.length > 0 || extra.length > 0) && <tr className="mc-sweep-group"><th colSpan={4}>{t("Parameters")}</th></tr>}
            {[...shown.map((item) => ({ path: item.path, comment: item.comment, model: `${item.value ?? "–"}${item.unit ? ` ${item.unit}` : ""}` })),
              ...extra.map((path) => ({ path, comment: "", model: "–" }))].map((item) => sweepRow(item, "parameter"))}
            {!optimizing && <>
            <tr className="mc-sweep-group"><th colSpan={4}>{t("Simulation settings")}<small>{t("Fixed in Simulation settings above; vary them here to compare.")}</small></th></tr>
            {SETTING_ROWS.map((item) => sweepRow({ path: item.path, comment: t(item.label), model: experimentValue[item.path] ?? "–" }, "setting"))}
            </>}
          </tbody>
        </table>
      </div>
      {parameters.length === 0 && extra.length === 0 && inputNames.length === 0 && <p className="muted small">{t("This model has no input or parameter to vary; its simulation settings still can.")}</p>}
    </>}
    {rowError && <p className="danger small">{rowError}</p>}
    {previewError && <p className="danger small">{previewError}</p>}
    </section>
    {optimizing && <section className="panel mc-study-section" aria-label={t("Objective")}>
      <h2>{t("Objective")}</h2>
      <p className="muted small">{t("The indicator the optimizer makes best, measured in every simulation, and the limits other indicators must keep.")}</p>
      <div className="form-grid">
        <label>{t("Variable")}<input list="mc-study-variables" value={objective.variable} placeholder={variables[0] ?? diagram?.outputs[0] ?? "tank.level"} onChange={(event) => setObjective({ ...objective, variable: event.target.value })} /></label>
        <label>{t("Indicator")}<select value={objective.statistic} onChange={(event) => setObjective({ ...objective, statistic: event.target.value })}>
          {Object.entries(STATISTIC_NAMES).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
        </select></label>
        <label>{t("Goal")}<select value={objective.goal} onChange={(event) => setObjective({ ...objective, goal: event.target.value as Goal })}>
          <option value="minimize">{t("Minimize")}</option><option value="maximize">{t("Maximize")}</option><option value="target">{t("Reach a value")}</option>
        </select></label>
        {objective.goal === "target" && <label>{t("Target")}<input value={objective.target} onChange={(event) => setObjective({ ...objective, target: event.target.value })} placeholder={t("e.g. 2.5")} /></label>}
        <label>{t("Method")}<select value={optimizer} onChange={(event) => setOptimizer(event.target.value as typeof optimizer)}>
          {OPTIMIZERS.map((item) => <option key={item.id} value={item.id}>{t(item.label)}</option>)}
        </select></label>
        <label>{t("Most simulations")}<input type="number" min={2} value={budget} onChange={(event) => setBudget(event.target.value)} /></label>
      </div>
      <h3 className="mc-subtitle">{t("Constraints")} <small className="muted">{t("optional")}</small></h3>
      {constraints.map((item, index) => {
        const change = (patch: Partial<typeof item>) => setConstraints(constraints.map((other, at) => (at === index ? { ...other, ...patch } : other)));
        return <div key={index} className="mc-constraint">
          <input list="mc-study-variables" aria-label={t("Variable of constraint {n}", { n: index + 1 })} value={item.variable} placeholder="tank.level" onChange={(event) => change({ variable: event.target.value })} />
          <select aria-label={t("Indicator of constraint {n}", { n: index + 1 })} value={item.statistic} onChange={(event) => change({ statistic: event.target.value })}>
            {Object.entries(STATISTIC_NAMES).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
          </select>
          <select aria-label={t("Comparison of constraint {n}", { n: index + 1 })} value={item.op} onChange={(event) => change({ op: event.target.value as "<=" | ">=" })}>
            <option value="<=">≤</option><option value=">=">≥</option>
          </select>
          <input aria-label={t("Limit of constraint {n}", { n: index + 1 })} value={item.value} placeholder={t("limit")} onChange={(event) => change({ value: event.target.value })} />
          <button type="button" className="icon-button" aria-label={t("Remove constraint {n}", { n: index + 1 })} onClick={() => setConstraints(constraints.filter((_, at) => at !== index))}>×</button>
        </div>;
      })}
      {constraints.length < 10 && <button type="button" className="button button-small button-secondary" onClick={() => setConstraints([...constraints, { variable: objective.variable, statistic: "max", op: "<=", value: "" }])}>{t("Add a constraint")}</button>}
      {optimizationError && <p className="danger small">{optimizationError}</p>}
    </section>}
    <section className="panel mc-study-section" aria-label={t("What it compares")}>
    <h2>{t("What it compares")}</h2>
    <p className="muted small">{t("Variables measured in every simulation (final value, overshoot, settling time, IAE…), to rank and compare the simulations side by side.")}</p>
    <div className="mc-chips">
      {indicators.map((item) => <span key={item} className="tag mc-tag">{item} <button type="button" className="link-button" aria-label={t("Remove {name}", { name: item })} onClick={() => setIndicators(indicators.filter((other) => other !== item))}>×</button></span>)}
      <form className="mc-inline-field" onSubmit={(event) => { event.preventDefault(); addIndicator(indicator); }}>
        <input list="mc-study-variables" value={indicator} placeholder={variables[0] ?? diagram?.outputs[0] ?? "tank.level"} aria-label={t("Variable to measure")} onChange={(event) => setIndicator(event.target.value)} />
        <button type="submit" className="button button-small button-secondary" disabled={!indicator.trim()}>{t("Add")}</button>
      </form>
      <datalist id="mc-study-variables">{(variables.length ? variables : suggested ?? diagram?.outputs ?? []).slice(0, 500).map((item) => <option key={item} value={item} />)}</datalist>
    </div>
    </section>
    <div className="form-actions">
      <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
      <button type="button" className="button button-primary" disabled={busy || !model || Boolean(rowError) || tooMany || (optimizing && !optimization)} onClick={() => void submit()}>{busy ? t("Starting…") : t("Start the study")}</button>
    </div>
    </div>
    <aside className="mc-study-aside">
      <section className="panel mc-study-preview" aria-label={t("Preview")}>
        <h2>{t("Preview")}</h2>
        {optimizing ? <>
          <p className="mc-study-count"><b className="pc-num">{t("up to {n}", { n: budget })}</b> {t("simulations, one after the other")}
            {preview?.seconds_each != null && <small>{t("at most about {time}", { time: formatDuration(Math.max(1, preview.seconds_each * Number(budget))) })}</small>}</p>
          {built && built.variables.length > 0 && <ul className="mc-study-sweep">{built.variables.map((item) => <li key={item.name}>
            <span className="pc-mono">{item.name}</span><small>{t("from {start}, between {min} and {max}", { start: item.start, min: item.min, max: item.max })}</small>
          </li>)}</ul>}
          <p className="muted small">{t("Each simulation's values come from the results of those before: it stops when the best values change no more or at the most simulations.")}</p>
        </> : count ?? <p className="muted small">{t("Choose what varies to see how many simulations it makes.")}</p>}
        {built && built.sweep.length > 0 && <ul className="mc-study-sweep">{built.sweep.map((item) => <li key={item.name}>
          <span className={isSetting(item.name) ? undefined : "pc-mono"}>{sweptLabel(item.name)}</span>
          <small>{item.mode === "range" ? t("{count} values from {start} to {stop}", { count: item.count ?? 0, start: item.start ?? 0, stop: item.stop ?? 0 }) : t("{count} values", { count: item.values?.length ?? 0 })}</small>
        </li>)}</ul>}
        {!optimizing && preview && preview.count > preview.warn_above && !tooMany && <div className="notice">{t("{n} simulations is a large study: it can keep the queue busy for a while. Quick simulations still go first.", { n: preview.count })}</div>}
        {tooMany && preview && <div className="notice notice-error">{t("{n} simulations is more than this installation allows in one study ({limit}). Use fewer values; an administrator can raise the limit (MODELCRAFT_STUDY_MAX_RUNS).", { n: optimizing ? Number(budget) : preview.count, limit: preview.limit })}</div>}
      </section>
    </aside>
  </div>;
}
