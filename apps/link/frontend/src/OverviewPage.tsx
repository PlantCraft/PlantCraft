import { AppOverview, QueueSummary, type BoardItem } from "@plantcraft/ui";
import { lazy, Suspense } from "react";
import { t } from "./i18n";
import { BASE, href } from "./nav";

// The queue's chart is the only chart here: Plotly loads with it, after the page shows.
const Plot = lazy(() => import("@plantcraft/ui/plot").then((m) => ({ default: m.Plot })));

/** A new person's board (which loops and signals are bad now, and where):
 * the results by status beside the last 14 days in alarm, then the health map by area beside the
 * worst results, then the monitors and the queue (kept on the board). */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "linkcraft:results", widget: "linkcraft:results", x: 0, y: 0, w: 8, h: 2 },
  { i: "linkcraft:in-alarm-history", widget: "linkcraft:in-alarm-history", x: 8, y: 0, w: 4, h: 2 },
  { i: "linkcraft:health-map", widget: "linkcraft:health-map", x: 0, y: 2, w: 8, h: 3 },
  { i: "linkcraft:worst", widget: "linkcraft:worst", x: 8, y: 2, w: 4, h: 3 },
  { i: "linkcraft:schedules", widget: "linkcraft:schedules", x: 0, y: 5, w: 6, h: 3 },
  { i: "linkcraft:queue", widget: "linkcraft:queue", x: 6, y: 5, w: 6, h: 3 },
];

/**
 * The first page, in the frame of every app's Overview (`AppOverview`, the board of Desk's
 * Today): the widgets Link declares in app.toml and serves (results by status, the days in
 * alarm, the health map, the worst results, the schedules, and those a person adds), so they
 * read the same on Desk; the queue's chart is the page's own (it draws in the browser).
 */
export function OverviewPage() {
  const widgets = [
    { id: "queue", title: t("Queue"), size: "m" as const, description: t("What waits and runs now, and the queue over the last 24 hours."),
      render: () => <Suspense fallback={null}><QueueSummary url={href("/api/queue")} Plot={Plot} href={href("/executions")} /></Suspense> },
  ];
  // No buttons on top: an Overview only shows; runs start on Monitors.
  return <AppOverview app="linkcraft" name="Analytics" url={BASE} widgets={widgets} defaultLayout={DEFAULT_BOARD} />;
}
