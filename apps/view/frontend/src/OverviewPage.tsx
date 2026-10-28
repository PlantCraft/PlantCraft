import { AppOverview, type BoardItem } from "@plantcraft/ui";
import { t } from "./i18n";
import { BASE } from "./nav";

/** A new person's board, an entry point: the saved trends, the dashboards and the reports side
 * by side, then the process displays and the public links. Each row is a name and, below it,
 * when it was updated (or, for a report, when it goes out next). One dashboard stays one pick
 * away in "Add a widget". */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "dashcraft:trends", widget: "dashcraft:trends", x: 0, y: 0, w: 4, h: 3 },
  { i: "dashcraft:dashboards", widget: "dashcraft:dashboards", x: 4, y: 0, w: 4, h: 3 },
  { i: "dashcraft:reports", widget: "dashcraft:reports", x: 8, y: 0, w: 4, h: 3 },
  { i: "dashcraft:diagrams", widget: "dashcraft:diagrams", x: 0, y: 3, w: 4, h: 3 },
  { i: "dashcraft:public-links", widget: "dashcraft:public-links", x: 4, y: 3, w: 4, h: 3 },
];

/** View's first page, in the frame of every app's Overview (`AppOverview`, the board of Desk's
 * Today): the widgets View declares in app.toml and serves, arranged by each person. Nothing is
 * created here (owner, 2026-10-27): new dashboards, trends, reports and displays are made on
 * their own tabs. */
export function OverviewPage() {
  return <AppOverview app="dashcraft" name={t("View")} url={BASE} defaultLayout={DEFAULT_BOARD} />;
}
