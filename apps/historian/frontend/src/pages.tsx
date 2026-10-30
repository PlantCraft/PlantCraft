import { assistantTourStep, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { api } from "./api";
import { Activity, Database, FileDown, FileUp, LayoutDashboard, Settings as SettingsIcon } from "lucide-react";

/** The app's own pages, in the suite's order (app standard, D7): Overview, then what it holds. */
export const NAV: Array<{ to: string; label: string; icon: ShellNavItem["icon"] }> = [
  { to: "/", label: "Overview", icon: <LayoutDashboard /> },
  { to: "/sources", label: "Sources", icon: <Database /> },
  { to: "/points", label: "Signals", icon: <Activity /> },
  // Imports and Exports each in the sidebar (no tabs under the title).
  { to: "/imports", label: "Imports", icon: <FileUp /> },
  { to: "/exports", label: "Exports", icon: <FileDown /> },
  { to: "/settings", label: "Settings", icon: <SettingsIcon /> },
];

/** The signal the tour opens: a control loop's measured value (the demo's FIC-1003), else the first
 * one with a value; null when there is none. */
export async function tourExample(): Promise<string | null> {
  try {
    const loops = await api.points("FIC-1003");
    const found = loops.find((point) => /\.PV$/i.test(point.tag)) ?? (await api.points("PV")).find((point) => point.kind === "number");
    return found?.signal ?? null;
  } catch {
    return null;
  }
}

/** The app's guided tour (@plantcraft/ui; texts in the tour language, translated there): opens the
 * first time a person opens the Historian. `example`: a signal whose page it opens. */
export function tourSteps(example: string | null = null): TourStep[] {
  return [
    {
            title: tt("Welcome to the Historian"),
      body: tt("The Historian collects every signal from your sources and keeps its history, compressed, for every app of the suite. What the apps calculate is stored here too."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("How many signals are collected, how they are doing, and how much the archive holds. Customize arranges the widgets as you like."),
    },
    {
      path: "/sources",
      target: ".pcs-content .table-panel, .pcs-content .empty",
      title: tt("Sources"),
      body: tt("Connections to plant systems: OPC UA, PI Web API, MQTT, Modbus, SQL and CSV files, with how often each is read and how long its history is kept."),
    },
    {
      path: "/points",
      target: ".pcs-content .table-panel, .pcs-content .empty",
      title: tt("Signals"),
      body: tt("Every signal with its last value and status. Open one for its trend, archive and settings."),
    },
    ...(example ? [{
      path: `/points/${encodeURIComponent(example)}`,
      target: '.pcs-content [data-tour="point-main"]',
      title: tt("One signal"),
      body: tt("A control loop's measured value: its current value and status, how much the archive holds and how well it compresses, and its trend over the period you pick."),
    }] : []),
    {
      path: "/imports",
      target: ".pcs-content .table-panel, .pcs-content .empty",
      title: tt("Imports"),
      body: tt("CSV and Excel files loaded once, checked before anything is written."),
    },
    {
      path: "/exports",
      target: ".pcs-content .export-layout",
      title: tt("Exports"),
      body: tt("Pick assets and signals, a period and a format: history goes out as one ZIP of open files, with the plant's metadata. Saved exports, on the left, run again in one click."),
    },
    {
      path: "/settings/retention",
      target: ".pcs-content .form-panel",
      title: tt("Settings"),
      body: tt("How long history is kept (retention), how often signals are read and how much they are compressed. Set here for every signal; a source or a single signal can set its own."),
    },
    assistantTourStep("/points", [
      tt("Find the signals that stopped updating or read bad quality"),
      tt("Compare a signal's last week with the week before"),
      tt("Explain how a source is collected and compressed"),
      tt("Prepare an export of a unit's signals for a period"),
    ]),
  ];
}
