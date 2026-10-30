/** Setup › Desk (administrators): whether Desk shows its Team page (hidden by default, owner
 * 2026-10-25), and whether people may add calendars by link (Outlook,
 * Google, any .ics address), and from which servers. Off by default: the suite runs offline
 * and only reads the servers named here. Importing an .ics file always works. */
import { FormSection, Heading } from "@plantcraft/ui";
import { useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, CalendarDays, LoaderCircle, ShieldCheck } from "lucide-react";
import { errorText } from "./collab";
import { deskApi } from "./deskApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import "./access.css";

export function CalendarSettingsPage() {
  const [enabled, setEnabled] = useState(false);
  const [hosts, setHosts] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [team, setTeam] = useState<boolean | null>(null);
  useEffect(() => { deskApi.teamPage().then((value) => setTeam(value.enabled)).catch(() => setTeam(false)); }, []);
  async function saveTeam(value: boolean) {
    setError("");
    setTeam(value); // the switch moves at once; back if the save fails
    try {
      const saved = await deskApi.saveTeamPage(value);
      setTeam(saved.enabled);
      setNotice(saved.enabled ? t("Desk shows the Team page.") : t("Desk no longer shows the Team page."));
    } catch (err) {
      setTeam(!value);
      setError(errorText(err));
    }
  }
  useEffect(() => { deskApi.settings().then((value) => { setEnabled(value.enabled); setHosts(value.hosts.join("\n")); setLoaded(true); }).catch((err) => setError(errorText(err))); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = await deskApi.saveSettings(enabled, hosts.split(/[\s,]+/).map((host) => host.trim()).filter(Boolean));
      setEnabled(saved.enabled);
      setHosts(saved.hosts.join("\n"));
      setNotice(t("Calendar settings saved."));
    } catch (err) {
      setError(errorText(err));
    }
    setBusy(false);
  }
  return <>
    <Heading eyebrow={<><CalendarDays size={14} /> {t("Administration")} · <a href="/setup" onClick={(event) => { event.preventDefault(); navigate("/setup"); }}>{t("Settings")}</a></>} title={t("Desk")} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {!loaded && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {team !== null && <section className="panel form-panel">
      <FormSection id="dk-team" title={t("Team page")} detail={t("A page with how each of the person's groups is doing today: its people, board, week and handovers. Hidden until you show it.")}>
        <label className="check"><input type="checkbox" checked={team} onChange={(event) => void saveTeam(event.target.checked)} /> {t("Show the Team page in Desk")}</label>
      </FormSection>
    </section>}
    {loaded && <section className="panel form-panel">
      <form onSubmit={(event) => void submit(event)}>
        <FormSection id="dk-links" title={t("Calendar links")} detail={t("In Desk, each person can show other calendars beside their actions. Importing an .ics file always works; reading one by its link needs the suite to reach that server. Only these servers are read, over https, every 15 minutes, at most 2 MB each. Addresses inside your network are refused. Leave it off to keep the suite fully offline.")}>
        <div className="form-grid">
          <label className="check field-span"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> {t("Let people add calendars by link")}</label>
          <label className="field-span">{t("Servers allowed, one per line")}<textarea id="dk-hosts" rows={4} value={hosts} placeholder={"outlook.office365.com\ncalendar.google.com"} onChange={(event) => setHosts(event.target.value)} /></label>
        </div>
        <div><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button></div>
        </FormSection>
      </form>
    </section>}
  </>;
}

export default CalendarSettingsPage;
