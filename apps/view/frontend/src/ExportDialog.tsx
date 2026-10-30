/** Download a report in the format the person picks: the PDF, Word, HTML or Markdown. The same
 * dialog on the report's page and on the list of reports. */
import { Dialog } from "@plantcraft/ui";
import { Download, FileText } from "lucide-react";
import { exportUrl } from "./api";
import { t } from "./i18n";
import { EXPORTS } from "./reportModel";
import type { ExportFormat } from "./types";

/** `onPdf` makes a PDF now (the report's page); without it `pdfHref` opens the last one made
 * (the list), and with neither the PDF is left out. The other formats are the report read now. */
export function ExportDialog({ reportId, busy = false, onPdf, pdfHref, onClose }: { reportId: string; busy?: boolean; onPdf?: () => void; pdfHref?: string | null; onClose: () => void }) {
  return <Dialog title={t("Download the report")} onClose={onClose}>
    <p className="muted">{t("Each file is the report read now, over its period. Word and Markdown are for changing it; the web page keeps its charts interactive.")}</p>
    <div className="tc-export-list">
      {EXPORTS.map((item) => item.id === "pdf"
        ? onPdf
          ? <button key={item.id} type="button" className="tc-choice tc-export" disabled={busy} onClick={onPdf}><FileText size={18} aria-hidden /><span><b>{t(item.label)}</b><small>{t(item.hint)}</small></span></button>
          : pdfHref
            ? <a key={item.id} className="tc-choice tc-export" href={pdfHref} target="_blank" rel="noreferrer" onClick={() => window.setTimeout(onClose, 300)}><FileText size={18} aria-hidden /><span><b>{t(item.label)}</b><small>{t("The last one made, as it was sent.")}</small></span></a>
            : null
        : <a key={item.id} className="tc-choice tc-export" href={exportUrl(reportId, item.id as ExportFormat)} download onClick={() => window.setTimeout(onClose, 300)}><Download size={18} aria-hidden /><span><b>{t(item.label)}</b><small>{t(item.hint)}</small></span></a>)}
    </div>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Close")}</button></footer>
  </Dialog>;
}
