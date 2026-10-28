import { AppOverview, type BoardItem } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { BASE } from "./nav";
import type { Me, Summary } from "./types";
import { ErrorBox, message } from "./ui";

/** A new person's board answers "what is active, and is the alarm load within target?": the
 * alarms that need action by priority beside the hourly rate against its target, the alarm
 * summary beside the most frequent alarms, then the ISA-18.2 indicators. Active and raised in
 * 24 h stay in "Add a widget" (the split and the columns already say them). */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "alarmcraft:priorities", widget: "alarmcraft:priorities", x: 0, y: 0, w: 4, h: 2 },
  { i: "alarmcraft:rate", widget: "alarmcraft:rate", x: 4, y: 0, w: 8, h: 2 },
  { i: "alarmcraft:summary", widget: "alarmcraft:summary", x: 0, y: 2, w: 6, h: 3 },
  { i: "alarmcraft:bad-actors", widget: "alarmcraft:bad-actors", x: 6, y: 2, w: 6, h: 3 },
  { i: "alarmcraft:performance", widget: "alarmcraft:performance", x: 0, y: 5, w: 12, h: 2 },
];

/** Alarms' first page, in the frame of every app's Overview (`AppOverview`, the board of Desk's
 * Today): the widgets Alarms declares in app.toml and serves, arranged by each person. No buttons
 * on top (owner's review, 2026-10-27): the side menu opens Alarms, and the widgets open the
 * Performance page; each widget's title says on hover what it shows and in which order. */
export function OverviewPage({ me }: { me: Me }) {
  const [monitor, setMonitor] = useState<Summary["monitor"] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.summary().then((value) => setMonitor(value.monitor)).catch((err) => setError(message(err)));
  }, []);
  return <AppOverview app="alarmcraft" name={t("Alarms")} url={BASE} defaultLayout={DEFAULT_BOARD}>
    {error && <ErrorBox text={error} />}
    {!me.service_key && <div className="notice">{t("Alarms has no app key yet: it cannot read the plant on its own. An administrator sets it in PlantCraft (Apps).")}</div>}
    {monitor?.last_error && <div className="notice notice-error">{monitor.last_error}</div>}
  </AppOverview>;
}
