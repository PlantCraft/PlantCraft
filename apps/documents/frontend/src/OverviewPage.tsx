import { AppOverview, type BoardItem } from "@plantcraft/ui";
import { Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { BASE, Link, navigate } from "./nav";
import type { DocRow, Me } from "./types";

/** A new person's board (owner, 2026-10-27: "where is the document I need?"): the search box
 * beside the count, then the latest documents beside those not linked to assets yet. The
 * reading widget stays in the catalog; what is being read is the notice above the board. */
const DEFAULT_BOARD: BoardItem[] = [
  { i: "doccraft:ask", widget: "doccraft:ask", x: 0, y: 0, w: 8, h: 2 },
  { i: "doccraft:count", widget: "doccraft:count", x: 8, y: 0, w: 4, h: 2 },
  { i: "doccraft:latest", widget: "doccraft:latest", x: 0, y: 2, w: 6, h: 3 },
  { i: "doccraft:unlinked", widget: "doccraft:unlinked", x: 6, y: 2, w: 6, h: 3 },
];

const READING = new Set(["queued", "indexing"]);

/** The page's own widget: words or a question, answered on the Search page. */
function AskBox() {
  const [text, setText] = useState("");
  return <form className="overview-ask" onSubmit={(event) => {
    event.preventDefault();
    if (text.trim()) navigate(`/search?${new URLSearchParams({ q: text.trim() })}`);
  }}>
    <div className="overview-ask-row">
      <input className="search-input" aria-label={t("Search or ask the documents")} placeholder={t("Search or ask the documents")}
        value={text} onChange={(event) => setText(event.target.value)} maxLength={500} />
      <button className="button button-primary" type="submit"><Search size={16} /> {t("Search")}</button>
    </div>
    <p className="muted">{t("Words, a tag or a question, in English or Portuguese: each passage found opens at its page.")}</p>
  </form>;
}

/** Documents' first page, in the frame of every app's Overview (`AppOverview`, the board of
 * Desk's Today): the search box (the page's own) and the widgets Documents declares in app.toml
 * and serves (the count, the latest, those not linked to assets), arranged by each person. No
 * button on top (final round, 2026-10-27): the library and sending files are on the Library
 * page of the side menu. */
export function OverviewPage(_props: { me: Me }) {
  const [docs, setDocs] = useState<DocRow[] | null>(null);
  const load = useCallback(() => api.documents().then(setDocs).catch(() => undefined), []);
  useEffect(() => { void load(); }, [load]);
  // While files are read, look again every few seconds.
  const reading = docs?.filter((doc) => READING.has(doc.status ?? "")).length ?? 0;
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [reading, load]);
  const widgets = [
    { id: "ask", title: t("Search"), size: "l" as const, sizes: [{ w: 6, h: 2 }, { w: 8, h: 2 }, { w: 12, h: 2 }], w: 8, h: 2,
      description: t("Search or ask the documents: the search matches the words and the meaning."), render: () => <AskBox /> },
  ];
  return <AppOverview app="doccraft" name={t("Documents")} url={BASE} widgets={widgets} defaultLayout={DEFAULT_BOARD}>
    {reading > 0 && <div className="notice">
      {reading === 1 ? t("1 document is being read.") : t("{n} documents are being read.", { n: reading })} <Link to="/documents">{t("See them in the library")}</Link>
    </div>}
  </AppOverview>;
}
