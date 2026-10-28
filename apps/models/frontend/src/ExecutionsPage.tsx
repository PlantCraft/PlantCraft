/**
 * Executions, in Link's shape (owner, 2026-10-25, round 8 M3): the study takes the schedule's
 * place and the simulation the asset's. `/executions` opens on the studies, each with what it
 * runs and how its simulations ended (a model's single runs, what Run on its page starts, are a
 * group of their own); `/executions/<id>` is one group: a summary, then its simulations, each
 * opening its run. `/executions/queue` is the live queue: the suite's queue panel, what runs
 * and waits now, and every run, FMU exports included.
 */
import { DataTable, PageTabs, QueuePanel, type DataColumn } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, t } from "./i18n";
import { href, navigate } from "./nav";
import { modelPath } from "./paths";
import { QueueLists, RunsTable } from "./RunsPage";
import { SimulationsTable } from "./StudiesPage";
import type { Me, QueueState, Run, Study, SweepItem } from "./types";
import { ErrorBox, Heading, Link, Loading, message, StudyProgress } from "./ui";

const POLL_MS = 3000;

/** A group's name: a study's own, or "Single simulations of <model>". */
export function groupName(study: Pick<Study, "kind" | "name" | "model">): string {
  return study.kind === "quick" ? t("Single simulations of {model}", { model: study.model.split(".").pop() ?? study.model }) : study.name;
}

export const GROUP_KINDS: Record<string, string> = { quick: "Single simulations", single: "Study", sweep: "Study", optimization: "Study" };

export const groupPath = (study: Pick<Study, "id">) => `/executions/${encodeURIComponent(study.id)}`;

export const EXECUTIONS_TABS = (active: "studies" | "queue") => <PageTabs label={t("Simulations")} href={href} navigate={navigate} tabs={[
  { to: "/executions", label: t("By study"), active: active === "studies" },
  { to: "/executions/queue", label: t("Queue"), active: active === "queue" },
]} />;

/** "12 done · 1 failed · 2 waiting": how a group's simulations ended, in one line. */
export function countsText(study: Pick<Study, "done" | "failed" | "cancelled" | "queued" | "running">): string {
  const parts = [
    study.done ? t("{n} done", { n: study.done }) : "",
    study.failed ? t("{n} failed", { n: study.failed }) : "",
    study.cancelled ? t("{n} cancelled", { n: study.cancelled }) : "",
    study.running ? t("{n} running", { n: study.running }) : "",
    study.queued ? t("{n} waiting", { n: study.queued }) : "",
  ].filter(Boolean);
  return parts.join(" · ") || t("Nothing ran yet");
}

/** What a study varies, as people say it: "tank.A 5 values from 2 to 6 × tank.Cv 3 values". */
export function variesText(study: Pick<Study, "kind" | "spec">): string {
  if (study.kind === "quick") return t("Run on the model's page");
  const optimization = study.spec && "optimization" in study.spec ? study.spec.optimization : undefined;
  if (optimization) return t("Optimization of {names}", { names: optimization.variables.map((item) => item.name).join(", ") });
  const sweep: SweepItem[] = study.spec && "sweep" in study.spec ? study.spec.sweep : [];
  if (!sweep.length) return t("The model as it is");
  return sweep.map((item) => `${item.name} ${item.mode === "range"
    ? t("{count} values from {start} to {stop}", { count: item.count ?? 0, start: item.start ?? 0, stop: item.stop ?? 0 })
    : t("{count} values", { count: item.values?.length ?? 0 })}`).join(" × ");
}

function usePolled<T>(load: () => Promise<T>, key: string): [T | null, string, () => void] {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const read = useCallback(() => { load().then((answer) => { setValue(answer); setError(""); }).catch((err) => setError(message(err))); }, [key]);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, POLL_MS);
    return () => window.clearInterval(timer);
  }, [read]);
  return [value, error, read];
}

