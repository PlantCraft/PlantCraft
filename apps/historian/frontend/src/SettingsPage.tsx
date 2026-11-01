import { NextSteps } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href, navigate } from "./nav";
import { forecastLine } from "./levels";
import { formatBytes } from "./format";
import type { Forecast, Me, RetentionLevel, Settings } from "./types";
import { ErrorBox, FormFooter, FormSection, Heading, Link, Loading } from "./ui";

const FIELDS: { key: keyof Settings; label: string; help: string; step: string }[] = [
  { key: "retention_days", label: "Raw values (days)", help: "Archived values older than this are deleted, unless a source or a signal sets its own.", step: "1" },
  { key: "hourly_retention_days", label: "Hourly rollups (days)", help: "Each hour's mean, lowest and highest value, kept after the raw values are gone: trends of weeks and months still read. 0 keeps them forever.", step: "1" },
  { key: "daily_retention_days", label: "Daily rollups (days)", help: "Each day's mean, lowest and highest value: trends of years. 0 keeps them forever.", step: "1" },
  { key: "monthly_retention_days", label: "Monthly rollups (days)", help: "Each month's mean, lowest and highest value. 0 keeps them forever.", step: "1" },
  { key: "default_scan_seconds", label: "Scan period (s)", help: "How often a signal is read, unless its source or the signal sets its own.", step: "0.1" },
  { key: "default_deviation_percent", label: "Deviation (% of span)", help: "Compression of a signal with a known range, unless its source or the signal sets its own: the rebuilt signal never strays more than this from a value read.", step: "0.01" },
  { key: "default_exception_percent", label: "Exception (% of span)", help: "Before the compression, a value within this of the last one passed on is taken as that value: noise smaller than it is never archived. 0 turns it off.", step: "0.01" },
  { key: "default_max_seconds", label: "Longest interval between archived values (s)", help: "A flat signal is still archived this often, unless its source or the signal sets its own.", step: "1" },
];

const SECTIONS: { title: string; detail: string; keys: (keyof Settings)[] }[] = [
  { title: "Retention", detail: "How long archived values and their hourly, daily and monthly rollups are kept. A rollup is kept at least as long as the raw values and the finer rollups.", keys: ["retention_days", "hourly_retention_days", "daily_retention_days", "monthly_retention_days"] },
  { title: "Collection and compression", detail: "How often signals are read and how much of what is read is archived.", keys: ["default_scan_seconds", "default_exception_percent", "default_deviation_percent", "default_max_seconds"] },
];

/** Settings: one tile per group, as PlantCraft's Setup and every app. */
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
  const [levels, setLevels] = useState<RetentionLevel[] | null>(null);
  useEffect(() => {
    api.retention().then(setLevels).catch(() => setLevels(null));
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
      api.retention().then(setLevels).catch(() => setLevels(null));
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
    {levels && <RetentionDisk levels={levels} />}
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

const LEVEL_NAMES: Record<RetentionLevel["level"], string> = { raw: "Raw values", hour: "Hourly rollups", day: "Daily rollups", month: "Monthly rollups" };

/** The disk each retention takes (H9): now, and once every signal keeps its full retention. */
export function RetentionDisk({ levels }: { levels: RetentionLevel[] }) {
  return <div className="panel">
    <h2>{t("Disk by retention")}</h2>
    <div className="table-scroll"><table className="table compact">
      <thead><tr><th>{t("Kept")}</th><th>{t("Retention")}</th><th className="num">{t("On disk now")}</th><th className="num">{t("At full retention")}</th></tr></thead>
      <tbody>{levels.map((item) => <tr key={item.level}>
        <td>{t(LEVEL_NAMES[item.level])}</td>
        <td>{item.days > 0 ? t("{days} days", { days: item.days }) : t("Forever")}</td>
        <td className="num">{formatBytes(item.now)}</td>
        <td className="num">{item.per_year ? t("{size} a year", { size: formatBytes(item.full) }) : formatBytes(item.full)}</td>
      </tr>)}</tbody>
    </table></div>
    <small>{t("At the values archived in the last 24 h. A signal or a source with its own retention counts with it; a rollup is kept at least as long as the raw values.")}</small>
  </div>;
}
