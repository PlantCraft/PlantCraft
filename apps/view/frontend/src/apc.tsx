/** The multivariable controller panel (V10): a third-party APC's manipulated (MV) and
 * controlled (CV) variables, read only. Each row draws the variable's range from lo to hi, its
 * value (a pointer) and its steady-state target (a hollow mark), as the ISA-101 analog indicator
 * does, and its value and target over the panel's window (the horizon). A variable at a limit
 * (its target, else its value, within its band of lo or hi) is marked: that is where the
 * controller is constrained. View never writes to the controller. */
import { formatDate, t } from "./i18n";
import { formatValue } from "./model";
import type { ApcData, ApcVariable } from "./types";

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** The scale of a variable's bar: lo to hi with a margin of a tenth either side, widened to
 * show a value or target outside them; null without both limits. */
export function apcScale(variable: Pick<ApcVariable, "lo" | "hi" | "value" | "target">): { min: number; max: number } | null {
  if (!finite(variable.lo) || !finite(variable.hi) || variable.hi <= variable.lo) return null;
  const pad = (variable.hi - variable.lo) / 10;
  const points = [variable.lo - pad, variable.hi + pad, ...[variable.value, variable.target].filter(finite)];
  return { min: Math.min(...points), max: Math.max(...points) };
}

/** An SVG path of a line over `width` × `height`, scaled to `min`..`max` (gaps break it). */
export function sparkPath(values: Array<number | null>, width: number, height: number, min: number, max: number): string {
  if (!values.length || max <= min) return "";
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  let path = "";
  let pen = false;
  values.forEach((value, index) => {
    if (!finite(value)) { pen = false; return; }
    const x = (index * step).toFixed(1);
    const y = (height - ((value - min) / (max - min)) * height).toFixed(1);
    path += `${pen ? "L" : "M"}${x} ${y}`;
    pen = true;
  });
  return path;
}

/** "At high limit", "At low limit", "Out of service" or "": what a row's state says. */
export function apcState(variable: Pick<ApcVariable, "at_limit" | "in_service">): string {
  if (variable.in_service === false) return t("Out of service");
  if (variable.at_limit === "hi") return t("At high limit");
  if (variable.at_limit === "lo") return t("At low limit");
  return "";
}

const BAR_W = 140;
const BAR_H = 22;

function RangeBar({ variable }: { variable: ApcVariable }) {
  const scale = apcScale(variable);
  if (!scale) return <span className="muted">{t("No limits")}</span>;
  const x = (value: number) => ((value - scale.min) / (scale.max - scale.min)) * BAR_W;
  const lo = x(variable.lo as number);
  const hi = x(variable.hi as number);
  return <svg className="apc-bar" viewBox={`0 0 ${BAR_W} ${BAR_H}`} width={BAR_W} height={BAR_H} role="img"
    aria-label={t("{lo} to {hi}, value {value}, target {target}", { lo: formatValue(variable.lo), hi: formatValue(variable.hi), value: formatValue(variable.value), target: formatValue(variable.target) })}>
    <rect className="apc-bar-track" x={0} y={8} width={BAR_W} height={6} rx={1} />
    <rect className="apc-bar-range" x={lo} y={8} width={Math.max(0, hi - lo)} height={6} />
    <line className={`apc-bar-limit${variable.at_limit === "lo" ? " on" : ""}`} x1={lo} x2={lo} y1={4} y2={18} />
    <line className={`apc-bar-limit${variable.at_limit === "hi" ? " on" : ""}`} x1={hi} x2={hi} y1={4} y2={18} />
    {finite(variable.target) && <path className="apc-bar-target" d={`M${x(variable.target)} 5l4 6-4 6-4-6z`} />}
    {finite(variable.value) && <path className="apc-bar-value" d={`M${x(variable.value)} 15l4 6h-8z`} />}
  </svg>;
}

const SPARK_W = 120;
const SPARK_H = 22;

