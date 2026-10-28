/** A dashboard's diagram card: the saved diagram drawn live, scaled to fit the panel, coloured by
 * its values now (`api/views.py` `diagram_card`). A click opens the diagram's page when signed
 * in; a diagram the viewer may not see, or one deleted, says so instead. */
import { Workflow } from "lucide-react";
import { useMemo } from "react";
import { t } from "../i18n";
import { navigate } from "../nav";
import type { CardData } from "../types";
import { DiagramCanvas } from "./DiagramCanvas";
import { shownAt, type DiagramDraft } from "./model";
import "./diagrams.css";

export function DiagramCardBody({ data }: { data: CardData }) {
  const found = data.diagram;
  const diagram: DiagramDraft | null = useMemo(() => (found ? { ...found, folder_id: "", tags: [] } : null), [found]);
  const symbols = useMemo(() => new Map((found?.symbols ?? []).map((item) => [item.id, item])), [found]);
  const shows = useMemo(() => (diagram ? shownAt(diagram.elements, data.data ?? null, {}, null) : undefined), [diagram, data.data]);
  if (!diagram) return <div className="dg-card-missing" role="note"><Workflow size={18} aria-hidden="true" /> {data.unavailable || t("This process display is not available.")}</div>;
  const problems = (data.data?.bindings ?? []).filter((row) => row.error).length;
  const open = data.url ? () => navigate(data.url!) : undefined;
  return <div className={`dg-card${open ? " dg-card-open" : ""}`}>
    <div className="dg-card-stage" onClick={open} role={open ? "link" : undefined} tabIndex={open ? 0 : undefined}
      aria-label={open ? t("Open the process display {name}", { name: diagram.name }) : undefined} title={open ? t("Open the process display {name}", { name: diagram.name }) : undefined}
      onKeyDown={open ? (event) => { if (event.key === "Enter") open(); } : undefined}>
      <DiagramCanvas diagram={diagram} symbols={symbols} shows={shows} />
    </div>
    {problems > 0 && <small className="dg-card-note">{t("{n} values cannot be read", { n: problems })}</small>}
  </div>;
}
