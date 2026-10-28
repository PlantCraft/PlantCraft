import { DataTable, type DataColumn } from "@plantcraft/ui";
import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import { formatPercent, methodLabel, performanceOf } from "./labels";
import { resultLabel, statusLabel } from "./status";
import type { Job, Me, MethodResult } from "./types";
import { ErrorBox, Health, Heading, Link, Loading, Pill } from "./ui";
import { LinkAssistant } from "./Assistant";

const RESULT_COLUMNS: DataColumn<MethodResult>[] = [
  { key: "method", label: t("Method"), sort: (item) => methodLabel(item.method_id), render: (item) => methodLabel(item.method_id) },
  { key: "status", label: t("Result"), sort: (item) => resultLabel(item.status), render: (item) => <Pill status={item.status} label={resultLabel(item.status)} />, filter: { value: (item) => resultLabel(item.status) } },
  { key: "performance", label: t("Performance"), numeric: true, sort: (item) => performanceOf(item), render: (item) => formatPercent(performanceOf(item)) },
  { key: "finding", label: t("Finding"), render: (item) => item.finding || item.message },
];

export function RunPage({ jobId, me }: { jobId: string; me: Me }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.job(jobId).then(setJob).catch((err: Error) => setError(err.message)); }, [jobId]);
  if (error) return <ErrorBox text={error} />;
  if (!job) return <Loading />;
  const summary = job.summary ?? {};
  return <>
    <nav className="breadcrumb"><Link to="/results/runs">{t("Run history")}</Link><ChevronRight size={12} /><span>{job.name}</span></nav>
    <Heading eyebrow={t("Run of {loop}", { loop: job.loop_id })} title={job.name}
      detail={job.source_start ? t("Window {start} to {end}.", { start: formatDate(job.source_start), end: formatDate(job.source_end) }) : job.error_message ?? t(job.status)}
      actions={<>
        {!["queued", "running"].includes(job.status) && <LinkAssistant kind="run" id={job.job_id} me={me} title={`${job.name} · ${job.loop_id}`} failed={job.status === "failed"} />}
        {me.can_edit && ["queued", "running"].includes(job.status) && <button className="button button-secondary" onClick={() => void api.cancelJob(job.job_id).then(setJob)}>{t("Cancel")}</button>}
      </>} />
    <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Run")}</span><Pill status={job.status} label={job.status_label ?? t(job.status)} /></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Loop status")}</span>{summary.status ? <Pill status={summary.status} label={statusLabel(summary.status)} /> : "—"}<Health value={summary.health} /></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Limiting criterion")}</span>{summary.limiting ? <><b>{methodLabel(summary.limiting.method_id)}</b><small>{summary.limiting.finding}</small></> : "—"}</div>
    </div>
    {job.error_message && <div className="notice notice-error">{job.error_message}</div>}
    {!!job.results?.length && <DataTable rows={job.results} columns={RESULT_COLUMNS} rowKey={(item) => item.method_id} initialSort={{ key: "method", descending: false }} label={t("Results")} />}
  </>;
}
