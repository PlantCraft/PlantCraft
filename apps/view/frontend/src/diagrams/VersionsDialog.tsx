/** The saves kept of a diagram (the last 30), newest first. One is brought back onto the
 * editor's canvas as a draft: Undo takes it away again and nothing is saved until Save. */
import { Dialog, errorMessage as message } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { formatDate, t } from "../i18n";
import { ErrorBox } from "../ui";
import { diagramsApi, type DiagramVersion } from "./api";
import type { DiagramDraft } from "./model";

export function VersionsDialog({ diagramId, onPick, onClose }: { diagramId: string; onPick: (diagram: DiagramDraft, version: number) => void; onClose: () => void }) {
  const [versions, setVersions] = useState<DiagramVersion[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  useEffect(() => { diagramsApi.versions(diagramId).then(setVersions).catch((err) => { setVersions([]); setError(message(err)); }); }, [diagramId]);

  async function pick(version: number) {
    setBusy(version);
    setError("");
    try { onPick((await diagramsApi.version(diagramId, version)).diagram, version); } catch (err) { setError(message(err)); } finally { setBusy(null); }
  }

  return <Dialog title={t("Versions")} onClose={onClose}>
    {error && <ErrorBox text={error} />}
    {versions === null && <p className="muted">{t("Reading the saves…")}</p>}
    {versions?.length === 0 && !error && <p className="muted">{t("No earlier saves are kept yet.")}</p>}
    {versions && versions.length > 0 && <table className="pc-table dg-versions">
      <thead><tr><th>{t("Version")}</th><th>{t("Saved")}</th><th>{t("By")}</th><th className="pc-num">{t("Elements")}</th><th /></tr></thead>
      <tbody>{versions.map((item) => <tr key={item.version}>
        <td>{item.version}</td><td>{formatDate(item.saved_at)}</td><td>{item.saved_by ?? "—"}</td><td className="pc-num">{item.elements}</td>
        <td><button className="button button-secondary button-small" disabled={busy !== null} onClick={() => void pick(item.version)}>{busy === item.version ? t("Opening…") : t("Bring back")}</button></td>
      </tr>)}</tbody>
    </table>}
    <p className="muted tc-dialog-note">{t("A version brought back replaces the canvas; Undo takes it away. Nothing is saved until you press Save.")}</p>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Close")}</button></footer>
  </Dialog>;
}
