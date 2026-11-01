/**
 * A model's compiled version (2026-11-01): Compile on its page builds the model as it is now into
 * an FMU (FMI 2.0, co-simulation: what Analytics runs) kept with the model, the last three of them.
 * The page says whether the model is compiled, from which version, and when it fell out of date.
 */
import { Pill } from "@plantcraft/ui";
import { Download } from "lucide-react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { runPath } from "./paths";
import { Link } from "./nav";
import type { Build, BuildState, ModelBuild } from "./types";

/** The words and the tone of each state. */
export const BUILD_WORDS: Record<BuildState, { label: string; tone: string; detail: string }> = {
  compiled: { label: "Compiled", tone: "good", detail: "Compiled from the model as it is now." },
  compiling: { label: "Compiling", tone: "running", detail: "In the queue or compiling now." },
  out_of_date: { label: "Out of date", tone: "attention", detail: "The model changed after it was compiled: compile it again." },
  failed: { label: "Compile failed", tone: "problem", detail: "The last compilation failed; its messages are below." },
  not_compiled: { label: "Not compiled", tone: "inactive", detail: "Compile it to keep a compiled version (an FMU) with the model." },
};

/** The states in the order a list sorts them. */
export const BUILD_ORDER: BuildState[] = ["compiled", "compiling", "out_of_date", "failed", "not_compiled"];

export function BuildPill({ state }: { state: BuildState }) {
  const words = BUILD_WORDS[state] ?? BUILD_WORDS.not_compiled;
  return <span title={t(words.detail)}><Pill status={words.tone} label={t(words.label)} /></span>;
}

/** "Compiled · version 4", as the page's heading and the list say it. */
export function buildText(build: ModelBuild): string {
  const words = t(BUILD_WORDS[build.state].label);
  const version = build.compiled?.version;
  return build.state === "compiled" && version ? `${words} · ${t("version {n}", { n: version })}` : words;
}

const size = (bytes: number | null) => (bytes === null ? "–" : bytes < 1024 * 1024 ? t("{n} kB", { n: Math.round(bytes / 1024) }) : t("{n} MB", { n: (bytes / 1024 / 1024).toFixed(1) }));

function Facts({ build }: { build: Build }) {
  return <dl className="mc-facts">
    <div><dt>{t("Version")}</dt><dd>{build.version ? t("Version {n}", { n: build.version }) : t("A version no longer kept")}{build.current ? ` · ${t("as it is now")}` : ""}</dd></div>
    <div><dt>{t("Compiled")}</dt><dd title={formatDate(build.finished_at ?? build.created_at)}>{formatAgo(build.finished_at ?? build.created_at)} · {build.created_by}</dd></div>
    <div><dt>{t("Took")}</dt><dd>{build.seconds === null ? "–" : formatDuration(build.seconds)}</dd></div>
    <div><dt>{t("FMU")}</dt><dd>{t("FMI {version} {type}", { version: build.fmi_version || "2.0", type: build.fmu_type || "cs" })} · {size(build.size)}{build.variables !== null ? ` · ${t("{n} variables", { n: build.variables })}` : ""}</dd></div>
    <div><dt>{t("Messages")}</dt><dd>{build.errors || build.warnings ? t("{errors} errors, {warnings} warnings", { errors: build.errors, warnings: build.warnings }) : t("None.")}</dd></div>
  </dl>;
}

/** The Overview's "Compiled version": the state, the compiled version and its FMU, and the
 * last compilations (each opens as a run, with its messages). */
export function BuildPanel({ build }: { build: ModelBuild | null }) {
  if (!build) return null;
  const failed = build.builds[0]?.status === "failed" ? build.builds[0] : null;
  return <section className="panel mc-model-build" aria-label={t("Compiled version")}>
    <div className="panel-header"><div><h2>{t("Compiled version")}</h2>
      <p><BuildPill state={build.state} /> <span className="muted small">{t(BUILD_WORDS[build.state].detail)}</span></p></div>
    </div>
    {failed && <ul className="mc-run-messages">{failed.messages.filter((item) => item.level === "error").slice(0, 5).map((item, index) => <li key={index}>{item.text}</li>)}
      {!failed.messages.some((item) => item.level === "error") && <li>{failed.summary || t("omc did not finish; see the messages.")}</li>}</ul>}
    {build.compiled && <>
      <Facts build={build.compiled} />
      <p className="mc-build-actions">
        <a className="button button-secondary button-small" href={api.fmuUrl(build.compiled.id)} download><Download size={14} />{t("Download the FMU")}</a>
        <span className="muted small">{t("Analytics runs this FMU: upload it there as a model.")}</span>
      </p>
    </>}
    {build.builds.length > 0 && <details className="mc-build-history">
      <summary>{t("Last compilations ({n})", { n: build.builds.length })}</summary>
      <ul>{build.builds.map((item) => <li key={item.id}>
        <Link to={runPath({ id: item.id })}>{formatAgo(item.created_at)}</Link> · {item.created_by} · {item.version ? t("version {n}", { n: item.version }) : t("an older version")} · {t(item.status === "done" ? "Done" : item.status === "failed" ? "Failed" : item.status === "cancelled" ? "Cancelled" : item.status === "running" ? "Running" : "Queued")}{item.seconds !== null ? ` · ${formatDuration(item.seconds)}` : ""}
      </li>)}</ul>
    </details>}
  </section>;
}
