/** The ISA-101 analog indicator ("moving analog indicator"): a grey bar over the signal's range,
 * a darker band where the value should run (the normal range), ticks at the LL, L, H and HH
 * limits, a hollow mark at the setpoint and a pointer at the value. Everything is grey while the
 * value is normal; only the pointer takes the warning or alarm colour, so a screen of them shows
 * at a glance which few values need a look. Drawn by gauge cards ("Analog indicator") and by a
 * diagram's value elements ("indicator"). */
import { formatValue } from "./model";
import { sortedSteps, stepValues } from "./fields";
import type { FieldConfig, State } from "./types";

export interface AnalogLimits { ll?: number | null; l?: number | null; h?: number | null; hh?: number | null }
export interface AnalogSpec {
  value: number | null; min: number; max: number; limits: AnalogLimits;
  normal?: { low?: number | null; high?: number | null } | null; sp?: number | null; state: State;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** LL, L, H and HH from a card's threshold steps: L where the normal step starts and H where the
 * step after it starts; LL and HH the steps on either side of those. No normal step: none. */
export function limitsFromSteps(config: FieldConfig, range?: { low?: number | null; high?: number | null }): AnalogLimits {
  const steps = config.thresholds?.steps?.length ? sortedSteps(config.thresholds.steps) : [];
  if (!steps.length) return {};
  // Colour-only steps (level "none") are no limits.
  const values = stepValues(config, range).filter((item) => item.step.level === "ok" || item.step.level === "warning" || item.step.level === "alarm");
  const okAt = values.findIndex((item) => item.step.level === "ok");
  if (okAt < 0) {
    // The base step is the normal one: every threshold is above it (H, then HH).
    if (steps[0].level !== "ok") return {};
    return { h: values[0]?.value ?? null, hh: values[1]?.value ?? null };
  }
  return {
    ll: values[okAt - 1]?.value ?? null,
    l: values[okAt].value,
    h: values[okAt + 1]?.value ?? null,
    hh: values[okAt + 2]?.value ?? null,
  };
}

/** The normal range: the field's own, else between L and H. */
export function normalRange(config: FieldConfig, limits: AnalogLimits): { low: number | null; high: number | null } | null {
  const low = finite(config.normal_low) ? config.normal_low : finite(limits.l) ? limits.l : null;
  const high = finite(config.normal_high) ? config.normal_high : finite(limits.h) ? limits.h : null;
  return low === null && high === null ? null : { low, high };
}

/** Where each part sits along the bar, 0 to 1 (outside the range: clamped, and said so). */
export function analogLayout(spec: AnalogSpec) {
  const span = spec.max - spec.min || 1;
  const at = (x: number) => Math.max(0, Math.min(1, (x - spec.min) / span));
  const ticks = (["ll", "l", "h", "hh"] as const).flatMap((name) => finite(spec.limits[name]) ? [{ name, at: at(spec.limits[name] as number), value: spec.limits[name] as number }] : []);
  const low = spec.normal && finite(spec.normal.low) ? spec.normal.low : spec.normal && finite(spec.normal.high) ? spec.min : null;
  const high = spec.normal && finite(spec.normal.high) ? spec.normal.high : spec.normal && finite(spec.normal.low) ? spec.max : null;
  const band = low !== null && high !== null && high > low ? { from: at(low), to: at(high) } : null;
  const pointer = finite(spec.value) ? { at: at(spec.value), over: spec.value > spec.max, under: spec.value < spec.min } : null;
  const sp = finite(spec.sp) ? at(spec.sp) : null;
  return { ticks, band, pointer, sp };
}

const LABELS = { ll: "LL", l: "L", h: "H", hh: "HH" } as const;

/** The indicator as an SVG group of `width` × `height` at (x, y); horizontal. */
export function AnalogBar({ spec, x = 0, y = 0, width, height = 30, labels = true, decimals }: {
  spec: AnalogSpec; x?: number; y?: number; width: number; height?: number; labels?: boolean; decimals?: number | null;
}) {
  const layout = analogLayout(spec);
  const barTop = y + height * 0.36;
  const barHeight = height * 0.28;
  const px = (share: number) => x + share * width;
  const tone = spec.state === "alarm" || spec.state === "warning" ? spec.state : spec.state === "unknown" ? "unknown" : "normal";
  const size = Math.max(4, height * 0.2);
  return <g className="isa-analog" data-state={tone}>
    <rect className="isa-analog-track" x={x} y={barTop} width={width} height={barHeight} />
    {layout.band && <rect className="isa-analog-normal" x={px(layout.band.from)} y={barTop} width={Math.max(1, (layout.band.to - layout.band.from) * width)} height={barHeight} />}
    {layout.ticks.map((tick) => <g key={tick.name} className={`isa-analog-limit isa-analog-${tick.name}`}>
      <line x1={px(tick.at)} x2={px(tick.at)} y1={barTop - (tick.name.length > 1 ? size * 0.8 : size * 0.4)} y2={barTop + barHeight + (tick.name.length > 1 ? size * 0.8 : size * 0.4)} />
      {labels && <text x={px(tick.at)} y={y + height} textAnchor="middle"><title>{`${LABELS[tick.name]} ${formatValue(tick.value, decimals ?? undefined)}`}</title>{LABELS[tick.name]}</text>}
    </g>)}
    {layout.sp !== null && <path className="isa-analog-sp" d={`M ${px(layout.sp)} ${barTop + barHeight} l ${size * 0.7} ${size} h ${-size * 1.4} Z`}><title>{`SP ${formatValue(spec.sp ?? null, decimals ?? undefined)}`}</title></path>}
    {layout.pointer && <path className="isa-analog-pointer" d={`M ${px(layout.pointer.at)} ${barTop} l ${size * 0.8} ${-size * 1.2} h ${-size * 1.6} Z`} />}
    {layout.pointer?.over && <path className="isa-analog-pointer" d={`M ${x + width + 2} ${barTop + barHeight / 2} l ${-size} ${-size * 0.7} v ${size * 1.4} Z`} transform={`translate(${size} 0)`} />}
    {layout.pointer?.under && <path className="isa-analog-pointer" d={`M ${x - 2} ${barTop + barHeight / 2} l ${size} ${-size * 0.7} v ${size * 1.4} Z`} transform={`translate(${-size} 0)`} />}
  </g>;
}
