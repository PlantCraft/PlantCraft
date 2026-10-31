import { DataTable, type DataColumn } from "@plantcraft/ui";
import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatNumber, t } from "./i18n";
import { navigate } from "./nav";
import { ResultTabs } from "./ResultsPage";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";
import type { ApcConstraint, ApcController, ApcList, ApcVariable } from "./types";

/** The windows a controller is read over (days). */
export const APC_WINDOWS = [1, 7, 31];

export const apcPath = (controllerId?: string) => (controllerId ? `/apc/${encodeURIComponent(controllerId)}` : "/apc");

const share = (value: number | null | undefined) => (value == null ? "—" : `${formatNumber(value, 0)}%`);
const num = (value: number | null | undefined) => (value == null ? "—" : formatNumber(value, 3));
const sideLabel = (side: "lo" | "hi" | null) => (side === "lo" ? t("Low limit") : side === "hi" ? t("High limit") : "");

/** The server's state: "alarm" when on or MVs in service under 50 % of the time, "warning" under 90 %. */
export const apcState = (controller: Pick<ApcController, "summary">) => controller.summary.state ?? "unknown";

const stateLabel = (state: string) => t(state === "ok" ? "Healthy" : state === "warning" ? "Warning" : state === "alarm" ? "Alarm" : "No data");

function Window({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  return <select aria-label={t("Window")} value={days} onChange={(event) => onChange(Number(event.target.value))}>
    {APC_WINDOWS.map((value) => <option key={value} value={value}>{value === 1 ? t("Last day") : t("Last {days} days", { days: value })}</option>)}
  </select>;
}

function Figures({ controller }: { controller: ApcController }) {
  const summary = controller.summary;
  return <div className="pc-grid">
    <div className="panel kpi-card"><span className="pc-overline">{t("On")}</span><b className="pc-num">{share(summary.on_pct)}</b><small>{summary.on_now ? t("On now") : t("Off now")}</small></div>
    <div className="panel kpi-card"><span className="pc-overline">{t("MVs in service")}</span><b className="pc-num">{share(summary.mv_in_service_pct)}</b><small>{t("{now} of {total} now", { now: summary.mvs_in_service, total: summary.mvs })}</small></div>
    <div className="panel kpi-card"><span className="pc-overline">{t("CVs at a limit")}</span><b className="pc-num">{share(summary.cv_at_limit_pct)}</b><small>{t("{now} of {total} now", { now: summary.cvs_at_limit, total: summary.cvs })}</small></div>
    <div className="panel kpi-card"><span className="pc-overline">{t("Active limits")}</span><b className="pc-num">{summary.constraints_active}</b><small>{t("now, of {count} in the window", { count: controller.constraints.length })}</small></div>
  </div>;
}

const LIST_COLUMNS: DataColumn<ApcController>[] = [
  { key: "name", label: t("Controller"), sort: (row) => row.name, render: (row) => <Link to={apcPath(row.id)}><b>{row.name}</b></Link> },
  { key: "state", label: t("State"), sort: (row) => ["alarm", "warning", "unknown", "ok"].indexOf(apcState(row)), render: (row) => <Pill status={apcState(row)} label={stateLabel(apcState(row))} /> },
  { key: "on", label: t("On"), numeric: true, sort: (row) => row.summary.on_pct ?? -1, render: (row) => share(row.summary.on_pct) },
  { key: "mvs", label: t("MVs in service"), numeric: true, sort: (row) => row.summary.mv_in_service_pct ?? -1, render: (row) => `${share(row.summary.mv_in_service_pct)} · ${row.summary.mvs_in_service}/${row.summary.mvs}` },
  { key: "cvs", label: t("CVs at a limit"), numeric: true, sort: (row) => row.summary.cv_at_limit_pct ?? -1, render: (row) => `${share(row.summary.cv_at_limit_pct)} · ${row.summary.cvs_at_limit}/${row.summary.cvs}` },
  { key: "top", label: t("Costliest limit"), className: "hide-narrow", render: (row) => { const top = row.constraints[0]; return top ? <small>{top.name} · {sideLabel(top.side)}{top.worth_1pct != null ? ` · ${num(top.worth_1pct)} ${row.cost_unit}` : ""}</small> : <span className="muted">—</span>; } },
];

/** Every third-party multivariable controller the person sees, read only. */
export function ApcListPage() {
  const [days, setDays] = useState(1);
  const [answer, setAnswer] = useState<ApcList | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { setAnswer(null); api.apc(days).then((value) => { setAnswer(value); setError(""); }).catch((err: Error) => setError(err.message)); }, [days]);
  return <>
    <Heading eyebrow={t("Third-party APC · read only")} title={t("Multivariable controllers")} actions={<Window days={days} onChange={setDays} />} />
    <ResultTabs tab="apc" />
    <p className="muted">{t("The time each controller was on, its manipulated variables in service and its controlled variables at a limit, from the controller's own signals. Analytics never writes to it.")}</p>
    {error ? <ErrorBox text={error} /> : !answer ? <Loading />
      : <DataTable rows={answer.controllers} columns={LIST_COLUMNS} rowKey={(row) => row.id} onRowClick={(row) => navigate(apcPath(row.id))} label={t("Multivariable controllers")}
          empty={t("No multivariable controller in the plant yet. Add an asset of type Multivariable controller in PlantCraft, with its MVs and CVs inside it.")} />}
  </>;
}

