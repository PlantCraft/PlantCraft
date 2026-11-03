/**
 * Operations' guided tour (2026-11-03): short, apart from the platform's. The status of the
 * suite, the requests for help and, for administrators and a public demo's visitor, the backups;
 * it ends, like every app's tour, on the assistant's questions for the page. A sponsor at the
 * plant who opens only Requests and Partners gets those two.
 */
import { assistantTourStep, tt, type TourStep } from "@plantcraft/ui";

const WELCOME: TourStep = {
  title: tt("Welcome to Operations"),
  body: <p>{tt("Operations keeps the suite running, for IT and the integrators: the status of every app and data source, the requests for help, partners and their hours, support access, load alerts, backups and updates.")}</p>,
};

export function operationsTour(adminView: boolean, sponsorOnly = false): TourStep[] {
  if (sponsorOnly) return [
    WELCOME,
    {
      path: "/ops/partners",
      target: ".pcs-content .ops-partners",
      title: tt("Partners"),
      body: <p>{tt("The companies that work at the plant, their people, the last day of their access and the hours they logged on requests, month by month.")}</p>,
    },
  ];
  const steps: TourStep[] = [
    WELCOME,
    {
      path: "/health",
      target: '.pcs-content [data-tour="health"], .pcs-content .panel',
      title: tt("Status"),
      body: <p>{tt("Whether every app and data source is running, with its load and uptime. The suite checks itself every 30 seconds and tells the administrators in Messages when a part stops or is loaded.")}</p>,
    },
    {
      path: "/ops/requests",
      target: ".pcs-content .ops-requests .pc-dt, .pcs-content .ops-requests",
      title: tt("Requests"),
      body: <p>{tt("Ask for help, in every app's menu under your name, lands here: each request has a queue, a priority and targets for the first answer and the fix.")}</p>,
    },
  ];
  if (adminView) steps.push({
    path: "/backups",
    target: ".pcs-content .apps-status, .pcs-content .apps-page",
    title: tt("Backups"),
    body: <p>{tt("Backups on a schedule, each checked, and a restore tested in a separate copy, so the plant's data is never lost.")}</p>,
  });
  steps.push(assistantTourStep("/health", [
    tt("Explain why an app shows as stopped or loaded"),
    tt("List the requests waiting for a first answer"),
    tt("Sum up the load alerts of the last week"),
  ]));
  return steps;
}
