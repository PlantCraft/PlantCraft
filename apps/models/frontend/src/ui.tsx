/** The suite's building blocks (@plantcraft/ui), and this app's own. */
import { ErrorBox, Heading, Health, Loading, Pill, errorMessage, saveFile, formatReading } from "@plantcraft/ui";
import type { ReactNode } from "react";
import { useEffect } from "react";
import { href } from "./nav";
import { t } from "./i18n";
import type { Message, Run } from "./types";

export { ErrorBox, Health, Heading, Loading, Pill };
export { Link } from "./nav";

export const RUN_WORDS: Record<string, string> = { queued: "Queued", running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled" };
export const STUDY_WORDS: Record<string, string> = { quick: "Quick simulations", single: "One simulation", sweep: "Parameter sweep", optimization: "Optimization" };
export const KIND_WORDS: Record<string, string> = { simulate: "Simulation", fmu: "FMU export" };
export const LEVEL_WORDS: Record<string, string> = { error: "Error", warning: "Warning", info: "Note" };
export const RESTRICTION_LETTER: Record<string, string> = {
  package: "P", model: "M", block: "B", connector: "C", "expandable connector": "C", record: "R",
  type: "T", function: "F", "pure function": "F", "impure function": "F", class: "K", operator: "O",
  "operator record": "R", "operator function": "F",
};

export function RunPill({ run }: { run: Pick<Run, "status"> }) {
  return <Pill status={`run-${run.status}`} label={t(RUN_WORDS[run.status] ?? run.status)} />;
}

/** A bar for how far something is, 0 to 1, with its text beside it. */
export function Progress({ value, text, tone = "info", label }: { value: number; text?: ReactNode; tone?: "info" | "good" | "problem"; label?: string }) {
  const share = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return <span className={`mc-progress mc-progress-${tone}`}>
    <span className="mc-progress-track" role="progressbar" aria-label={label ?? (typeof text === "string" ? text : t("Progress"))} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}><span style={{ width: `${share * 100}%` }} /></span>
    {text !== undefined && <small>{text}</small>}
  </span>;
}

/** A study's simulations as one bar: finished (done, failed, cancelled) of the total. */
export function StudyProgress({ study }: { study: { queued: number; running: number; done: number; failed: number; cancelled: number; total: number } }) {
  const finished = study.done + study.failed + study.cancelled;
  const text = study.total === 0 ? t("No simulation") : study.queued || study.running
    ? t("{done} of {total} · {running} running", { done: finished, total: study.total, running: study.running })
    : study.failed ? t("{done} done · {failed} failed", { done: study.done, failed: study.failed }) : t("{done} done", { done: study.done });
  return <Progress value={study.total ? finished / study.total : 0} text={text} label={t("Simulations finished")} tone={study.failed ? "problem" : study.queued || study.running ? "info" : "good"} />;
}

/** A sweep variant as a person reads it: "k=2, Ti=30". */
export function variantText(variant: Record<string, number | boolean | string> | undefined): string {
  return Object.entries(variant ?? {}).map(([name, value]) => `${name.replace(/^@/, "").split(".").pop()}=${typeof value === "number" ? Number(value.toPrecision(6)) : value}`).join(", ");
}

export function LevelPill({ level }: { level: Message["level"] }) {
  return <Pill status={`level-${level}`} label={t(LEVEL_WORDS[level] ?? level)} />;
}

/** The kind of a Modelica class as one letter in a badge, the way Modelica tools show it. */
export function ClassBadge({ restriction, partial }: { restriction: string; partial?: boolean }) {
  return <span className={`mc-badge mc-badge-${(restriction.split(" ").pop() ?? "class")}${partial ? " mc-badge-partial" : ""}`} title={partial ? t("partial {kind}", { kind: restriction }) : restriction}>
    {RESTRICTION_LETTER[restriction] ?? "?"}
  </span>;
}

/** An error as the line a person reads. */
export const message = errorMessage;

/** A number as an engineer reads it: 4 significant digits, the unit after (ui). */
export const reading = formatReading;

/** The suite's dialog (ui): Escape, the × and a click outside close it; focus stays inside. */
export { Dialog } from "@plantcraft/ui";

/** Download a text as a file, without a round trip to the server. */
export const download = (name: string, text: string, type = "text/plain") => saveFile(name, text, type);

/** Send the browser to another page of the app, in place of this address (no history entry). */
export function Redirect({ to }: { to: string }) {
  useEffect(() => {
    window.history.replaceState({}, "", href(to));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [to]);
  return <Loading />;
}
