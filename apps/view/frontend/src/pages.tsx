import { assistantTourStep, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { api } from "./api";
import { diagramsApi } from "./diagrams/api";
import { FileText, LayoutDashboard, LineChart, Monitor, Workflow } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own entry.
 * View has four pages: Overview (`AppOverview`, the widgets each person arranges), Dashboards (the
 * list, each dashboard (`/d/<id>`) and the asset deep link (`/assets/<id>`)), Reports (`/reports`,
 * `/reports/<id>`) and Trends (`/trends`, `/trends/<id>`), the quick look last. */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  { to: "/", label: "Overview", icon: <LayoutDashboard />, match: (path) => path === "/" },
  {
    to: "/dashboards",
    label: "Dashboards",
    icon: <Monitor />,
    match: (path) => path.startsWith("/dashboards") || path.startsWith("/d/") || path.startsWith("/assets/"),
  },
  { to: "/diagrams", label: "Process", icon: <Workflow />, match: (path) => path.startsWith("/diagrams") },
  { to: "/reports", label: "Reports", icon: <FileText />, match: (path) => path.startsWith("/reports") },
  { to: "/trends", label: "Trends", icon: <LineChart />, match: (path) => path.startsWith("/trends") },
];

/** The pages the tour opens, when this installation has them (the demo's own first). */
export type TourExamples = { dashboard: string | null; diagram: string | null; report: string | null; trend: string | null };

const ref = (value: string) => encodeURIComponent(value);
const pick = <T extends { name: string }>(items: T[], name: RegExp) => items.find((item) => name.test(item.name)) ?? items[0];

export async function tourExamples(): Promise<TourExamples> {
  const found: TourExamples = { dashboard: null, diagram: null, report: null, trend: null };
  await Promise.all([
    api.dashboards().then((items) => { const item = pick(items, /plant overview/i); if (item) found.dashboard = `/d/${ref(item.dashboard_id)}`; }).catch(() => undefined),
    diagramsApi.list().then((items) => { const item = pick(items, /riverbend/i); if (item) found.diagram = `/diagrams/${ref(item.diagram_id)}`; }).catch(() => undefined),
    api.reports().then((items) => { const item = items[0]; if (item) found.report = `/reports/${ref(item.report_id)}`; }).catch(() => undefined),
    // Only a trend the team saved on purpose, never whatever comes first.
    api.trends().then((items) => { const item = items.find((entry) => /FIC-1003/.test(entry.name)); if (item) found.trend = `/trends/${ref(item.trend_id)}`; }).catch(() => undefined),
  ]);
  return found;
}

/** The app's guided tour (@plantcraft/ui; texts in the tour language, translated there): opens the
 * first time a person opens View. Each page, then one of its objects. */
export function tourSteps(examples: TourExamples = { dashboard: null, diagram: null, report: null, trend: null }): TourStep[] {
  const steps: TourStep[] = [
    {
      title: tt("Welcome to View"),
      body: tt("View shows the plant: dashboards to share by link, process displays, trends to look at any signal in a few clicks, and reports sent as PDF on a schedule."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("The dashboards, the saved trends and the public links at a glance. Customize arranges the widgets as you like."),
    },
    {
      path: "/dashboards",
      target: ".pcs-content .pc-grid, .pcs-content .tc-empty-list",
      title: tt("Your dashboards"),
      body: tt("Each tile is one dashboard, with a preview of its layout. A public link shows a dashboard on a wall screen without signing in, and can be revoked at any time."),
    },
  ];
  if (examples.dashboard) steps.push({
    path: examples.dashboard,
    target: ".pcs-content .tc-grid",
    title: tt("One dashboard"),
    body: tt("Panels over signals and the apps' results, live. Edit, at the top, moves and resizes the panels and adds new ones over any signal; New dashboard starts one from the plant's assets or an empty grid."),
  });
  steps.push({
    path: "/diagrams",
    target: ".pcs-content .pc-grid, .pcs-content .tc-empty-list",
    title: tt("Process"),
    body: tt("Process displays: the plant drawn with its equipment and live values, like the control room's screens, made from a library of symbols."),
  });
  if (examples.diagram) steps.push({
    path: examples.diagram,
    target: ".pcs-content .dg-zoom-stage",
    title: tt("One process display"),
    body: tt("Live values on the drawing, a vessel's level as it fills. Click a value for its trend, or a piece of equipment for its asset."),
  });
  steps.push({
    path: "/reports",
    target: ".pcs-content .pc-grid, .pcs-content .tc-empty-list",
    title: tt("Reports"),
    body: tt("A report is a document of panels, notes and events over one period. View makes it into a PDF every day or week and sends it to people and groups in Messages; every PDF sent stays here to read again."),
  });
  if (examples.report) steps.push({
    path: examples.report,
    target: ".pcs-content .tc-report-page",
    title: tt("One report"),
    body: tt("What it covers, when it is sent and to whom, and its sections as the PDF shows them."),
  });
  steps.push({
    path: examples.trend ?? "/trends",
    target: ".pcs-content .tc-trend-plot, .pcs-content .tc-trend-form",
    title: tt("Trends"),
    body: tt("Pick signals, draw them on one plot or on stacked plots, choose the period and how to aggregate, and save the trend to open it again or download its data. This one is saved by the team."),
  });
  // On a dashboard: the Overview has no assistant button.
  steps.push(assistantTourStep(examples.dashboard ?? "/dashboards", [
    tt("Build a dashboard of a unit's critical loops"),
    tt("Explain what a panel shows and where its data comes from"),
    tt("Draft a weekly report on the loops that got worse"),
    tt("Compare signals on a trend over the last shift"),
  ]));
  return steps;
}
