/**
 * Starting a run: the simulation dialog (the experiment, parameter overrides and, optionally,
 * plant data from Historian as the model's inputs and as a comparison) and the FMU export dialog.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import type { ClassInfo, Diagram, Run, SignalOption } from "./types";
import { Dialog, message } from "./ui";
import { isoOf, localOf } from "@plantcraft/ui";

/** The integrators omc offers, with what each is for (OpenModelica User's Guide, simulation flags). */
export const SOLVERS: Array<{ id: string; label: string; detail: string }> = [
  { id: "dassl", label: "DASSL (default)", detail: "Variable step, variable order BDF. Stiff systems and most process models." },
  { id: "ida", label: "IDA", detail: "Variable step BDF from SUNDIALS, like DASSL; often faster on large systems." },
  { id: "cvode", label: "CVODE", detail: "Variable step from SUNDIALS (BDF or Adams). Smooth systems." },
  { id: "rungekutta", label: "Runge-Kutta (4th order)", detail: "Fixed step, explicit. Non-stiff systems; the step is the output interval." },
  { id: "heun", label: "Heun", detail: "Fixed step, explicit, 2nd order." },
  { id: "euler", label: "Explicit Euler", detail: "Fixed step, explicit, 1st order. Quick checks; small steps." },
  { id: "impeuler", label: "Implicit Euler", detail: "Fixed step, implicit, 1st order. Stiff systems at a fixed step." },
  { id: "trapezoid", label: "Trapezoid", detail: "Fixed step, implicit, 2nd order." },
];
const SOLVER_KEY = "modelcraft.solver.";

/** The integrator last used for a model in this browser, else DASSL. */
export function lastSolver(model: string): string {
  try { const saved = window.localStorage.getItem(SOLVER_KEY + model); return SOLVERS.some((item) => item.id === saved) ? saved as string : "dassl"; } catch { return "dassl"; }
}
function keepSolver(model: string, method: string) {
  try { window.localStorage.setItem(SOLVER_KEY + model, method); } catch { /* a private window */ }
}

function localInput(date: Date): string {
  return localOf(date.toISOString());
}

