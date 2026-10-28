import { AppOverview, type BoardItem } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { BASE } from "./nav";
import type { Me, RunnerState } from "./types";

/** A new person's board: what ran (simulations per day) and what the latest study gave, then
 * where to continue: the models, the latest runs and the studies. The runner takes no card: the
 * notice above the board says when it is down. */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "modelcraft:activity", widget: "modelcraft:activity", x: 0, y: 0, w: 8, h: 2 },
  { i: "modelcraft:latest-study", widget: "modelcraft:latest-study", x: 8, y: 0, w: 4, h: 2 },
  { i: "modelcraft:models", widget: "modelcraft:models", x: 0, y: 2, w: 4, h: 3 },
  { i: "modelcraft:runs", widget: "modelcraft:runs", x: 4, y: 2, w: 4, h: 3 },
  { i: "modelcraft:studies", widget: "modelcraft:studies", x: 8, y: 2, w: 4, h: 3 },
];

/** Models' first page, in the frame of every app's Overview (`AppOverview`, the board of Desk's
 * Today): the widgets Models declares in app.toml and serves (simulations per day, the latest
 * study, the models, runs and studies, one model, the runner), arranged by each person; above
 * them, a notice only while the runner is down. No buttons on top (owner, 2026-10-27): the side
 * menu goes to the models, and New model is on Models. */
export function OverviewPage(_props: { me: Me }) {
  const [runner, setRunner] = useState<RunnerState | null>(null);
  useEffect(() => { api.runner().then(setRunner).catch(() => undefined); }, []);
  return <AppOverview app="modelcraft" name={t("Models")} url={BASE} defaultLayout={DEFAULT_BOARD}>
    {runner && !runner.available && <div className="notice">{t("The Modelica runner is not available: {reason} Checks and simulations wait for it; an administrator can bring it back (Help, The Modelica runner).", { reason: runner.reason })}</div>}
  </AppOverview>;
}
