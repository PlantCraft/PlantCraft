import { t } from "./i18n.js";
import { choosePeriod, TIME_WINDOWS, windowLabel, type TimePeriod } from "./timeChart.js";

export type PeriodPickerProps = {
  value: TimePeriod;
  onChange: (period: TimePeriod) => void;
  /** The relative windows offered; left out, `TIME_WINDOWS`. */
  windows?: readonly string[];
  /** Offer "From – to" (default on). */
  fixed?: boolean;
  className?: string;
};

/**
 * The period of a time chart, the same in every app: "Last 2 hours" … "Last 30 days" or
 * "From – to" with two dates. `periodRange(value)` gives the start and end to load.
 */
export function PeriodPicker({ value, onChange, windows = TIME_WINDOWS, fixed = true, className }: PeriodPickerProps) {
  return <div className={["pc-period", className].filter(Boolean).join(" ")}>
    <label>{t("Period")}<select value={value.window} onChange={(event) => onChange(choosePeriod(value, event.target.value))}>
      {windows.map((window) => <option key={window} value={window}>{t("Last {window}", { window: windowLabel(window) })}</option>)}
      {fixed && <option value="fixed">{t("From – to")}</option>}
    </select></label>
    {value.window === "fixed" && <>
      <label>{t("From")}<input type="datetime-local" value={value.from} onChange={(event) => onChange({ ...value, from: event.target.value })} /></label>
      <label>{t("To")}<input type="datetime-local" value={value.to} onChange={(event) => onChange({ ...value, to: event.target.value })} /></label>
    </>}
  </div>;
}
