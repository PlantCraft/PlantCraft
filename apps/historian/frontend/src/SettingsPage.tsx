import { NextSteps } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href, navigate } from "./nav";
import { forecastLine } from "./levels";
import type { Forecast, Me, Settings } from "./types";
import { ErrorBox, FormFooter, FormSection, Heading, Link, Loading } from "./ui";

const FIELDS: { key: keyof Settings; label: string; help: string; step: string }[] = [
  { key: "retention_days", label: "Retention (days)", help: "Archived values older than this are deleted, unless a source or a signal sets its own.", step: "1" },
  { key: "default_scan_seconds", label: "Scan period (s)", help: "How often a signal is read, unless its source or the signal sets its own.", step: "0.1" },
  { key: "default_deviation_percent", label: "Deviation (% of span)", help: "Compression of a signal with a known range, unless its source or the signal sets its own: the rebuilt signal never strays more than this from a value read.", step: "0.01" },
  { key: "default_exception_percent", label: "Exception (% of span)", help: "Before the compression, a value within this of the last one passed on is taken as that value: noise smaller than it is never archived. 0 turns it off.", step: "0.01" },
  { key: "default_max_seconds", label: "Longest interval between archived values (s)", help: "A flat signal is still archived this often, unless its source or the signal sets its own.", step: "1" },
];

const SECTIONS: { title: string; detail: string; keys: (keyof Settings)[] }[] = [
  { title: "Retention", detail: "How long archived values are kept.", keys: ["retention_days"] },
  { title: "Collection and compression", detail: "How often signals are read and how much of what is read is archived.", keys: ["default_scan_seconds", "default_exception_percent", "default_deviation_percent", "default_max_seconds"] },
];

/** Settings: one tile per group, as PlantCraft's Setup and every app (owner, 2026-10-22). */
export function SettingsPage({ me, section }: { me: Me; section?: string }) {
  if (section === "retention") return <RetentionPage me={me} />;
  if (section) return <ErrorBox text={t("Page not found.")} />;
  return <>
    <Heading eyebrow={t("Historian")} title={t("Settings")} detail={t("How the Historian collects and keeps the plant's history.")} />
    <NextSteps title={t("Collection and history")} href={href} navigate={navigate} items={[
      { title: t("Retention and collection"), detail: t("How long history is kept, how often signals are read and how much they are compressed. Set here for every signal; a source or a single signal can set its own, and the most specific wins."), to: "/settings/retention", cta: t("Open") },
    ]} />
  </>;
}

/** The general level of retention and collection; a source's and a point's own values win over it. */
function RetentionPage({ me }: { me: Me }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [forecast, setForecast] = useState<Forecast | null>(null);
  useEffect(() => {
    api.overview().then((answer) => setForecast(answer.archive.forecast ?? null)).catch(() => setForecast(null));
    api.settings().then((answer) => { setSettings(answer); setDraft(Object.fromEntries(Object.entries(answer).map(([k, v]) => [k, String(v)]))); }).catch((err: Error) => setError(err.message));
  }, []);
  if (!settings && error) return <ErrorBox text={error} />;
  if (!settings) return <Loading />;
  async function save() {
    setError(""); setMessage("");
    try {
      const answer = await api.saveSettings(Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, Number(v)])));
      setSettings(answer);
      setMessage(t("Settings saved. The collector applies them within seconds."));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  return <>
    <div className="breadcrumb"><Link to="/settings">{t("Settings")}</Link> / <span>{t("Retention and collection")}</span></div>
    <Heading eyebrow={t("Settings")} title={t("Retention and collection")} detail={`${t("General settings of every signal. A source can set its own for its signals (Sources, Edit), and a signal its own (its page); the most specific wins.")}${me.is_admin ? "" : ` ${t("Only administrators change these settings.")}`}`} />
    <ol className="levels" aria-label={t("Where a setting comes from")}>
      <li><b>{t("General")}</b><span>{t("This page: every signal, unless something more specific is set.")}</span></li>
      <li><b>{t("Source")}</b><span>{t("Overrides the general value for the source's signals.")}</span></li>
      <li><b>{t("Signal")}</b><span>{t("Overrides both for that one signal.")}</span></li>
    </ol>
    {forecast && <div className={forecastLine(forecast).warn ? "notice notice-warn" : "notice"} role="status">
      <b>{t("Disk")}</b> {forecastLine(forecast).text} {t("At the values archived in the last 24 h, each signal kept for its retention.")}</div>}
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    <div className="panel form-panel">
      {SECTIONS.map((section) => <FormSection key={section.title} title={t(section.title)} detail={t(section.detail)}>
        <div className="form-grid">{FIELDS.filter((field) => section.keys.includes(field.key)).map((field) => <label key={field.key}>
          {t(field.label)}
          <input type="number" min="0" step={field.step} disabled={!me.is_admin} value={draft[field.key] ?? ""} onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} />
          <small>{t(field.help)}</small>
        </label>)}</div>
      </FormSection>)}
      {me.is_admin && <FormFooter note={t("The collector applies saved settings within seconds.")}><button className="button button-primary" onClick={() => void save()}>{t("Save")}</button></FormFooter>}
    </div>
  </>;
}