function Horizon({ variable }: { variable: ApcVariable }) {
  const all = [...variable.value_line, ...variable.target_line, variable.lo, variable.hi].filter(finite);
  if (!variable.value_line.some(finite)) return <span className="muted">—</span>;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max > min ? max - min : 1;
  const scale = (value: number | null) => (finite(value) ? SPARK_H - ((value - min) / span) * SPARK_H : 0);
  const first = variable.t[0];
  const last = variable.t[variable.t.length - 1];
  return <svg className="apc-spark" viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} width={SPARK_W} height={SPARK_H} role="img"
    aria-label={first && last ? t("Value and target from {start} to {end}", { start: formatDate(first), end: formatDate(last) }) : t("Value and target")}>
    {finite(variable.hi) && <line className="apc-spark-limit" x1={0} x2={SPARK_W} y1={scale(variable.hi)} y2={scale(variable.hi)} />}
    {finite(variable.lo) && <line className="apc-spark-limit" x1={0} x2={SPARK_W} y1={scale(variable.lo)} y2={scale(variable.lo)} />}
    <path className="apc-spark-target" d={sparkPath(variable.target_line, SPARK_W, SPARK_H, min, min + span)} />
    <path className="apc-spark-value" d={sparkPath(variable.value_line, SPARK_W, SPARK_H, min, min + span)} />
  </svg>;
}

export function ApcPanel({ data }: { data?: ApcData }) {
  if (!data) return null;
  if (data.error || !data.controller) return <div className="tc-card-error">{data.error ?? t("The controller cannot be read.")}</div>;
  const { controller, counts } = data;
  const variables = data.variables ?? [];
  const priced = variables.some((variable) => finite(variable.shadow_price));
  const on = controller.on === null ? t("State unknown") : controller.on ? t("On") : t("Off");
  return <div className="apc">
    <p className="apc-head">
      <span className="apc-on" data-on={controller.on === null ? "unknown" : String(controller.on)}>{on}</span>
      {controller.mode !== null && controller.mode !== "" && <span>{t("Mode {mode}", { mode: String(controller.mode) })}</span>}
      {counts && <span>{t("{mv} MV · {cv} CV · {service} in service · {limits} at a limit", { mv: counts.mv, cv: counts.cv, service: counts.in_service, limits: counts.at_limits })}</span>}
      {controller.vendor && <span className="muted">{controller.vendor}</span>}
    </p>
    {!variables.length ? <p className="muted">{t("No MV or CV under this controller: add assets of kind apc_mv and apc_cv under it.")}</p>
      : <div className="apc-scroll"><table className="apc-table">
        <thead><tr>
          <th>{t("Variable")}</th><th>{t("Range")}</th>
          <th className="num">{t("Value")}</th><th className="num">{t("Target")}</th>
          <th className="num">{t("Low")}</th><th className="num">{t("High")}</th>
          {priced && <th className="num" title={t("Cost of the constraint per unit, as the controller exports it")}>{controller.cost_unit ? t("Shadow price ({unit})", { unit: controller.cost_unit }) : t("Shadow price")}</th>}
          <th>{t("Horizon")}</th><th>{t("State")}</th>
        </tr></thead>
        <tbody>{variables.map((variable) => {
          const state = apcState(variable);
          return <tr key={variable.id} data-limit={variable.at_limit ?? undefined} data-service={variable.in_service === false ? "out" : undefined}>
            <th scope="row" title={variable.description || undefined}><span className="apc-type">{variable.type.toUpperCase()}</span> {variable.name}</th>
            <td><RangeBar variable={variable} /></td>
            <td className="num">{formatValue(variable.value)}{variable.unit && <small> {variable.unit}</small>}</td>
            <td className="num">{formatValue(variable.target)}</td>
            <td className="num">{formatValue(variable.lo)}</td>
            <td className="num">{formatValue(variable.hi)}</td>
            {priced && <td className="num">{formatValue(variable.shadow_price)}</td>}
            <td><Horizon variable={variable} /></td>
            <td className="apc-state">{state}</td>
          </tr>;
        })}</tbody>
      </table></div>}
  </div>;
}
