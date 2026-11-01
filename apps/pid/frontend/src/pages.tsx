import { tourClosing, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { FileStack, Network, PenTool } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own entry. */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  { to: "/", label: "Plant map", icon: <Network />, match: (path) => path === "/" || path === "/plant-map" || path.startsWith("/assets/") },
  { to: "/drawings", label: "Drawings", icon: <FileStack />, match: (path) => path.startsWith("/drawings") },
  { to: "/diagrams", label: "Diagrams", icon: <PenTool />, match: (path) => path.startsWith("/diagrams") },
];

/** The app's guided tour (@plantcraft/ui): opens the first time a person opens the app. */
export function tourSteps(): TourStep[] {
  return [
    {
      title: tt("Welcome to PID"),
      body: tt("PID reads the plant's P&IDs into one plant map: units, equipment, the lines between them and the control loops."),
    },
    {
      path: "/drawings",
      target: ".pcs-content",
      title: tt("Drawings"),
      body: tt("Send P&IDs as PDF, SVG, DEXPI or scans. Each sheet is read into tags and lines."),
    },
    {
      path: "/",
      target: ".pcs-content",
      title: tt("Plant map"),
      body: tt("The sheets joined into one plant. Check what was read, then export it to PlantCraft's assets, DEXPI or lists."),
    },
    tourClosing(),
  ];
}
