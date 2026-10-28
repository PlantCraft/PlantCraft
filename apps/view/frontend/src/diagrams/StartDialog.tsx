/** Start a drawing from somewhere: laid out from a unit's assets, or drafted by the assistant
 * from what the person describes (`api/routers/diagram_drafts.py`). Nothing is saved: the
 * drawing replaces the editor's canvas, and Undo brings the old one back. */
import { Dialog, errorMessage as message, type AssetOption } from "@plantcraft/ui";
import { useMemo, useState, type FormEvent } from "react";
import { t } from "../i18n";
import { ErrorBox } from "../ui";
import { diagramsApi, type DiagramStart } from "./api";

export type StartMode = "assets" | "assistant";

const UNIT_KINDS = new Set(["plant", "site", "area", "unit", "section", "system", "train"]);

/** The assets a diagram can be drawn for: the units, else anything that holds other assets. */
export function unitsOf(assets: AssetOption[]): AssetOption[] {
  const units = assets.filter((asset) => UNIT_KINDS.has(String(asset.kind ?? "").toLowerCase()));
  if (units.length) return units;
  const parents = new Set(assets.map((asset) => asset.parent).filter(Boolean));
  return assets.filter((asset) => parents.has(asset.id));
}

export function StartDialog({ mode, assets, replaces, onDrawn, onClose }: {
  mode: StartMode; assets: AssetOption[]; replaces: boolean;
  onDrawn: (start: DiagramStart) => void; onClose: () => void;
}) {
  const units = useMemo(() => unitsOf(assets).sort((a, b) => a.name.localeCompare(b.name)), [assets]);
  const [unit, setUnit] = useState(units[0]?.id ?? "");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mode === "assets" && !unit) return;
    if (mode === "assistant" && !description.trim()) { setError(t("Say what the process display should show.")); return; }
    setBusy(true);
    setError("");
    try {
      onDrawn(mode === "assets" ? await diagramsApi.drawFromAssets(unit) : await diagramsApi.draft(description.trim(), unit || null));
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }

  return <Dialog title={mode === "assets" ? t("Draw from the plant's assets") : t("Draft with the assistant")} onClose={onClose} onSubmit={(event) => void submit(event)}>
    {error && <ErrorBox text={error} />}
    <div className="form-grid">
      {mode === "assistant" && <label>{t("What should the process display show?")}
        <textarea autoFocus rows={4} maxLength={2000} value={description} placeholder={t("Feed tank, two pumps in parallel and the column, with the level and the flows.")} onChange={(event) => setDescription(event.target.value)} />
      </label>}
      <label>{mode === "assets" ? t("Unit") : t("Unit (optional)")}
        <select value={unit} onChange={(event) => setUnit(event.target.value)} autoFocus={mode === "assets"}>
          {mode === "assistant" && <option value="">{t("The whole plant")}</option>}
          {units.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {mode === "assets" && !units.length && <small className="muted">{t("No units were found among the assets you can see.")}</small>}
    </div>
    <footer>
      <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
      <button className="button button-primary" type="submit" disabled={busy || (mode === "assets" && !unit)}>{busy ? t("Drawing…") : t("Draw")}</button>
    </footer>
    <p className="muted tc-dialog-note">{replaces ? t("The drawing replaces what is on the canvas; Undo brings it back. Nothing is saved until you press Save.") : t("Nothing is saved until you press Save.")}</p>
  </Dialog>;
}