export function ExecutionsPage(_props: { me: Me }) {
  const [studies, error] = usePolled(() => api.studies().then((found) => found.filter((item) => item.total > 0)), "studies");
  const columns: DataColumn<Study>[] = [
    { key: "name", label: t("Study"), sort: (study) => groupName(study).toLowerCase(), render: (study) => <><Link to={groupPath(study)}><b>{groupName(study)}</b></Link><small>{variesText(study)}</small></> },
    { key: "model", label: t("Model"), sort: (study) => study.model, render: (study) => <><span>{study.model.split(".").pop()}</span><small>{study.project_name}</small></> },
    { key: "kind", label: t("Type"), className: "hide-narrow", sort: (study) => study.kind, render: (study) => t(GROUP_KINDS[study.kind] ?? study.kind),
      filter: { value: (study) => (study.kind === "quick" ? "quick" : "study"), options: [{ value: "study", label: t("Study") }, { value: "quick", label: t("Single simulations") }] } },
    { key: "simulations", label: t("Simulations"), numeric: true, sort: (study) => study.total, render: (study) => <span className="pc-num">{study.total}</span> },
    { key: "last", label: t("Last simulation"), sort: (study) => study.last_run_at ?? study.created_at, render: (study) => <>{formatAgo(study.last_run_at ?? study.created_at)}<small>{countsText(study)}</small></> },
  ];
  return <>
    <Heading eyebrow={t("What Models ran")} title={t("Simulations")}
      detail={t("Each study with what it varies and how its simulations ended. Open one to see its simulations, and a simulation to see its results.")} />
    {EXECUTIONS_TABS("studies")}
    {error && <ErrorBox text={error} />}
    <section className="panel" aria-label={t("Studies")}>
      {!studies ? (error ? null : <Loading />) : <DataTable rows={studies} columns={columns} rowKey={(study) => study.id} label={t("Studies")}
        searchText={(study) => [groupName(study), study.model, study.description, study.created_by].join(" ")} searchPlaceholder={t("Search study or model")}
        initialSort={{ key: "last", descending: true }} empty={t("Nothing ran yet: a study simulates a model over the values you choose.")} onRowClick={(study) => navigate(groupPath(study))} />}
    </section>
  </>;
}

/** `/executions/queue`: what runs and waits now, and every run. */
export function QueuePage({ me }: { me: Me }) {
  const [state, error, reload] = usePolled(() => Promise.all([api.queue(), api.runs({ limit: "500" })]), "queue");
  const [queue, runs]: [QueueState | null, Run[] | null] = state ?? [null, null];
  return <>
    <Heading eyebrow={t("The queue")} title={t("Simulations")}
      detail={t("Every simulation and FMU export waits in one queue: what a person tests on a model's page first, then the studies.")} />
    {EXECUTIONS_TABS("queue")}
    <QueuePanel url={href("/api/queue")} Plot={Plot} title={t("Queue")} detail={t("Now and over time: items waiting, running and how long they waited.")} />
    {error && <ErrorBox text={error} />}
    {queue && <QueueLists queue={queue} me={me} onChanged={reload} />}
    <h2 className="section-title">{t("Simulations")}</h2>
    {!runs ? (error ? null : <Loading />) : <RunsTable runs={runs} me={me} onChanged={reload} label={t("Simulations")} />}
  </>;
}

/** `/executions/<id>`: one group, its summary and its simulations. */
export function GroupPage({ studyId, me }: { studyId: string; me: Me }) {
  const [study, error, reload] = usePolled(() => api.study(studyId), studyId);
  if (error && !study) return <ErrorBox text={error} />;
  if (!study) return <Loading />;
  const quick = study.kind === "quick";
  const runs = study.runs ?? [];
  const last = study.last_run_at ?? runs.reduce<string | null>((latest, run) => (!latest || run.created_at > latest ? run.created_at : latest), null);
  return <>
    <nav className="breadcrumb"><Link to="/executions">{t("Simulations")}</Link></nav>
    <Heading eyebrow={t(GROUP_KINDS[study.kind] ?? study.kind)} title={groupName(study)}
      actions={quick
        ? <Link to={modelPath(study.project_id, study.model)} className="button button-secondary">{t("Open the model")}</Link>
        : <Link to={`/studies/${encodeURIComponent(study.id)}`} className="button button-secondary">{t("Open the study")}</Link>} />
    <section className="panel mc-group-summary" aria-label={t("Summary")}>
      <dl className="facts">
        <div><dt>{t("Simulations")}</dt><dd><Link to={modelPath(study.project_id, study.model)}>{study.model.split(".").pop()}</Link><small className="muted"> · {study.project_name}</small></dd></div>
        <div><dt>{t("What varies")}</dt><dd>{variesText(study)}</dd></div>
        <div><dt>{t("Last simulation")}</dt><dd>{last ? `${formatDate(last)} (${formatAgo(last)})` : "–"}</dd></div>
        <div><dt>{t("How it ended")}</dt><dd>{countsText(study)}</dd></div>
      </dl>
      <StudyProgress study={study} />
    </section>
    <h2 className="section-title">{t("Simulations")}</h2>
    {quick ? <RunsTable runs={runs} me={me} onChanged={reload} label={t("Simulations")} /> : <SimulationsTable study={study} runs={runs} me={me} />}
  </>;
}
