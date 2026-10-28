/**
 * A diagram model's simulation settings (start, stop, step, tolerance, solver) and what the page
 * reads from its diagram: the inputs nobody wired, the signals its scopes show, the parameters a
 * study can vary.
 */
import type { BlockCatalog, DiagramCheck } from "@plantcraft/ui/blockEditor";
import { t } from "./i18n";
import type { BlockDiagram, SimSettings } from "./types";

/** The solvers OpenModelica offers a diagram model: variable step first (OpenModelica User's
 * Guide, simulation flags). A fixed-step solver integrates at the step; a variable-step one
 * chooses its own steps within the tolerance and writes the results at the step. */
export const SOLVERS: Array<{ id: string; name: string; fixed: boolean; detail: string }> = [
  { id: "dassl", name: "DASSL", fixed: false, detail: "Variable step and order (BDF). Stiff systems and most process models." },
  { id: "ida", name: "IDA", fixed: false, detail: "Variable step BDF from SUNDIALS; often faster on large systems." },
  { id: "cvode", name: "CVODE", fixed: false, detail: "Variable step from SUNDIALS. Smooth systems." },
  { id: "euler", name: "Euler", fixed: true, detail: "Explicit, 1st order. Quick checks with a small step." },
  { id: "heun", name: "Heun", fixed: true, detail: "Explicit, 2nd order." },
  { id: "rungekutta", name: "Runge-Kutta", fixed: true, detail: "Explicit, 4th order. Non-stiff systems." },
  { id: "trapezoid", name: "Trapezoid", fixed: true, detail: "Implicit, 2nd order." },
  { id: "impeuler", name: "Implicit Euler", fixed: true, detail: "Implicit, 1st order. Stiff systems at a fixed step." },
];
export const SOLVER_NAMES: Record<string, string> = Object.fromEntries(SOLVERS.map((item) => [item.id, item.name]));
export const MAX_STEPS = 200_000;

/** What is wrong with the settings, in words, or "" when they can run. */
export function settingsProblem(settings: SimSettings): string {
  const { start, stop, interval, tolerance } = settings;
  if (![start, stop, interval, tolerance].every(Number.isFinite)) return t("Start, stop, step and tolerance are numbers.");
  if (stop <= start) return t("The stop time must come after the start time.");
  if (interval <= 0) return t("The step must be greater than zero.");
  if ((stop - start) / interval > MAX_STEPS) return t("Up to {n} steps: make the step larger or the time shorter.", { n: MAX_STEPS.toLocaleString("en") });
  if (tolerance < 1e-14 || tolerance > 0.1) return t("The tolerance is between 1e-14 and 0.1.");
  return "";
}

/** The diagram's check, as the editor shows it: each input without a wire, and what the server
 * said the diagram cannot hold. */
export function checkDiagram(diagram: BlockDiagram, catalog: BlockCatalog, problems: string[] = []): DiagramCheck {
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  const fed = new Set(diagram.edges.map((edge) => `${edge.target}.${edge.target_port}`));
  const nodeErrors: Record<string, string[]> = {};
  for (const node of diagram.nodes) {
    const spec = specs[node.block];
    if (!spec) { nodeErrors[node.id] = [t("{block} is not a block of the libraries.", { block: node.block })]; continue; }
    const loose = spec.inputs.filter((port) => !fed.has(`${node.id}.${port.port}`));
    if (loose.length) nodeErrors[node.id] = loose.map((port) => t("{input} is not connected.", { input: port.label || port.port }));
  }
  const errors = [...problems];
  if (Object.keys(nodeErrors).length) errors.push(t("Every input needs a wire before the model runs."));
  return { valid: !errors.length, errors, warnings: [], node_errors: nodeErrors };
}

/** The signals the diagram's scopes show, as result variables (`tank.level`), in order. */
export function scopeSignals(diagram: BlockDiagram, catalog: BlockCatalog): string[] {
  const sinks = new Set(catalog.blocks.filter((block) => block.outputs.length === 0).map((block) => block.block_id));
  const scopes = new Set(diagram.nodes.filter((node) => sinks.has(node.block)).map((node) => node.id));
  const found: string[] = [];
  for (const edge of diagram.edges) {
    const name = `${edge.source}.${edge.source_port}`;
    if (scopes.has(edge.target) && !found.includes(name)) found.push(name);
  }
  return found;
}

/** The parameters a study can vary: every numeric parameter of every block (`tank.A`). */
export function diagramParameters(diagram: BlockDiagram, catalog: BlockCatalog): Array<{ path: string; comment: string; value: string; unit: string }> {
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  return diagram.nodes.flatMap((node) => (specs[node.block]?.parameters ?? [])
    .filter((item) => ["number", "integer", "boolean"].includes(String(item.schema.type)))
    .map((item) => ({
      path: `${node.id}.${item.name}`,
      comment: [node.label || specs[node.block].name, item.description].filter(Boolean).join(": "),
      value: String(node.parameters?.[item.name] ?? item.default ?? "–"),
      unit: item.unit,
    })));
}

function NumberField({ label, unit, value, onChange, disabled }: { label: string; unit?: string; value: number; onChange: (value: number) => void; disabled?: boolean }) {
  return <label><span>{label}{unit && <small> ({unit})</small>}</span>
    <input type="number" step="any" value={Number.isFinite(value) ? value : ""} disabled={disabled} onChange={(event) => onChange(event.target.value === "" ? Number.NaN : Number(event.target.value))} />
  </label>;
}

/** The settings panel beside the diagram. */
export function SimulationSettings({ settings, onChange, readOnly }: { settings: SimSettings; onChange: (settings: SimSettings) => void; readOnly?: boolean }) {
  const set = (change: Partial<SimSettings>) => onChange({ ...settings, ...change });
  const solver = SOLVERS.find((item) => item.id === settings.solver) ?? SOLVERS[0];
  const problem = settingsProblem(settings);
  const steps = Math.round((settings.stop - settings.start) / settings.interval);
  return <section className="mc-sim-settings" aria-label={t("Simulation settings")}>
    <h3>{t("Simulation settings")}</h3>
    <div className="mc-sim-grid">
      <NumberField label={t("Start")} unit="s" value={settings.start} disabled={readOnly} onChange={(start) => set({ start })} />
      <NumberField label={t("Stop")} unit="s" value={settings.stop} disabled={readOnly} onChange={(stop) => set({ stop })} />
      <label className="mc-sim-wide">{t("Solver")}
        <select value={settings.solver} disabled={readOnly} onChange={(event) => set({ solver: event.target.value })}>
          <optgroup label={t("Variable step")}>{SOLVERS.filter((item) => !item.fixed).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup>
          <optgroup label={t("Fixed step")}>{SOLVERS.filter((item) => item.fixed).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup>
        </select>
        <small>{t(solver.detail)}</small>
      </label>
      <NumberField label={solver.fixed ? t("Step") : t("Output step")} unit="s" value={settings.interval} disabled={readOnly} onChange={(interval) => set({ interval })} />
      <NumberField label={t("Tolerance")} value={settings.tolerance} disabled={readOnly || solver.fixed} onChange={(tolerance) => set({ tolerance })} />
    </div>
    {problem ? <p className="danger small">{problem}</p> : <p className="muted small">{t("{n} steps of {step} s.", { n: steps.toLocaleString("en"), step: settings.interval })}</p>}
  </section>;
}
