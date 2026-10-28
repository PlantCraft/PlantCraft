/**
 * Executions: the queue that runs everything Link does (owner, 2026-10-23). The panel shows the
 * numbers of now and the queue over 1 h to 30 days (@plantcraft/ui QueuePanel, the same in
 * every app); the list below has every execution, newest first: an algorithm on a loop or an
 * asset, a round, the past replayed. A person cancels one still waiting or runs one again.
 */
import { DataTable, MultiSelect, QueuePanel, type DataColumn } from "@plantcraft/ui";
import { RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { href, navigate } from "./nav";
import { EXECUTIONS_TABS } from "./ExecutionGroups";
import { Plot } from "@plantcraft/ui/plot";
import type { Execution, ExecutionList, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";

/** The list asks again this often (the panel has its own pace). */
const POLL_MS = 10_000;
const OPEN = ["queued", "running"];

export function executionWhen(row: Execution): string | null {
  return row.started_at ?? row.due_at ?? row.requested_at;
}

/** What the status column says beyond the pill: how far it got, the tries, the wait. */
export function executionDetail(row: Execution): string {
  // A failed execution says its reason, and after how many tries when there were several.
  if (row.status === "failed") return row.attempts > 1 ? `${t("After {n} tries", { n: row.attempts })}: ${row.error}` : "";
  const parts: string[] = [];
  if (row.status === "running" && row.progress?.total) parts.push(t("{done} of {total}", { done: row.progress.done, total: row.progress.total }));
  if (row.status === "queued" && row.due_at && new Date(row.due_at).getTime() > Date.now()) parts.push(t("from {time}", { time: formatDate(row.due_at) }));
  // The schedule's tries (owner, 2026-10-24): "try 2 of 3"; the queue's own retries say "try 2".
  if (row.attempts > 1) parts.push(row.max_attempts ? t("try {n} of {max}", { n: row.attempts, max: row.max_attempts }) : t("try {n}", { n: row.attempts }));
  return parts.join(" · ");
}

export function ExecutionsPage({ me }: { me: Me }) {
  const [list, setList] = useState<ExecutionList | null>(null);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [works, setWorks] = useState<string[]>([]);
  const [error, setError] = useState("");
  const load = () => api.executions({ status: statuses, work: works }).then((value) => { setList(value); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [statuses.join(","), works.join(",")]);
  const act = (action: () => Promise<unknown>) => (event: { stopPropagation: () => void }) => {
    event.stopPropagation();
    setError("");
    action().then(() => load()).catch((err: Error) => setError(err.message));
  };
  const columns: DataColumn<Execution>[] = [
    { key: "when", label: t("When"), sort: (row) => executionWhen(row) ?? "", render: (row) => <>{formatDate(executionWhen(row))}<small>{executionWhen(row) ? formatAgo(executionWhen(row)!) : ""}</small></> },
    { key: "work", label: t("Run"), sort: (row) => row.work_label, render: (row) => <><b>{row.algorithm?.name || row.name || row.work_label}</b><small>{row.work_label}</small></> },
    { key: "subject", label: t("On"), sort: (row) => row.subject, render: (row) => (row.subject_path ? <Link to={row.subject_path} className="pc-mono">{row.subject}</Link> : row.subject) },
    { key: "schedule", label: t("Monitor"), className: "hide-narrow", sort: (row) => row.schedule?.name ?? "", render: (row) => (row.schedule ? <Link to={`/schedules/${encodeURIComponent(row.schedule.id)}`}>{row.schedule.name || row.schedule.id}</Link> : <small>{t("Run now by {who}", { who: row.by || "—" })}</small>) },
    { key: "status", label: t("Status"), sort: (row) => row.status, render: (row) => <><Pill status={row.state} label={row.status_label} />{(executionDetail(row) || row.error) && <small className="clamp" title={row.error}>{executionDetail(row) || row.error}</small>}</> },
    { key: "wait", label: t("Waited"), numeric: true, className: "hide-narrow", sort: (row) => row.wait_seconds, render: (row) => <span className="pc-num">{row.wait_seconds === null ? "—" : formatDuration(row.wait_seconds)}</span> },
    { key: "duration", label: t("Took"), numeric: true, sort: (row) => row.duration_seconds, render: (row) => <span className="pc-num">{row.duration_seconds === null ? "—" : formatDuration(row.duration_seconds)}</span> },
    ...(me.can_edit ? [{
      key: "actions", label: "", render: (row: Execution) => <div className="row-actions">
        {row.can_cancel && <button type="button" className="icon-button" title={t("Cancel")} aria-label={t("Cancel")} onClick={act(() => api.cancelExecution(row.id))}><X size={16} /></button>}
        {row.can_rerun && <button type="button" className="icon-button" title={t("Run again")} aria-label={t("Run again")} onClick={act(() => api.rerunExecution(row.id))}><RotateCcw size={16} /></button>}
      </div>,
    }] : []),
  ];
  const statusOptions = Object.entries(list?.statuses ?? {}).filter(([key]) => !["scheduled", "waiting_data"].includes(key)).map(([id, label]) => ({ id, label }));
  const workOptions = Object.entries(list?.works ?? {}).map(([id, label]) => ({ id, label }));
  const open = (list?.items ?? []).filter((row) => OPEN.includes(row.status)).length;
  return <>
    <Heading eyebrow={t("Results")} title={t("Queue")}
      detail={t("Everything Analytics runs waits in one queue: what a person asked for first, then the monitors, then replays of the past.")} />
    {EXECUTIONS_TABS("queue")}
    <QueuePanel url={href("/api/queue")} Plot={Plot} title={t("Queue")} detail={t("Now and over time: items waiting, running and how long they waited.")} />
    {error && <ErrorBox text={error} />}
    <section className="panel" aria-label={t("Runs")}>
      <div className="panel-header"><div><h2>{t("Runs")}</h2><p>{list ? t("{total} runs, {open} waiting or running in this list.", { total: list.total, open }) : ""}</p></div></div>
      {!list ? (error ? null : <Loading />)
        : <DataTable
          rows={list.items}
          columns={columns}
          rowKey={(row) => row.id}
          onRowClick={(row) => row.path && navigate(row.path)}
          searchText={(row) => `${row.name} ${row.algorithm?.name ?? ""} ${row.subject} ${row.schedule?.name ?? ""} ${row.by} ${row.error}`}
          searchPlaceholder={t("Search algorithm, target, monitor or person")}
          label={t("Runs")}
          empty={t("Nothing ran yet.")}
          toolbar={<>
            <MultiSelect label={t("Status")} value={statuses} onChange={setStatuses} options={statusOptions} />
            <MultiSelect label={t("Type")} value={works} onChange={setWorks} options={workOptions} />
          </>}
        />}
    </section>
  </>;
}
