import { tourClosing, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { NotebookPen } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own entry.
 * Notes holds each note and the asset deep link (`/assets/<id>`). */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  {
    to: "/",
    label: "Notes",
    icon: <NotebookPen />,
    match: (path) => path === "/" || path.startsWith("/notes/") || path.startsWith("/assets/"),
  },
];

/** The app's guided tour (@plantcraft/ui): opens the first time a person opens the app. */
export function tourSteps(): TourStep[] {
  return [
    {
      title: tt("Welcome to Starter"),
      body: tt("Starter keeps notes on the plant's assets: what a person saw, did or wants the next shift to know."),
    },
    {
      path: "/",
      target: ".pcs-content .panel",
      title: tt("Notes"),
      body: tt("Every note, newest first. An editor writes one on any asset of PlantCraft's asset tree; Ctrl+K finds them from anywhere in the suite."),
    },
    tourClosing(),
  ];
}
