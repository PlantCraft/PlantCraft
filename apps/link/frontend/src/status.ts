import { t } from "./i18n";
import type { StatusTone } from "@plantcraft/ui";

/** Loop status ids served by the API, their words and their colour family. */
export const STATUS: Record<string, { label: string; tone: StatusTone }> = {
  critical: { label: "Critical", tone: "problem" },
  high: { label: "High", tone: "serious" },
  medium: { label: "Medium", tone: "attention" },
  incomplete: { label: "Incomplete record", tone: "unusable" },
  normal: { label: "Normal", tone: "good" },
  inactive: { label: "Inactive", tone: "inactive" },
  no_data: { label: "Data not usable", tone: "unusable" },
  no_score: { label: "No score", tone: "info" },
  pending: { label: "Pending", tone: "info" },
};
export const STATUS_ORDER = ["critical", "high", "medium", "incomplete", "normal", "inactive", "no_data", "no_score", "pending"];

/** The suite's one status vocabulary (PlantCraft app standard, D5), as people read it. */
export const SUITE: Record<string, { label: string; tone: StatusTone }> = {
  ok: { label: "OK", tone: "good" },
  warning: { label: "Warning", tone: "attention" },
  alarm: { label: "Critical", tone: "problem" },
  unknown: { label: "Unknown", tone: "inactive" },
};

/** Method result status ids, worded as the suite words them (bad is the suite's alarm). */
export const RESULT: Record<string, { label: string; tone: StatusTone }> = {
  bad: SUITE.alarm,
  warning: SUITE.warning,
  ok: SUITE.ok,
  insufficient_data: { label: "Not enough data", tone: "inactive" },
  not_applicable: { label: "Not applicable", tone: "inactive" },
  unknown: SUITE.unknown,
};

export const statusLabel = (status: string) => t(STATUS[status]?.label ?? status);
export const statusTone = (status: string): StatusTone => STATUS[status]?.tone ?? "info";
export const suiteLabel = (status: string) => t(SUITE[status]?.label ?? SUITE.unknown.label);
export const resultLabel = (status: string) => t(RESULT[status]?.label ?? status);
export const resultTone = (status: string): StatusTone => RESULT[status]?.tone ?? "info";