/** A signal from PlantCraft, searched by name as the person types. */
export function SignalPicker({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  const [options, setOptions] = useState<SignalOption[]>([]);
  const [error, setError] = useState("");
  const list = useMemo(() => `signals-${Math.random().toString(36).slice(2)}`, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.signals(value).then((found) => { setOptions(found); setError(""); }).catch((err) => setError(message(err)));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [value]);
  return <>
    <input list={list} value={value} placeholder={t("Signal")} aria-label={label} onChange={(event) => onChange(event.target.value)} />
    <datalist id={list}>{options.map((item) => <option key={item.id} value={item.id}>{[item.name, item.unit, item.description].filter(Boolean).join(" · ")}</option>)}</datalist>
    {error && <small className="danger">{error}</small>}
  </>;
}

export function SimulateDialog({ projectId, model, info, diagram: drawn, onClose, onStarted }: {
  projectId: string; model: string; info: ClassInfo | undefined; diagram: Diagram | null;
  onClose: () => void; onStarted: (run: Run) => void;
}) {
  const experiment = info?.experiment ?? {};
  const [start, setStart] = useState(String(experiment.StartTime ?? 0));
  const [stop, setStop] = useState(String(experiment.StopTime ?? 1));
  const interval = experiment.Interval ?? ((experiment.StopTime ?? 1) - (experiment.StartTime ?? 0)) / 500;
  const [intervals, setIntervals] = useState(String(Math.max(1, Math.round(((experiment.StopTime ?? 1) - (experiment.StartTime ?? 0)) / (interval || 1)))));
  const [tolerance, setTolerance] = useState(String(experiment.Tolerance ?? 1e-6));
  const [method, setMethod] = useState(() => lastSolver(model));
  const [label, setLabel] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [usePlant, setUsePlant] = useState(false);
  const now = new Date();
  const [plantStart, setPlantStart] = useState(localInput(new Date(now.getTime() - 3600_000)));
  const [plantEnd, setPlantEnd] = useState(localInput(now));
  const [plantStep, setPlantStep] = useState("10");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [compare, setCompare] = useState<Array<{ variable: string; signal: string }>>([{ variable: "", signal: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [diagram, setDiagram] = useState<Diagram | null>(drawn);
  // The parameters and inputs come from the class's instance: drawn here when the diagram was not.
  useEffect(() => { if (!drawn) api.diagram(projectId, model).then(setDiagram).catch(() => undefined); }, [drawn, projectId, model]);
  const parameters = diagram?.parameters.filter((item) => !item.name.includes(".")) ?? [];
  const modelInputs = diagram?.inputs ?? [];

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const values: Record<string, number | boolean> = {};
      for (const [name, text] of Object.entries(overrides)) {
        if (text.trim() === "") continue;
        if (text === "true" || text === "false") values[name] = text === "true";
        else if (Number.isFinite(Number(text))) values[name] = Number(text);
        else throw new Error(t("{name}: write a number, true or false.", { name }));
      }
      const settings: Record<string, unknown> = {
        model, start: Number(start), stop: Number(stop), intervals: Number(intervals), tolerance: Number(tolerance),
        method, overrides: values, label: label.trim(),
      };
      keepSolver(model, method);
      if (usePlant) {
        settings.plant = {
          start: isoOf(plantStart), end: isoOf(plantEnd),
          step: plantStep ? Number(plantStep) : null,
          inputs: Object.fromEntries(Object.entries(inputs).filter(([, signal]) => signal.trim())),
          compare: Object.fromEntries(compare.filter((row) => row.variable.trim() && row.signal.trim()).map((row) => [row.variable.trim(), row.signal.trim()])),
        };
      }
      onStarted(await api.simulate(projectId, settings));
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };

  return <Dialog title={t("Simulate {model}", { model: model.split(".").pop() ?? model })} onClose={onClose} wide
    footer={<>
      <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
      <button type="button" className="button button-primary" disabled={busy} onClick={() => void submit()}>{busy ? t("Starting…") : t("Simulate")}</button>
    </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <h3 className="mc-dialog-section">{t("Solver")}</h3>
    <div className="mc-solvers" role="radiogroup" aria-label={t("Solver")}>
      {SOLVERS.map((item) => <label key={item.id} className={`mc-solver${method === item.id ? " on" : ""}`}>
        <input type="radio" name="solver" value={item.id} checked={method === item.id} onChange={() => setMethod(item.id)} />
        <span><b>{t(item.label)}</b><small>{t(item.detail)}</small></span>
      </label>)}
    </div>
    <h3 className="mc-dialog-section">{t("Simulation settings")}</h3>
    <div className="form-grid">
      <label>{t("Start time")} <small>{t("seconds")}</small><input type="number" value={start} onChange={(event) => setStart(event.target.value)} disabled={usePlant} /></label>
      <label>{t("Stop time")} <small>{t("seconds")}</small><input type="number" value={stop} onChange={(event) => setStop(event.target.value)} disabled={usePlant} /></label>
      <label>{t("Intervals")}<input type="number" min={1} value={intervals} onChange={(event) => setIntervals(event.target.value)} /></label>
      <label>{t("Tolerance")}<input type="number" step="any" value={tolerance} onChange={(event) => setTolerance(event.target.value)} /></label>
      <label>{t("Label")} <small>{t("optional")}</small><input value={label} maxLength={120} onChange={(event) => setLabel(event.target.value)} placeholder={t("e.g. higher gain")} /></label>
    </div>
    {parameters.length > 0 && <>
      <h3 className="mc-dialog-section">{t("Parameters")} <small className="muted">{t("A value here is used for this simulation only; the model's text does not change.")}</small></h3>
      <div className="mc-params-table">
        <table className="table">
          <thead><tr><th>{t("Parameter")}</th><th>{t("In the model")}</th><th>{t("For this simulation")}</th></tr></thead>
          <tbody>{parameters.map((item) => <tr key={item.name}>
            <td><strong>{item.name}</strong><small>{item.comment}</small></td>
            <td className="pc-mono">{item.value ?? item.default ?? "–"}{item.unit ? ` ${item.unit}` : ""}</td>
            <td><input aria-label={item.name} value={overrides[item.name] ?? ""} onChange={(event) => setOverrides({ ...overrides, [item.name]: event.target.value })} /></td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
    <h3 className="mc-dialog-section">
      <label className="check"><input type="checkbox" checked={usePlant} onChange={(event) => setUsePlant(event.target.checked)} /> {t("Use plant data")}</label>
    </h3>
    {usePlant && <>
      <p className="muted small">{t("The simulation covers this period of the plant's history: each input of the model follows a signal (its last value held between samples), and outputs can be drawn next to the signals they should match.")}</p>
      <div className="form-grid">
        <label>{t("From")}<input type="datetime-local" value={plantStart} onChange={(event) => setPlantStart(event.target.value)} /></label>
        <label>{t("To")}<input type="datetime-local" value={plantEnd} onChange={(event) => setPlantEnd(event.target.value)} /></label>
        <label>{t("Sample step")} <small>{t("seconds")}</small><input type="number" min={1} value={plantStep} onChange={(event) => setPlantStep(event.target.value)} /></label>
      </div>
      <h4 className="mc-dialog-section">{t("Inputs from the plant")}</h4>
      {modelInputs.length === 0 ? <p className="muted small">{t("This model has no top-level input: nothing to feed. Add an input connector (Modelica.Blocks.Interfaces.RealInput) to drive it from a signal.")}</p>
        : <div className="form-grid">{modelInputs.map((name) => <label key={name}>{name}<SignalPicker label={name} value={inputs[name] ?? ""} onChange={(value) => setInputs({ ...inputs, [name]: value })} /></label>)}</div>}
      <h4 className="mc-dialog-section">{t("Compare with the plant")}</h4>
      {compare.map((row, index) => <div className="form-grid" key={index}>
        <label>{t("Model variable")}<input value={row.variable} placeholder={diagram?.outputs[0] ?? "tank.level"} onChange={(event) => setCompare(compare.map((item, i) => (i === index ? { ...item, variable: event.target.value } : item)))} /></label>
        <label>{t("Signal")}<SignalPicker label={t("Signal")} value={row.signal} onChange={(value) => setCompare(compare.map((item, i) => (i === index ? { ...item, signal: value } : item)))} /></label>
      </div>)}
      <button type="button" className="link-button" onClick={() => setCompare([...compare, { variable: "", signal: "" }])}>{t("Add a comparison")}</button>
    </>}
  </Dialog>;
}

export function FmuDialog({ projectId, model, onClose, onStarted }: { projectId: string; model: string; onClose: () => void; onStarted: (run: Run) => void }) {
  const [version, setVersion] = useState("2.0");
  const [type, setType] = useState("cs");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onStarted(await api.exportFmu(projectId, { model, version, type, label: label.trim() }));
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };
  return <Dialog title={t("Export {model} as an FMU", { model: model.split(".").pop() ?? model })} onClose={onClose}
    footer={<>
      <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
      <button type="button" className="button button-primary" disabled={busy} onClick={() => void submit()}>{busy ? t("Starting…") : t("Export")}</button>
    </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <p className="muted">{t("A Functional Mock-up Unit for Linux, with the CVODE solver inside for co-simulation, for any FMI tool. It downloads from the simulation's page.")}</p>
    <div className="form-grid">
      <label>{t("FMI version")}<select value={version} onChange={(event) => setVersion(event.target.value)}><option value="2.0">FMI 2.0</option><option value="3.0">FMI 3.0</option></select></label>
      <label>{t("Type")}<select value={type} onChange={(event) => setType(event.target.value)}>
        <option value="cs">{t("Co-simulation")}</option>
        <option value="me">{t("Model exchange")}</option>
        <option value="me_cs">{t("Both")}</option>
      </select></label>
      <label>{t("Label")} <small>{t("optional")}</small><input value={label} maxLength={120} onChange={(event) => setLabel(event.target.value)} /></label>
    </div>
  </Dialog>;
}
