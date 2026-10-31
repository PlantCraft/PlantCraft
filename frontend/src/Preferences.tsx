/** Each person's Preferences (user menu › Preferences): the language and where times are shown;
 * and Setup › Installation (administrators): the installation's time zone, the "Local time" of
 * every screen and of schedules saved at local time (owner, 2026-10-24/25). */
import { cityName, deviceTimeZone, FormFooter, FormSection, Heading, offsetLabel, plantTimeZone, setTimeZoneMode, timeZoneLabel, timeZoneMode, TimeZoneSelect, type TimeZoneMode } from "@plantcraft/ui";
import { AlertTriangle, Clock, Languages, LoaderCircle, Lock } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { language, LANGUAGES, setLanguage, t, type Language } from "./i18n";
import { preferencesApi, type InstallationSettings, type Preferences } from "./preferencesApi";
import { useIsAdmin } from "./session";

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function zoneChoices(): Array<{ value: TimeZoneMode; title: string; detail: string }> {
  const plant = plantTimeZone(), device = deviceTimeZone();
  const choices: Array<{ value: TimeZoneMode; title: string; detail: string }> = [
    { value: "plant", title: timeZoneLabel("local", t("Local time")), detail: t("The installation's clock, the same for everyone. Recommended.") },
    { value: "utc", title: "UTC", detail: t("Coordinated Universal Time, for comparing with other sites.") },
  ];
  // Only when this device is somewhere else: otherwise it is the same as Local time.
  if (offsetLabel(device) !== offsetLabel(plant) || timeZoneMode() === "device") {
    choices.push({ value: "device", title: t("This device · {zone}", { zone: `${cityName(device)} (${offsetLabel(device)})` }), detail: t("The clock of the computer or phone you are using now.") });
  }
  return choices;
}

export function PreferencesPage() {
  const [saved, setSaved] = useState<Preferences | null>(null);
  const [zone, setZone] = useState<TimeZoneMode>(timeZoneMode());
  const [lang, setLang] = useState<string>(language);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    preferencesApi.get().then((value) => { setSaved(value); setZone(value.time_zone); setLang(value.language ?? language); }).catch((err) => setError(message(err)));
  }, []);
  const changed = saved !== null && (zone !== saved.time_zone || lang !== (saved.language ?? language));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const value = await preferencesApi.save({ time_zone: zone, language: lang });
      setSaved(value);
      // Every time on every page follows: the page reloads once.
      if (lang !== language) setLanguage(lang as Language);
      setTimeZoneMode(value.time_zone, true);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }
  return <>
    <Heading title={t("Preferences")} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!saved && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {saved && <form className="panel form-panel" onSubmit={(event) => void submit(event)}>
      <FormSection id="pref-time" icon={<Clock size={17} />} title={t("Times")} detail={t("Every time is stored in UTC and shown in the clock you choose here: on every page, chart and form of the suite. It is also the first choice where a form asks for a time zone.")}>
        <div className="pref-choices" role="radiogroup" aria-label={t("Times")}>
          {zoneChoices().map((choice) => (
            <label key={choice.value} className={`pref-choice${zone === choice.value ? " pref-on" : ""}`}>
              <input type="radio" name="time_zone" value={choice.value} checked={zone === choice.value} onChange={() => setZone(choice.value)} />
              <span><strong>{choice.title}</strong><small>{choice.detail}</small></span>
            </label>
          ))}
        </div>
      </FormSection>
      <FormSection id="pref-language" icon={<Languages size={17} />} title={t("Language")} detail={LANGUAGES.length < 2 ? t("The suite is in English for now; Portuguese comes back once the screens are final.") : t("The language of every app of the suite.")}>
        <div className="form-grid">
          <label>{t("Language")}
            <select value={lang} disabled={LANGUAGES.length < 2} onChange={(event) => setLang(event.target.value)}>
              {LANGUAGES.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
            </select>
          </label>
        </div>
      </FormSection>
      <FormFooter note={t("Saved for your account: it follows you to any computer or phone.")}>
        {changed && <button type="button" className="button button-secondary" onClick={() => { setZone(saved.time_zone); setLang(saved.language ?? language); }}>{t("Cancel")}</button>}
        <button className="button button-primary" disabled={busy || !changed}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button>
      </FormFooter>
    </form>}
  </>;
}

/** Setup › Installation: the installation's own time zone. */
export function InstallationSettingsPage() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<InstallationSettings | null>(null);
  const [zone, setZone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { preferencesApi.installation().then((value) => { setData(value); setZone(value.time_zone); }).catch((err) => setError(message(err))); }, []);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins change the installation's settings.")}</span></div>;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await preferencesApi.saveInstallation(zone);
      setData(value);
      setZone(value.time_zone);
      setNotice(t("Saved. Every app follows within a minute; open pages show it after a reload."));
    } catch (err) {
      setError(message(err));
    }
    setBusy(false);
  }
  const clock = data ? data.now.slice(11, 16) : "";
  return <>
    <Heading title={t("Installation")} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice" role="status">{notice}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {data && <form className="panel form-panel" onSubmit={(event) => void submit(event)}>
      <FormSection id="inst-zone" icon={<Clock size={17} />} title={t("Time zone")} detail={<>
        <p>{t("Where the plant is: the Local time of every screen, where a day and a shift begin, and the clock of the schedules saved at local time (backups, Analytics, Alarms).")}</p>
        <p>{data.locked
          ? t("Set by the installation: change it on the server, in the installation file.")
          : data.chosen
            ? t("Chosen by {who}. The installer had set {zone}.", { who: data.updated_by ?? "", zone: data.installed_time_zone })
            : t("Set by the installer from the server's clock. Change it if the server keeps another time.")}</p>
      </>}>
        <div className="form-grid">
          <label>{t("Time zone")}{data.locked ? <input value={data.time_zone} disabled readOnly /> : <TimeZoneSelect withLocal={false} value={zone} onChange={setZone} />}</label>
        </div>
        <p className="muted">{t("Now at the plant: {time} ({zone})", { time: clock, zone: offsetLabel(data.time_zone) })}</p>
      </FormSection>
      {data.installation_file?.present && <FormSection id="inst-file" icon={<Lock size={17} />} title={t("Set by the installation")} detail={<>
        <p>{t("Decided before the suite was installed, in {path} on the server. No account here can change these: edit the file as root and run install.sh again.", { path: data.installation_file.path })}</p>
        {data.installation_file.sha256 && <p className="muted">{t("File fingerprint (SHA-256): {sha}", { sha: data.installation_file.sha256.slice(0, 16) + "…" })}</p>}
      </>}>
        <table className="table"><tbody>
          {data.installation_file.entries.map((entry) => <tr key={entry.key}><th scope="row">{t(entry.label)}</th><td>{entry.value || t("(default)")}</td></tr>)}
        </tbody></table>
      </FormSection>}
      <FormFooter note={t("Stored times do not change: they are in UTC. Only how they are shown and when local schedules run.")}>
        {zone !== data.time_zone && <button type="button" className="button button-secondary" onClick={() => setZone(data.time_zone)}>{t("Cancel")}</button>}
        <button className="button button-primary" disabled={busy || zone === data.time_zone}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button>
      </FormFooter>
    </form>}
  </>;
}
