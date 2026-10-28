import { assistantTourStep, tt, type ShellNavItem, type TourStep } from "@plantcraft/ui";
import { api } from "./api";
import { blockPath, modelPath, runPath } from "./paths";
import { FlaskConical, LayoutDashboard, ListOrdered, Puzzle, Workflow } from "lucide-react";

/** The app's own pages in the suite frame (app standard, section 10); Help is the frame's own
 * entry. One level, no sub-items, in Link's order (owner, 2026-10-24): Blocks are what a diagram
 * is drawn with, Models the diagrams (and the code a model or a library is written in), Studies
 * compare a model's runs over its parameters, Executions are the queue and every run. */
export const NAV: Array<Omit<ShellNavItem, "label"> & { label: string }> = [
  {
    to: "/",
    label: "Overview",
    icon: <LayoutDashboard />,
    match: (path) => path === "/",
  },
  {
    to: "/blocks",
    label: "Blocks",
    icon: <Puzzle />,
    match: (path) => path === "/blocks" || path.startsWith("/blocks/"),
  },
  {
    to: "/models",
    label: "Models",
    icon: <Workflow />,
    match: (path) => ["/models", "/code", "/assets/"].some((prefix) => path === prefix || path.startsWith(prefix.endsWith("/") ? prefix : `${prefix}/`)),
  },
  {
    to: "/studies",
    label: "Studies",
    icon: <FlaskConical />,
    match: (path) => path === "/studies" || path.startsWith("/studies/"),
  },
  {
    to: "/executions",
    label: "Simulations",
    icon: <ListOrdered />,
    match: (path) => ["/executions", "/runs"].some((prefix) => path === prefix || path.startsWith(`${prefix}/`)),
  },
];

/** The pages the tour opens, when this installation has them: a block, an example model and a
 * finished simulation (owner, 2026-10-28). */
export type TourExamples = { block: string | null; model: string | null; run: string | null };

export async function tourExamples(): Promise<TourExamples> {
  const found: TourExamples = { block: null, model: null, run: null };
  await Promise.all([
    api.catalog().then(({ blocks }) => {
      const block = blocks.find((item) => /tank/i.test(item.block_id)) ?? blocks.find((item) => /pid/i.test(item.block_id)) ?? blocks[0];
      if (block) found.block = blockPath(block.block_id);
    }).catch(() => undefined),
    api.models().then((models) => {
      const model = models.find((item) => item.example && item.diagram) ?? models.find((item) => item.diagram) ?? models[0];
      if (model) found.model = modelPath(model.project_id, model.model, model.diagram ? "diagram" : "overview");
    }).catch(() => undefined),
    api.runs({ status: "done", kind: "simulate", limit: "1" }).then((runs) => {
      if (runs[0]) found.run = runPath(runs[0]);
    }).catch(() => undefined),
  ]);
  return found;
}

/** What a tab of an object's page shows: the panel right after its tabs. */
const TAB_CONTENT = ".pcs-content .pcs-tabs + *";

/** The app's guided tour (@plantcraft/ui): opens the first time a person opens Models. */
export function tourSteps(examples: TourExamples = { block: null, model: null, run: null }): TourStep[] {
  const steps: TourStep[] = [
    {
      title: tt("Welcome to Models"),
      body: tt("Models is for studying a process: draw it from blocks with inputs and outputs, choose the solver and the time step, run it over time and compare simulations with different parameters. It never runs on the plant."),
    },
    {
      path: "/",
      target: '.pcs-content [data-tour="widgets"]',
      title: tt("Overview"),
      body: tt("Models at a glance: the latest simulations and the Modelica runner. Customize chooses and orders the widgets; PlantCraft's Overview can show them too."),
    },
    {
      path: "/blocks",
      target: ".pcs-content .pc-grid, .pcs-content .mc-blocks",
      title: tt("Blocks"),
      body: tt("What a diagram is drawn with: sources, math, continuous dynamics, control, process equipment and scopes, by library."),
    },
  ];
  if (examples.block) steps.push({
    path: examples.block,
    target: TAB_CONTENT,
    title: tt("Inside a block"),
    body: tt("Its inputs, outputs and parameters, how it is drawn, its Modelica code, the models that use it and its versions, each in a tab."),
  });
  steps.push({
    path: "/models",
    target: ".pcs-content .pc-dt, .pcs-content .empty",
    title: tt("Models"),
    body: tt("Every model, the examples first. Each is a diagram of blocks; one written in Modelica code is one block."),
  });
  if (examples.model) steps.push({
    path: examples.model,
    target: ".pcs-content .mc-page-diagram, .pcs-content .mc-page-main",
    title: tt("Inside a model"),
    body: tt("Its diagram (the editor opens in its own window), its parameters, a test run, the studies that use it and its versions, in tabs like Analytics' algorithms."),
  });
  steps.push({
    path: "/studies",
    target: ".pcs-content .pc-dt, .pcs-content .empty",
    title: tt("Studies: simulation and optimization"),
    body: tt("A study either simulates one model for every combination of the values you choose and ranks the runs by an indicator such as overshoot or settling time, or optimizes: it searches the parameters that make an indicator best."),
  });
  steps.push({
    path: "/executions",
    target: ".pcs-content .pc-queue, .pcs-content .pc-dt",
    title: tt("Simulations"),
    body: tt("The queue now and over time, and every study and each model's single simulations. Any simulation can be cancelled while it waits or runs."),
  });
  if (examples.run) steps.push({
    path: examples.run,
    target: ".pcs-content .mc-results",
    title: tt("A simulation's results"),
    body: tt("Pick variables on the left to plot them over time, and compare with another run, as in a Modelica tool."),
  });
  steps.push(assistantTourStep("/models", [
    tt("Draw a model from a description of the process"),
    tt("Explain what a block or a model computes"),
    tt("Set up a study that compares tunings by overshoot and settling time"),
    tt("Compare two simulations and say what changed"),
  ]));
  return steps;
}
