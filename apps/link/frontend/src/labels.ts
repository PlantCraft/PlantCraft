import { t } from "./i18n";

/** Method names shared by every page (English; translated where read). */

const METHOD_NAMES: Record<string, string> = {
  error_metrics_basic: "PV–SP error",
  pv_variability: "PV variability",
  op_saturation_fraction: "Output saturation",
  op_travel_reversal: "Valve travel",
  oscillation_autocorrelation: "Oscillation",
  sensor_noise_ratio: "Sensor noise",
  stiction_screening: "Stiction screening",
  manual_mode_fraction: "Manual mode",
  setpoint_activity: "SP activity",
  operational_interventions: "Operator interventions",
  disturbance_attenuation: "Disturbance attenuation",
  operating_band_fraction: "Time in operating band",
  sampling_quality: "Sampling quality",
  interaction_cross_correlation: "Loop interaction",
  dq_availability: "Signal availability",
  dq_value_integrity: "Value integrity",
  dq_statistics: "Descriptive statistics",
  sq_availability: "Availability and gaps",
  sq_freshness: "Freshness",
  sq_frozen: "Frozen value",
  sq_spikes: "Spikes",
  sq_range: "Out of range",
  sq_noise: "Noise",
  sq_resolution: "Resolution and compression",
  sq_drift: "Drift",
};

export function methodLabel(value: string) {
  const name = METHOD_NAMES[value];
  return name ? t(name) : value.replaceAll("_", " ");
}

/** Performance on one scale, 100 = good, for any method result. */
export function performanceOf(result: { score?: unknown; metrics?: Record<string, unknown> }) {
  const component = result.metrics?.performance_component;
  if (typeof component === "number") return component;
  const score = Number(result.score);
  return Number.isFinite(score) ? Math.max(0, 100 - score) : null;
}

export function formatPercent(value?: number | null) {
  return value === undefined || value === null ? "—" : `${Math.round(value)}%`;
}
