import { Dialog } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { algorithmOf } from "./algorithms";
import { api } from "./api";
import { t } from "./i18n";
import type { Algorithm, LoopConfig, SignalOption } from "./types";

const ROLES = [
  { role: "pv", label: "Process variable (PV)", required: true },
  { role: "sp", label: "Setpoint (SP)" },
  { role: "op", label: "Controller output (OP)" },
  { role: "mode", label: "Mode (1 = auto)" },
] as const;

/** Signal id field with suggestions read from PlantCraft. */
function SignalField({ role, label, value, required, onChange }: { role: string; label: string; value: string; required?: boolean; onChange: (value: string) => void }) {
  const [options, setOptions] = useState<SignalOption[]>([]);
  useEffect(() => {
    const timer = window.setTimeout(() => { if (value.length >= 2) api.signalSearch(value).then(setOptions).catch(() => setOptions([])); }, 250);
    return () => window.clearTimeout(timer);
  }, [value]);
  return <label>{t(label)}<input list={`signals-${role}`} value={value} required={required} onChange={(event) => onChange(event.target.value)} placeholder={t("PlantCraft signal id")} className="pc-mono" />
    <datalist id={`signals-${role}`}>{options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</datalist></label>;
}

/** Create a loop from PlantCraft signals, or edit one defined here. */
export function LoopForm({ loop, onClose, onSaved }: { loop?: LoopConfig; onClose: () => void; onSaved: (loopId: string) => void }) {
  const [form, setForm] = useState({
    loop_id: loop?.loop_id ?? "", name: loop?.name ?? "", area: loop?.area ?? "", service: loop?.service ?? "",
    profile_id: loop?.profile_id ?? "flow_loop", criticality: String(loop?.metadata?.criticality ?? "medium"),
  });
  const [signals, setSignals] = useState<Record<string, string>>({ pv: loop?.signals.pv ?? "", sp: loop?.signals.sp ?? "", op: loop?.signals.op ?? "", mode: loop?.signals.mode ?? "" });
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.algorithms().then((items) => { setAlgorithms(items); setForm((now) => ({ ...now, profile_id: algorithmOf(items, now.profile_id)?.algorithm_id ?? now.profile_id })); }).catch(() => setAlgorithms([])); }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const chosen = Object.fromEntries(Object.entries(signals).map(([key, value]) => [key, value.trim() || null]));
    try {
      if (loop) {
        await api.updateLoop(loop.loop_id, { name: form.name, area: form.area, service: form.service, signals: chosen, profile_id: form.profile_id, criticality: form.criticality });
        onSaved(loop.loop_id);
      } else {
        const saved = await api.createLoop({ ...form, area: form.area || "No area", signals: chosen });
        onSaved(saved.loop.loop_id);
      }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }

  return <Dialog title={loop ? t("Edit loop") : t("New loop")} onClose={onClose} onSubmit={(event) => void submit(event)}>
      <p className="muted">{t("A loop defined here reads its signals from PlantCraft by id. Loops from PlantCraft assets are edited there.")}</p>
      <div className="form-grid">
        <label>{t("Loop id")}<input value={form.loop_id} disabled={!!loop} required pattern="[A-Za-z0-9_.:\-]+" onChange={(event) => setForm({ ...form, loop_id: event.target.value })} className="pc-mono" /></label>
        <label>{t("Name")}<input value={form.name} required onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
        <label>{t("Area")}<input value={form.area} onChange={(event) => setForm({ ...form, area: event.target.value })} /></label>
        <label>{t("Service")}<input value={form.service} onChange={(event) => setForm({ ...form, service: event.target.value })} /></label>
        {ROLES.map((item) => <SignalField key={item.role} role={item.role} label={item.label} required={"required" in item} value={signals[item.role]} onChange={(value) => setSignals({ ...signals, [item.role]: value })} />)}
        <label>{t("Algorithm")}<select value={form.profile_id} onChange={(event) => setForm({ ...form, profile_id: event.target.value })}>{algorithms.filter((item) => item.subject_kind === "loop").map((item) => <option key={item.algorithm_id} value={item.algorithm_id}>{item.name}</option>)}</select></label>
        <label>{t("Criticality")}<select value={form.criticality} onChange={(event) => setForm({ ...form, criticality: event.target.value })}>{["critical", "high", "medium", "low"].map((item) => <option key={item} value={item}>{t(item[0].toUpperCase() + item.slice(1))}</option>)}</select></label>
      </div>
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy ? t("Saving…") : t("Save")}</button></footer>
  </Dialog>;
}
