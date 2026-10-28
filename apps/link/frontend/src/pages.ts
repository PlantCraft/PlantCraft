import { assistantTourStep, tt, type TourStep } from "@plantcraft/ui";
import { createElement } from "react";
import { api } from "./api";
import { Blocks, BookOpen, CalendarClock, LayoutDashboard, ListOrdered, Workflow } from "lucide-react";

/** The suite frame's navigation, in the suite's page order (owner decision D9). */
export const NAV = [
  { to: "/", label: "Overview", icon: createElement(LayoutDashboard, { size: 16 }), match: (path: string) => path === "/" },
  // In the order of the work (owner, 2026-10-24): blocks make algorithms, schedules run them, Executions shows what they concluded.
  { to: "/blocks", label: "Blocks", icon: createElement(Blocks, { size: 16 }), match: (path: string) => path.startsWith("/blocks") || path.startsWith("/methods") },
  { to: "/algorithms", label: "Algorithms", icon: createElement(Workflow, { size: 16 }), match: (path: string) => path.startsWith("/algorithms") },
  { to: "/schedules", label: "Monitors", icon: createElement(CalendarClock, { size: 16 }), match: (path: string) => path.startsWith("/schedules") },
  // Executions and Results are one page (owner, 2026-10-24): schedule, then asset, then its history.
  { to: "/executions", label: "Results", icon: createElement(ListOrdered, { size: 16 }), match: (path: string) => ["/executions", "/results", "/runs", "/signals", "/loops", "/assets"].some((prefix) => path.startsWith(prefix)) },
];

/** Help is the frame's own entry (helpTo), after the pages. */
export const HELP = { to: "/help", label: "Help", icon: createElement(BookOpen, { size: 16 }) };

/** The app's guided tour (@plantcraft/ui; texts in the tour language, translated there): opens the first time a person opens Link. */
/** The pages the tour opens, when this installation has them (the demo's FIC-1003 first). */
export type TourExamples = { block: string | null; algorithm: string | null; result: string | null };

const ref = (value: string) => encodeURIComponent(value);

export async function tourExamples(): Promise<TourExamples> {
  const found: TourExamples = { block: null, algorithm: null, result: null };
  await Promise.all([
    api.blocks().then(({ blocks }) => {
      const block = blocks.find((item) => /stiction/i.test(item.block_id)) ?? blocks[0];
      if (block) found.block = `/blocks/${ref(block.site ? block.family : block.block_id)}/code`;
    }).catch(() => undefined),
    api.algorithms().then((algorithms) => {
      const algorithm = algorithms.find((item) => item.algorithm_id === "flow_loop") ?? algorithms[0];
      if (algorithm) found.algorithm = `/algorithms/${ref(algorithm.algorithm_id)}/diagram`;
    }).catch(() => undefined),
    api.executionGroups().then(async ({ groups }) => {
      const group = groups.find((item) => item.subject_kind === "loop" && item.subjects > 0) ?? groups.find((item) => item.subjects > 0);
      if (!group) return;
      const { subjects } = await api.executionGroup(group.id);
      const subject = subjects.find((item) => item.id.includes("FIC-1003")) ?? subjects[0];
      if (subject) found.result = `/executions/${ref(group.id)}/${ref(subject.id)}`;
    }).catch(() => undefined),
  ]);
  return found;
}

/** What a tab of an object's page shows: the panel right after its tabs. */
const TAB_CONTENT = ".pcs-content .pcs-tabs + *";

export function tourSteps(examples: TourExamples = { block: null, algorithm: null, result: null }): TourStep[] {
  const steps: TourStep[] = [
    {
      title: tt("Welcome to Analytics"),
      body: tt("Analytics runs algorithms on the plant's assets on a cadence: data quality, control loops, digital twins or your own. It tells you which results to look at first, and why."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("What Analytics runs and what it concluded: each monitor and how its last run ended, the queue and the latest runs. Customize adds the counts by status and arranges the widgets as you like."),
    },
    {
      path: "/blocks",
      target: ".pcs-content .pc-grid",
      title: tt("Blocks"),
      body: tt("Every block an algorithm can use, by library: its typed inputs and outputs, its parameters, formula and references. The editor and the assistant read the same descriptions."),
    },
  ];
  if (examples.block) steps.push({
    path: examples.block,
    target: TAB_CONTENT,
    title: tt("Inside a block"),
    body: tt("A block is Python code. Its tabs mark the inputs and outputs it takes and gives, test it on an asset, list the algorithms that use it and keep every version."),
  });
  steps.push({
    path: "/algorithms",
    target: ".pcs-content .pc-grid, .pcs-content .pc-dt",
    title: tt("Algorithms"),
    body: tt("Each algorithm is a block diagram that judges assets: PlantCraft's own are the reference, the site's start as a copy, each with its labels, owner, version and responsible group."),
  });
  if (examples.algorithm) steps.push({
    path: examples.algorithm,
    target: ".pcs-content .alg-diagram",
    title: tt("Inside an algorithm"),
    body: tt("Its diagram: blocks wired output to input. The tabs hold what it reads and gives, a test on an asset, where it is used and its versions."),
  });
  steps.push({
    path: "/executions",
    target: ".pcs-content .pc-dt, .pcs-content .empty",
    title: tt("Results"),
    body: tt("What Analytics ran and concluded, by monitor: open one to see each asset's latest result, and an asset to see its outputs over time and its past runs. The Queue tab shows what waits and runs now."),
  });
  if (examples.result) steps.push({
    path: examples.result,
    target: '.pcs-content [data-tour="over-time"]',
    title: tt("One result over time"),
    body: tt("How an output of this asset behaved, run after run. Outputs are saved in the Historian, so dashboards, alarms and the other apps read them too."),
  });
  steps.push(assistantTourStep("/executions", [
    tt("Rank the loops that got worse this week, and say why"),
    tt("Explain a result: which blocks and inputs led to it"),
    tt("Draft a new block in Python from a description"),
    tt("Set up a monitor that runs an algorithm every hour on a unit"),
  ]));
  return steps;
}
