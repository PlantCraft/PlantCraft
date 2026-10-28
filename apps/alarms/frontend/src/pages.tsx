import { assistantTourStep, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { BellRing, Inbox, LayoutDashboard, ListChecks } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own entry.
 * In the order things happen (owner's review, 2026-10-27): Overview, the app's widgets; Events, what
 * the other apps report; Rules, built on values and events; Alarms, raised when a rule holds, each
 * with its own history (and the asset deep link `/assets/<id>`). */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  {
    to: "/",
    label: "Overview",
    icon: <LayoutDashboard />,
    match: (path) => path === "/" || path === "/performance" || path === "/targets",
  },
  {
    to: "/events",
    label: "Events",
    icon: <Inbox />,
    match: (path) => path === "/events" || path.startsWith("/events/"),
  },
  {
    to: "/rules",
    label: "Rules",
    icon: <ListChecks />,
    match: (path) => path === "/rules" || path.startsWith("/rules/") || path === "/silences",
  },
  {
    to: "/alarms",
    label: "Alarms",
    icon: <BellRing />,
    match: (path) => path === "/alarms" || path.startsWith("/alarms/") || path.startsWith("/assets/") || path.startsWith("/history"),
  },
];

/** The app's guided tour (@plantcraft/ui): opens the first time a person opens Alarms. */
/** The first row of the page's table (owner, 2026-10-28: point at an event, a rule or an alarm,
 * not at the search and filters), or the page's empty state. */
// The whole list, as in the other apps' tours (owner, 2026-10-28).
const LIST = ".pcs-content .pc-dt, .pcs-content .empty";

export function tourSteps(): TourStep[] {
  return [
    {
      title: tt("Welcome to Alarms"),
      body: tt("Alarms tells the right person when something needs action. Rules read two things: values (the plant's signals and what the apps compute, such as a loop's health) and events (what the apps report, such as an Analytics run that failed or a signal without data). A rule that holds raises an alarm."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("The alarms at a glance: which need action, the load of the last 24 hours and the alarms raised most often. Hover a widget's title for what it shows; Customize chooses and orders the widgets."),
    },
    {
      path: "/events",
      target: LIST,
      title: tt("Events"),
      body: tt("What the other apps reported, only when something changes. Open now keeps what started and has not ended; All, every event of the period. Events notify nobody on their own. Open one for where it came from (the Analytics run behind it, for example); a rule decides when events like it become an alarm."),
    },
    {
      path: "/rules",
      target: LIST,
      title: tt("Rules"),
      body: tt("Each rule reads as a sentence: where (assets, a branch, a type, an Analytics monitor), when (written Simple or in Python) and its outputs (Alarms, dashboards, messages, email). One rule makes one alarm per asset, and its messages are gathered so 50 loops do not become 50 messages."),
    },
    {
      path: "/alarms",
      target: LIST,
      title: tt("Alarms"),
      body: tt("Every alarm a rule raised, most urgent first; each also reaches its people in Notifications, beside Messages. Acknowledge says you have seen it; shelve silences a nuisance alarm for a while, with a reason."),
    },
    assistantTourStep("/alarms", [
      tt("Say which alarms came back most often this week, and why"),
      tt("Write a rule from a sentence, such as a loop critical for over an hour"),
      tt("Explain an alarm: the rule, the values and the event behind it"),
      tt("Find nuisance alarms worth shelving or retuning"),
    ]),
  ];
}
