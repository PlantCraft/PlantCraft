/** Operations › Partners: the companies working at the plant (integrators, contractors). Each
 * is a group of kind "company" (Users › Groups): its teams, people, coordinator on its side,
 * sponsor at the plant, the last day of its access, its open requests and the hours its people
 * logged this month; below, the month's time report, exported as CSV for the month's review.
 * See docs/operations.md, section 4. */
import { AlertTriangle, Building2, Download, LoaderCircle } from "lucide-react";
import { type DataColumn, DataTable, Heading, saveFile } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { hoursText } from "./actionsBoard";
import { dayText, errorText, Go, PersonLink } from "./collab";
import { t } from "./i18n";
import { operationsApi, type Company, type HoursEntry, type HoursReport, type PartnersAnswer } from "./operationsApi";
import { monthRange } from "./OperationsRequests";
import { useIsAdmin } from "./session";
import "./apps.css";
import "./operations.css";

export function companyState(company: Pick<Company, "state" | "access_until">): { text: string; tone: "" | "warn" | "bad" } {
  const date = dayText(company.access_until);
  if (company.state === "ended") return { text: t("Access ended {date}", { date }), tone: "bad" };
  if (company.state === "ending") return { text: t("Access ends {date}", { date }), tone: "warn" };
  if (company.state === "active") return { text: t("Access until {date}", { date }), tone: "" };
  return { text: t("No end date"), tone: "" };
}

/** The month's time as CSV: one line per entry, for the plant's review and the company's invoice. */
export function hoursCsv(entries: HoursEntry[]): string {
  const cell = (value: unknown) => {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const head = ["day", "company", "person", "request", "title", "hours", "billable", "note"];
  const rows = entries.map((item) => [item.day, item.company_name ?? t("Plant"), item.display_name, item.action_id, item.title, item.hours, item.billable ? "yes" : "no", item.note].map(cell).join(","));
  return [head.join(","), ...rows].join("\n") + "\n";
}

const HOURS_COLUMNS: DataColumn<HoursEntry>[] = [
  { key: "day", label: t("Day"), sort: (item) => item.day, render: (item) => dayText(item.day) },
  { key: "company", label: t("Company"), sort: (item) => item.company_name ?? "", filter: { value: (item) => item.company_name ?? t("Plant") }, render: (item) => item.company_name ?? <span className="muted">{t("Plant")}</span> },
  { key: "person", label: t("Person"), sort: (item) => item.display_name, render: (item) => <PersonLink username={item.username} name={item.display_name} /> },
  { key: "request", label: t("Request"), sort: (item) => item.title, render: (item) => <Go to={`/actions/${item.action_id}`}>#{item.action_id} {item.title}</Go> },
  { key: "hours", label: t("Time"), className: "num", sort: (item) => item.hours, render: (item) => <>{hoursText(item.hours)}{!item.billable && <small className="apps-sub">{t("not billable")}</small>}</> },
  { key: "note", label: t("Note"), phone: "hide", render: (item) => item.note || <span className="muted">—</span> },
];

export function PartnersPage() {
  const admin = useIsAdmin();
  const [month, setMonth] = useState("");
  const [partners, setPartners] = useState<PartnersAnswer | null>(null);
  const [report, setReport] = useState<HoursReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([operationsApi.partners(month || undefined), operationsApi.hours(month || undefined)]).then(([found, hours]) => { setPartners(found); setReport(hours); setError(""); if (!month) setMonth(found.month); }, (err) => setError(errorText(err)));
  }, [month]);
  const companies = partners?.companies ?? [];
  return <div className="apps-page ops-partners">
    <Heading title={t("Partners")} actions={<>
      <label className="ops-month"><span>{t("Month")}</span><input type="month" value={month} onChange={(event) => event.target.value && setMonth(event.target.value)} /></label>
      <button type="button" className="button button-secondary" disabled={!report?.entries.length} onClick={() => report && saveFile(`plantcraft-hours-${report.month}.csv`, hoursCsv(report.entries), "text/csv")}><Download size={15} /> {t("Export hours")}</button>
    </>} />
    <p className="muted ops-intro">{t("The companies working at the plant: who they are, until when they have access, who sponsors them here, and the time they logged on requests.")}</p>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!partners && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {partners && !companies.length && <section className="panel ops-empty"><Building2 size={22} /><div><strong>{t("No company yet")}</strong><p className="muted">{t("A company is a group of kind Company in Users › Groups: its coordinator on its side, its teams as groups under it, the last day of its access and its sponsor at the plant.")}</p>{admin && <Go to="/users/groups">{t("Open Groups")}</Go>}</div></section>}
    {companies.length > 0 && <div className="ops-companies">{companies.map((company) => <CompanyCard key={company.group_id} company={company} />)}</div>}
    {report && <section className="panel ops-hours" aria-labelledby="ops-hours-title">
      <h2 id="ops-hours-title">{t("Time logged")} <small className="muted">{monthRange(report.first, report.last)} · {hoursText(report.hours)} · {t("{hours} billable", { hours: hoursText(report.billable_hours) })}</small></h2>
      <DataTable rows={report.entries} columns={HOURS_COLUMNS} rowKey={(item) => String(item.entry_id)} label={t("Time logged")} initialSort={{ key: "day", descending: true }}
        searchText={(item) => `${item.title} ${item.display_name} ${item.company_name ?? ""} ${item.note}`} searchPlaceholder={t("Filter the time")} empty={t("No time logged this month.")} />
    </section>}
  </div>;
}

function CompanyCard({ company }: { company: Company }) {
  const state = companyState(company);
  return <article className="panel ops-company" aria-label={company.name}>
    <header>
      <h2><Go to={`/groups/${encodeURIComponent(company.group_id)}`}>{company.name}</Go></h2>
      <span className={`apps-chip${state.tone === "warn" ? " apps-chip-warn" : state.tone === "bad" ? " apps-chip-bad" : ""}`}>{state.text}</span>
    </header>
    {company.description && <p className="muted">{company.description}</p>}
    <dl className="ops-company-facts">
      <div><dt>{t("Coordinator")}</dt><dd>{company.coordinator ? <PersonLink username={company.coordinator} name={company.coordinator_name} /> : "—"}</dd></div>
      <div><dt>{t("Sponsor at the plant")}</dt><dd>{company.sponsor ? <PersonLink username={company.sponsor} name={company.sponsor_name} /> : <span className="muted">{t("None")}</span>}</dd></div>
      <div><dt>{t("People")}</dt><dd>{company.people.length}{company.teams.length > 0 && <small className="muted"> · {t("{count} teams", { count: company.teams.length })}</small>}</dd></div>
      <div><dt>{t("Open requests")}</dt><dd>{company.open_requests}</dd></div>
      <div><dt>{t("Time this month")}</dt><dd>{hoursText(company.hours)}{company.hours > 0 && <small className="muted"> · {t("{hours} billable", { hours: hoursText(company.billable_hours) })}</small>}</dd></div>
    </dl>
    {company.people.length > 0 && <ul className="ops-company-people">{company.people.map((person) => <li key={person.username}>
      <PersonLink username={person.username} name={person.display_name} />
      {person.coordinator && <small className="apps-chip">{t("Coordinator")}</small>}
      {person.teams.length > 0 && <small className="muted">{person.teams.join(", ")}</small>}
      {!person.active && <small className="muted">{t("inactive")}</small>}
    </li>)}</ul>}
  </article>;
}