function variableColumns(unit: string): DataColumn<ApcVariable>[] {
  return [
    { key: "name", label: t("Variable"), sort: (row) => row.name, render: (row) => <span><b>{row.name}</b> <small className="muted">{row.kind.toUpperCase()}</small></span> },
    { key: "service", label: t("In service"), sort: (row) => row.in_service_pct ?? -1, render: (row) => <span>{row.in_service ? <Pill status="ok" label={t("In service")} /> : <Pill status="warning" label={t("Out of service")} />} <small className="muted">{share(row.in_service_pct)}</small></span> },
    { key: "value", label: t("Value"), numeric: true, sort: (row) => row.value ?? 0, render: (row) => num(row.value) },
    { key: "target", label: t("Target"), numeric: true, className: "hide-narrow", sort: (row) => row.target ?? 0, render: (row) => num(row.target) },
    { key: "limits", label: t("Limits"), className: "hide-narrow", render: (row) => `${num(row.lo)} – ${num(row.hi)}` },
    { key: "at", label: t("At a limit"), sort: (row) => row.at_limit_pct ?? -1, render: (row) => <span>{row.at ? <Pill status="warning" label={sideLabel(row.at)} /> : <span className="muted">{t("Free")}</span>} <small className="muted">{share(row.at_limit_pct)}</small></span> },
    { key: "price", label: t("Constraint cost"), numeric: true, className: "hide-narrow", sort: (row) => Math.abs(row.shadow_price ?? 0), render: (row) => (row.shadow_price == null ? "—" : `${num(row.shadow_price)} ${unit}`) },
  ];
}

function constraintColumns(unit: string): DataColumn<ApcConstraint>[] {
  return [
    { key: "name", label: t("Limit"), sort: (row) => row.name, render: (row) => <span><b>{row.name}</b> · {sideLabel(row.side)} <small className="muted">{row.kind.toUpperCase()}</small></span> },
    { key: "now", label: t("Now"), sort: (row) => (row.active_now ? 0 : 1), render: (row) => (row.active_now ? <Pill status="warning" label={t("Active")} /> : <span className="muted">{t("Not now")}</span>) },
    { key: "hours", label: t("Active"), numeric: true, sort: (row) => row.hours, render: (row) => `${formatNumber(row.hours, 1)} h · ${share(row.share_pct)}` },
    { key: "price", label: t("Constraint cost"), numeric: true, sort: (row) => row.shadow_price ?? -1, render: (row) => (row.shadow_price == null ? "—" : t("{cost} {unit} per unit", { cost: num(row.shadow_price), unit })) },
    { key: "worth", label: t("Worth of 1% more range"), numeric: true, sort: (row) => row.worth_1pct ?? -1, render: (row) => (row.worth_1pct == null ? <span className="muted">{t("No cost from the controller")}</span> : <b>{num(row.worth_1pct)} {unit}</b>) },
  ];
}

/** One controller: its figures, its MVs and CVs, and its active limits by what they cost. */
export function ApcPage({ controllerId }: { controllerId: string }) {
  const [days, setDays] = useState(1);
  const [controller, setController] = useState<ApcController | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { setController(null); api.apcController(controllerId, days).then((value) => { setController(value); setError(""); }).catch((err: Error) => setError(err.message)); }, [controllerId, days]);
  const unit = controller?.cost_unit ?? "";
  return <>
    <nav className="breadcrumb"><Link to={apcPath()}>{t("Multivariable controllers")}</Link><ChevronRight size={12} /><span>{controller?.name ?? controllerId}</span></nav>
    {error ? <ErrorBox text={error} /> : !controller ? <Loading /> : <>
      <Heading eyebrow={[t("Multivariable controller"), controller.vendor].filter(Boolean).join(" · ")} title={controller.name} actions={<Window days={days} onChange={setDays} />} />
      <Figures controller={controller} />
      <h2 className="section-title">{t("Active limits by cost")}</h2>
      <p className="muted">{t("A limit is active when the variable's target (its value, when the controller gives no target) sits within its band of the limit. Constraint cost is the controller's own shadow price; worth of 1% more range is what moving the limit by 1% of the variable's range would be worth.")}</p>
      <DataTable rows={controller.constraints} columns={constraintColumns(unit)} rowKey={(row) => `${row.variable_id}:${row.side}`} label={t("Active limits by cost")} empty={t("No limit was active in the window.")} />
      <h2 className="section-title">{t("Variables")}</h2>
      <DataTable rows={controller.variables ?? []} columns={variableColumns(unit)} rowKey={(row) => row.id} label={t("Variables")} empty={t("No MV or CV inside this controller.")} />
      {controller.failed.length > 0 && <p className="muted">{t("Not read: {signals}", { signals: controller.failed.join(", ") })}</p>}
    </>}
  </>;
}
