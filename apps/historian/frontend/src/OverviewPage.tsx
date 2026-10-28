import { AppOverview, type BoardItem } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import type { Overview } from "./types";
import { ErrorBox } from "./ui";
import { BASE } from "./nav";

/** A new person's board: is data arriving from every source, and will the disk hold? The
 * signals by status beside the collector, the values stored per hour beside the map of every
 * signal by source, then the signals not collecting beside the archive. The points count, a
 * signal's trend and the sources stay declared, for anyone who adds them. */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "histcraft:statuses", widget: "histcraft:statuses", x: 0, y: 0, w: 8, h: 2 },
  { i: "histcraft:collector", widget: "histcraft:collector", x: 8, y: 0, w: 4, h: 2 },
  { i: "histcraft:stored", widget: "histcraft:stored", x: 0, y: 2, w: 6, h: 3 },
  { i: "histcraft:source-map", widget: "histcraft:source-map", x: 6, y: 2, w: 6, h: 3 },
  { i: "histcraft:not-collecting", widget: "histcraft:not-collecting", x: 0, y: 5, w: 6, h: 3 },
  { i: "histcraft:archive", widget: "histcraft:archive", x: 6, y: 5, w: 6, h: 3 },
];

/** The first page, in the frame of every app's Overview (`AppOverview`, the board of Desk's
 * Today): the widgets the Historian declares in app.toml and serves, so they read the same on
 * Desk. The page adds only its notice when the collector is not running. */
export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = () => api.overview().then((answer) => { setData(answer); setError(""); }).catch((err: Error) => setError(err.message));
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const collector = data?.collector;
  return <AppOverview app="histcraft" name={t("Historian")} url={BASE} defaultLayout={DEFAULT_BOARD}>
    {error && <ErrorBox text={error} />}
    {collector && !collector.running && <div className="notice notice-error">{collector.mode === "embedded"
      ? t("The collector is not running. Restart Historian; see the server log.")
      : t("The collector is not running. Start the histcraft-collector container (histcraft collect); it is the part that reaches the plant network.")}</div>}
  </AppOverview>;
}
