import { assistantTourStep, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { api } from "./api";
import { FileText, LayoutDashboard, Search } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own entry.
 * Overview first (`AppOverview`, the widgets each person arranges), then the library (`/documents`,
 * each document, each folder and the asset deep link `/assets/<id>`) and the search. The files
 * being read are in the suite's Queue of the side bar, not on a page of their own (final round,
 * 2026-10-27). */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  { to: "/", label: "Overview", icon: <LayoutDashboard />, match: (path) => path === "/" },
  {
    to: "/documents",
    // The same name as the page's title (owner, 2026-10-28).
    label: "Documents",
    icon: <FileText />,
    match: (path) => path === "/documents" || path.startsWith("/documents/") || path.startsWith("/assets/") || path.startsWith("/folders/"),
  },
  { to: "/search", label: "Search", icon: <Search />, match: (path) => path === "/search" },
];

/** The app's guided tour (@plantcraft/ui): opens the first time a person opens the app. */
/** The document the tour opens (the demo's valve history first), or null. */
export async function tourExample(): Promise<string | null> {
  try {
    const docs = await api.documents();
    const doc = docs.find((item) => item.number === "DOC-MH-001") ?? docs.find((item) => item.status === "indexed") ?? docs[0];
    return doc ? `/documents/${encodeURIComponent(doc.doc_id)}` : null;
  } catch {
    return null;
  }
}

export function tourSteps(example: string | null = null): TourStep[] {
  const steps: TourStep[] = [
    {
      title: tt("Welcome to Documents"),
      body: tt("The plant's manuals, narratives, datasheets, procedures and reports, read into passages that you and the assistant can find and cite by page."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("Search or ask the documents, see the latest ones and those not linked to assets yet. Customize arranges the widgets as you like."),
    },
    {
      path: "/documents",
      target: ".pcs-content .pc-dt, .pcs-content .empty",
      title: tt("Documents"),
      body: tt("Every document you may read, by folder: folders say who reads and who changes them. An editor sends files here; each one is read in the background and linked to the assets its tags name."),
    },
  ];
  // No step opens a document (owner, 2026-10-28: its text says little in a tour).
  steps.push(
    {
      path: example ? "/search?q=valve+stiction" : "/search",
      target: ".pcs-content .hits, .pcs-content .search-form",
      title: tt("Search"),
      body: tt("Ask in your own words, in English or Portuguese: the search matches the words and the meaning, and opens each passage at its page."),
    },
    assistantTourStep("/documents", [
      tt("Answer a question from the manuals, citing each page"),
      tt("Find the procedure for a task on an asset"),
      tt("Sum up what the documents say about an asset"),
      tt("List the documents not linked to any asset yet"),
    ]),
  );
  return steps;
}
