/** Operations › Load alerts: when the suite's watch tells that an app or the machine is loaded.
 * Two levels (a warning, then critical), each held some minutes; administrators change them, the
 * Operations role reads them. See docs/operations.md, section 4. */
import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import { FormSection, Heading } from "@plantcraft/ui";
import { useEffect, useState, type FormEvent } from "react";
import { t } from "./i18n";
import { operationsApi, type LoadLimits } from "./operationsApi";
import { useIsAdmin } from "./session";
import "./access.css";
import "./apps.css";
import "./operations.css";

type NumberKey = Exclude<keyof LoadLimits, "enabled">;

const ROWS: Array<{ label: string; hint: string; warning: NumberKey; critical: NumberKey; unit: string; step: number }> = [
  { label: t("CPU"), hint: t("Of the CPUs each app may use (its limit), and of the whole machine."), warning: "cpu_warning", critical: "cpu_critical", unit: "%", step: 1 },
  { label: t("Memory"), hint: t("Of each app's memory limit, and the machine's memory in use."), warning: "memory_warning", critical: "memory_critical", unit: "%", step: 1 },
  { label: t("Errors logged"), hint: t("Errors a minute each server writes to its log."), warning: "errors_warning", critical: "errors_critical", unit: t("/ min"), step: 0.5 },
];

/** The sentence the page shows under the form, the way the watch applies the levels. */
export function limitsSummary(limits: LoadLimits): string {
  if (!limits.enabled) return t("Load alerts are off: only services down, the disk, backups and certificates are watched.");
  return t("An app or the machine above a level for {minutes} minutes in a row opens an incident: a message in Suite health (🟠 warning, 🔴 critical) and an event for Alarms. It ends once the value is back 5 points under the level.", { minutes: limits.minutes });
}

export function LoadAlertsPage() {
  const admin = useIsAdmin();
  const [limits, setLimits] = useState<LoadLimits | null>(null);
  const [draft, setDraft] = useState<LoadLimits | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    operationsApi.limits().then((value) => { setLimits(value); setDraft(value); }, (err) => setError(err instanceof Error ? err.message : t("Couldn't load.")));
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError("");
    setSaved(false);
    try { const value = await operationsApi.setLimits(draft); setLimits(value); setDraft(value); setSaved(true); } catch (err) { setError(err instanceof Error ? err.message : t("Couldn't save.")); }
    setBusy(false);
  }
  const changed = Boolean(limits && draft && JSON.stringify(limits) !== JSON.stringify(draft));
  return <div className="apps-page">
    <Heading title={t("Load alerts")} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!draft && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {draft && <form className="panel ops-limits" onSubmit={(event) => void save(event)}>
      <FormSection title={t("When to tell")} detail={admin ? t("The watch checks every 30 seconds. A level must hold for the minutes below before anyone is told, so a short peak (a report, a backup) says nothing.") : t("Only administrators change these levels.")}>
        <label className="ac-check"><input type="checkbox" checked={draft.enabled} disabled={!admin} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /> {t("Tell when an app or the machine is loaded")}</label>
        <div className="ops-limits-grid" role="table" aria-label={t("Levels")}>
          <div role="row" className="ops-limits-head"><span role="columnheader" /><span role="columnheader">{t("Warning")}</span><span role="columnheader">{t("Critical")}</span></div>
          {ROWS.map((row) => <div role="row" key={row.label} className="ops-limits-row">
            <span role="rowheader"><strong>{row.label}</strong><small>{row.hint}</small></span>
            {([row.warning, row.critical] as const).map((key) => <label role="cell" key={key} className="ops-limits-cell">
              <input type="number" inputMode="decimal" min={0} max={row.unit === "%" ? 100 : 10000} step={row.step} value={draft[key]} disabled={!admin || !draft.enabled}
                aria-label={`${row.label} · ${key.endsWith("critical") ? t("Critical") : t("Warning")}`}
                onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })} />
              <span className="muted">{row.unit}</span>
            </label>)}
          </div>)}
        </div>
        <label className="ops-limits-minutes"><span>{t("Held for")}</span>
          <input type="number" min={1} max={120} step={1} value={draft.minutes} disabled={!admin || !draft.enabled} onChange={(event) => setDraft({ ...draft, minutes: Math.round(Number(event.target.value)) })} />
          <span className="muted">{t("minutes")}</span>
        </label>
      </FormSection>
      <p className="muted">{limitsSummary(draft)}</p>
      {admin && <footer className="ops-limits-footer">
        {saved && !changed && <span className="ops-saved"><CheckCircle2 size={15} /> {t("Saved: the next check uses them.")}</span>}
        <button type="button" className="button button-secondary" disabled={!changed || busy} onClick={() => setDraft(limits)}>{t("Undo changes")}</button>
        <button className="button button-primary" disabled={!changed || busy}>{busy && <LoaderCircle className="spin" size={15} />} {t("Save")}</button>
      </footer>}
    </form>}
  </div>;
}
