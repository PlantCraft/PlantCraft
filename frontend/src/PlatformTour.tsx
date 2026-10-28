/**
 * The platform's guided tour (@plantcraft/ui's tour), in the order the owner asked (2026-10-28):
 * Desk's menu on the left (Today, the calendar, actions), then the quick buttons at the foot of
 * the menu (Messages, Notifications and the Assistant open their panels; the queues), then the switch to another app,
 * PlantCraft (assets, one asset, system health; People, Apps and Backups for administrators
 * and a public demo's visitor), and it ends on the other apps. Each app
 * opens with its own tour. With the demo story (`processcraft demo seed`) it walks the demo plant.
 * Its texts are in the tour's own language (`tt`, picked on the tour card); their translations are
 * in @plantcraft/ui.
 */
import { assistantTourStep, openPanel, tt, type TourStep } from "@plantcraft/ui";
import { appPurpose } from "./AppLauncher";
import { appIdFor, appLabel } from "./appMarks";
import type { HomeData } from "./types";

export function platformTour(data: HomeData, admin: boolean, readOnly = false, notebooks = false): TourStep[] {
  const demo = Boolean(data.demo_tour);
  const apps = data.apps.filter((app) => app.access);
  const steps: TourStep[] = [
    {
      path: "/",
      title: tt("Welcome to PlantCraft"),
      body: <>
        <p>{data.public_demo && readOnly
          ? tt("A live demo on a simulated refinery with 50 control loops. Nothing you change is saved.")
          : tt("One place for your plant's data, and a family of apps that work on it.")}</p>
        <p>{tt("Two minutes around the suite: use Next, or the arrow keys.")}</p>
      </>,
    },
    {
      path: "/",
      target: ".pcs-nav",
      title: tt("Desk: your day"),
      body: <p>{tt("You start in Desk, your own workspace: Today, your actions, the calendar, your to-dos and notes. Every app has its menu here, on the left.")}</p>,
    },
    {
      path: "/",
      target: '[data-tour="widgets"]',
      title: tt("Your day, your widgets"),
      body: <p>{tt("The coming days, your actions, your notifications and what each app publishes. Customize, at the top right, arranges them; each person keeps their own.")}</p>,
    },
    {
      path: "/calendar",
      target: ".dk-calendar .fc-view-harness",
      title: tt("Everything with a date"),
      body: <p>{tt("Your meetings, your actions and to-dos, alarms on what you follow and the apps' scheduled runs, in one calendar.")}</p>,
    },
    {
      path: "/actions",
      target: '[data-tour="actions"]',
      title: tt("Actions: follow up the work"),
      body: <p>{tt("Each repair or check gets an owner and a due date, and links back to the asset and the finding it came from.")}</p>,
    },
    ...(notebooks ? [{
      path: "/notebooks",
      target: ".pcs-content .nb-choice",
      title: tt("Notebooks: Python on the plant's data"),
      body: <p>{tt("Jupyter notebooks run in the browser, inside the platform, or on your own computer with the kit downloaded here. Either way your Python code reads the plant's data and the apps' results, and can run things in the platform.")}</p>,
    }] : []),
    {
      path: "/",
      // The panels open, so the step shows what is in them (owner, 2026-10-28).
      target: ".pc-messages-drawer",
      onShow: openPanel(".pcs-quick .pcs-messages", ".pc-messages-drawer"),
      title: tt("Messages"),
      body: <p>{demo
        ? tt("The quick buttons at the foot of the menu open a panel over any app. Messages: the team talks here about FIC-1003, the sticking valve.")
        : tt("The quick buttons at the foot of the menu open a panel over any app. Messages: talk with a person or a whole group about an asset or a finding.")}</p>,
    },
    {
      path: "/",
      target: ".pc-messages-drawer",
      onShow: openPanel(".pcs-quick .pcs-notifications", ".pc-messages-drawer"),
      title: tt("Notifications"),
      body: <p>{tt("Alarms, finished runs and changes to your actions, as they happen.")}</p>,
    },
    {
      path: "/",
      target: ".pc-assistant-panel",
      onShow: openPanel('[data-tour="assistant-button"]', ".pc-assistant-panel"),
      title: tt("The assistant"),
      body: <p>{data.public_demo && readOnly
        ? tt("Ask about any page in plain words; it reads the plant's data and documents and shows each step it took. It is off in this demo, but open it to read the team's chats.")
        : tt("Ask about any page in plain words; it reads the plant's data and documents and shows each step it took.")}</p>,
    },
    // Like every app's tour: the questions of this page (the journey test, 2026-10-28).
    assistantTourStep("/", [
      tt("Sum up what changed in the plant since your last shift"),
      tt("List your overdue actions and what each waits on"),
      tt("Find the assets with the most alarms this week"),
      tt("Draft a message to the team about a finding"),
    ]),
    {
      path: "/",
      target: ".pcs-queue-button",
      title: tt("Queues"),
      body: <p>{tt("The calculations the apps are running and waiting to run, with what failed.")}</p>,
    },
    {
      path: "/",
      target: ".pcs-switcher-pop .pcs-app-item:last-child",
      onShow: openPanel(".pcs-switcher .pcs-brand", ".pcs-switcher-pop"),
      title: tt("Apps, one click away"),
      body: <p>{tt("Desk is one app of the suite. The name at the top of the menu opens the others; next, PlantCraft.")}</p>,
    },
    {
      path: "/assets",
      target: '.pcs-content .as-tree',
      title: tt("PlantCraft: the plant as a tree"),
      body: <p>{tt("You are in another app now: PlantCraft, the platform. Sites, units and equipment, each with its record and signals, set up once for every app.")}</p>,
    },
  ];
  if (demo) steps.push({
    path: "/assets/FIC-1003",
    target: '[data-tour="asset-overview"]',
    title: tt("One asset, one page"),
    body: <p>{tt("FIC-1003 is the recycle flow loop, and its valve is sticking. Its page holds the record, the signals, actions and history, each in a tab.")}</p>,
  });
  steps.push({
    path: "/health",
    target: '.pcs-content [data-tour="health"], .pcs-content .panel',
    title: tt("System health"),
    body: <p>{tt("Whether every app and data source is running, each with its state and what it last said.")}</p>,
  });
  // The administration (owner, 2026-10-28): shown to administrators, and to a public demo's
  // visitor, who reads it without changing anything.
  if (admin) steps.push(
    {
      path: "/users",
      target: '[data-tour="users"]',
      title: tt("People and access"),
      body: <p>{tt("Who may sign in, and which apps each person opens: to edit, to read, or not at all. Groups, the next tab, are the teams: they share actions, messages and alarms.")}</p>,
    },
    {
      path: "/apps",
      target: ".pcs-content .apps-page",
      title: tt("Apps"),
      body: <p>{tt("The apps this installation runs, their versions and health. An administrator adds, updates or removes them here.")}</p>,
    },
    {
      path: "/backups",
      target: ".pcs-content .apps-page",
      title: tt("Backups"),
      body: <p>{tt("Backups on a schedule, each checked, and a restore tested in a separate copy, so the plant's data is never lost.")}</p>,
    },
  );
  steps.push({
    path: "/admin",
    target: ".pcs-user-pop",
    onShow: openPanel(".pcs-account .pcs-profile", ".pcs-user-pop"),
    title: tt("Help, in every app"),
    body: <p>{tt("The menu under your name holds Help, with a guide for every page of the app you are in, this tour, the theme and your preferences.")}</p>,
  });
  steps.push({
    path: "/admin",
    target: '[data-tour="apps"]',
    title: tt("Now the apps"),
    body: <>
      {apps.length
        ? <ul>{apps.map((app) => <li key={app.id}><b>{appLabel(app.id, app.name)}</b>: {appPurpose(appIdFor(app.id), tt).replace(/\.$/, "").replace(/^./, (first) => first.toLowerCase())}</li>)}</ul>
        : <p>{tt("No app is installed yet. An administrator adds them on the Apps page.")}</p>}
      <p>{tt("Open one to go on: each starts with its own short tour. You can take this tour again from the menu under your name.")}</p>
    </>,
  });
  return steps;
}
