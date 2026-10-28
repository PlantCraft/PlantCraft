/** The suite's building blocks (@plantcraft/ui), and this app's own. */
import { ErrorBox, errorMessage, Heading, Health, Loading, Pill, formatReading } from "@plantcraft/ui";
import { t } from "./i18n";

export { ErrorBox, Health, Heading, Loading, Pill };
export { Link } from "./nav";

export const STATUS_WORDS: Record<string, string> = {
  unacked: "Unacknowledged", rtn_unacked: "Returned, unacknowledged", acked: "Acknowledged",
  shelved: "Shelved", out_of_service: "Out of service", normal: "Normal",
};
export const PRIORITY_WORDS: Record<string, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
export const ACTION_WORDS: Record<string, string> = {
  raised: "Raised", cleared: "Cleared", acknowledged: "Acknowledged", shelved: "Shelved", unshelved: "Unshelved",
  created: "Created", changed: "Changed", deleted: "Deleted", out_of_service: "Out of service", in_service: "In service",
};

/** An alarm's ISA-18.2 state in its suite colour. */
export function StatusPill({ status }: { status: string }) {
  return <Pill status={`alarm-${status}`} label={t(STATUS_WORDS[status] ?? status)} />;
}

export function PriorityPill({ priority }: { priority: string }) {
  return <Pill status={`priority-${priority}`} label={t(PRIORITY_WORDS[priority] ?? priority)} />;
}

/** An error as the line a person reads. */
export const message = errorMessage;

/** A number as an engineer reads it: 4 significant digits, the unit after (ui). */
export const reading = formatReading;

export const WINDOWS = ["24h", "7d", "30d"];

export function WindowPicker({ value, onChange, options = WINDOWS }: { value: string; onChange: (value: string) => void; options?: string[] }) {
  return <div className="pc-segmented" role="group" aria-label={t("Period")}>
    {options.map((item) => <button key={item} type="button" className={item === value ? "on" : ""} onClick={() => onChange(item)}>{item}</button>)}
  </div>;
}

export const DISCIPLINE_WORDS: Record<string, string> = {
  operations: "Operations", process: "Process", instrumentation: "Instrumentation", electrical: "Electrical",
  mechanical: "Mechanical", safety: "Safety and environment",
};
