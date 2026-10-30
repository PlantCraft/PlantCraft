/** A person's page (/people/<username>, /people/me): who they are, how to reach them, the actions
 * they own and, for themselves and the administrators, the apps they open and with which role.
 * Each person edits their own profile here. */
import { useCallback, useEffect, useState, type FormEvent, type ReactElement } from "react";
import { AlertTriangle, Bell, Building2, CalendarClock, ClipboardCheck, LoaderCircle, Mail, MapPin, Pencil, Phone, ShieldCheck, UserRound, Users } from "lucide-react";
import { accessApi, EMPTY_PROFILE } from "./accessApi";
import { groupsApi, priorityLabels, type NotificationPreferences, type Priority } from "./groupsApi";
import { Avatar, dayText, Go } from "./collab";
import { t } from "./i18n";
import { navigate } from "./nav";
import type { PersonCard, Profile } from "./types";
import { ProfileFields } from "./UsersAdmin";
import "./access.css";
import { MyAssistantTokens } from "./AssistantAccess";
import { Modal } from "./Modal";

const AFFILIATION: Record<string, string> = { internal: t("Internal"), external: t("External") };
const ROLE: Record<string, string> = { viewer: t("Viewer"), editor: t("Editor") };

export function PersonPage({ username }: { username: string }) {
  const [card, setCard] = useState<PersonCard | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const load = useCallback(() => (username === "me" ? accessApi.me() : accessApi.person(username)).then((value) => { setCard(value); setError(""); }).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load."))), [username]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>;
  if (!card) return <div className="module-state"><LoaderCircle className="spin" /></div>;
  const profile = card.profile;
  const facts: Array<[ReactElement, string, string | ReactElement]> = [];
  if (profile.unit) facts.push([<MapPin size={14} key="u" />, t("Unit or site"), profile.unit]);
  if (profile.affiliation || profile.organization) facts.push([<Building2 size={14} key="o" />, t("Organization"), [AFFILIATION[profile.affiliation], profile.organization].filter(Boolean).join(" · ")]);
  if (profile.email) facts.push([<Mail size={14} key="e" />, t("Email"), <a href={`mailto:${profile.email}`}>{profile.email}</a>]);
  if (profile.phone) facts.push([<Phone size={14} key="p" />, t("Phone"), <a href={`tel:${profile.phone.replace(/\s/g, "")}`}>{profile.phone}</a>]);
  return <>
    <div className="page-heading">
      <div className="pp-heading"><Avatar name={card.display_name} size="lg" /><div><span className="eyebrow"><UserRound size={14} /> {t("Person")}</span><h1>{card.display_name}</h1><p>{[profile.job_title, card.role].filter(Boolean).join(" · ") || `@${card.username}`}{card.active ? "" : ` · ${t("Deactivated")}`}</p></div></div>
      {card.is_me && <div className="heading-actions"><button className="button button-secondary" onClick={() => setEditing(true)}><Pencil size={15} /> {t("Edit my profile")}</button></div>}
    </div>
    <div className="pp-grid">
      <section className="panel">
        <h2 className="section-title">{t("Profile")}</h2>
        {facts.length ? <dl className="pp-facts">{facts.map(([icon, label, value]) => <div key={label}><dt>{icon} {label}</dt><dd>{value}</dd></div>)}</dl>
          : <p className="muted">{card.is_me ? t("Your profile is empty: add your job title, unit and how to reach you.") : t("No profile details yet.")}</p>}
        <h2 className="section-title"><Users size={15} /> {t("Groups")}</h2>
        {card.groups?.length ? <ul className="pp-apps">{card.groups.map((group) => <li key={group.group_id}><Go to={`/groups/${encodeURIComponent(group.group_id)}`}>{group.name}</Go><span className="ac-level ac-level-viewer">{group.coordinator ? `${group.kind_label} · ${t("Coordinator")}` : group.kind_label}</span></li>)}</ul> : <p className="muted">{card.is_me ? t("You are in no group yet; an administrator adds you.") : t("In no group.")}</p>}
        {card.apps && <>
          <h2 className="section-title"><ShieldCheck size={15} /> {t("Access")}</h2>
          <p className="muted pp-access">{card.access?.access_label}{card.is_me ? ` · ${t("only administrators change it")}` : ""}</p>
          {card.apps.length ? <ul className="pp-apps">{card.apps.map((app) => <li key={app.application_id}><span>{app.name}</span><span className={`ac-level ac-level-${app.role}`}>{ROLE[app.role] ?? app.role}</span></li>)}</ul> : <p className="muted">{t("No apps.")}</p>}
        </>}
      </section>
      <section className="panel">
        <h2 className="section-title"><ClipboardCheck size={15} /> {t("Open actions")}</h2>
        {card.actions.length ? <ul className="pp-actions">{card.actions.map((action) => <li key={action.action_id}>
          <Go to={`/actions/${action.action_id}`}><strong>{action.title}</strong></Go>
          <span className={`act-status act-status-${action.status}`}>{action.status_label}</span>
          {action.due_at && <span className={action.overdue ? "due-overdue" : "due"}><CalendarClock size={13} />{dayText(action.due_at)}</span>}
        </li>)}</ul> : <p className="muted">{t("Nothing open.")}</p>}
        <button type="button" className="as-link-button" onClick={() => navigate("/actions")}>{t("All actions")}</button>
        {card.is_me && <NotificationPanel />}
        {card.is_me && <MyAssistantTokens />}
      </section>
    </div>
    {editing && <MyProfileForm card={card} onClose={() => setEditing(false)} onSaved={(next) => { setCard(next); setEditing(false); }} />}
  </>;
}

/** How the apps' notifications reach me: always in Messages, by email if I want and from which priority. */
function NotificationPanel() {
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { groupsApi.preferences().then(setPrefs).catch(() => setPrefs(null)); }, []);
  if (!prefs) return null;
  async function save(next: { email: boolean; email_min_priority: Priority }) {
    setPrefs({ ...prefs!, ...next });
    try { setPrefs(await groupsApi.savePreferences(next)); setSaved(true); window.setTimeout(() => setSaved(false), 2000); } catch { /* the next load shows what is stored */ }
  }
  const labels = priorityLabels();
  return <div className="pp-notify">
    <h2 className="section-title"><Bell size={15} /> {t("Notifications")}</h2>
    <p className="muted">{t("The apps' notifications reach you in Messages.")}{prefs.email_ready ? "" : ` ${t("Email is not set up in this installation.")}`}</p>
    <label className="ac-check"><input type="checkbox" checked={prefs.email} disabled={!prefs.email_ready} onChange={(event) => void save({ email: event.target.checked, email_min_priority: prefs.email_min_priority })} /> {t("Also by email")}</label>
    <label className="pp-notify-min">{t("By email from priority")}<select value={prefs.email_min_priority} disabled={!prefs.email_ready || !prefs.email} onChange={(event) => void save({ email: prefs.email, email_min_priority: event.target.value as Priority })}>
      {(["critical", "high", "medium", "low"] as Priority[]).map((priority) => <option key={priority} value={priority}>{priority === "low" ? t("Low (everything)") : t("{priority} and above", { priority: labels[priority] })}</option>)}
    </select></label>
    {saved && <small className="muted">{t("Saved.")}</small>}
  </div>;
}

function MyProfileForm({ card, onClose, onSaved }: { card: PersonCard; onClose: () => void; onSaved: (card: PersonCard) => void }) {
  const [name, setName] = useState(card.display_name);
  const [sector, setSector] = useState(card.role);
  const [profile, setProfile] = useState<Profile>({ ...EMPTY_PROFILE, ...card.profile });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try { onSaved(await accessApi.saveMe({ display_name: name, role: sector, profile })); } catch (err) { setError(err instanceof Error ? err.message : t("Couldn't complete the operation.")); setBusy(false); }
  }
  return <Modal label={t("Edit my profile")} eyebrow={<><UserRound size={13} /> {t("Profile")}</>} title={t("Edit my profile")} description={t("Colleagues see it when they open your name. Your access is set by the administrators.")} onClose={onClose} className="ac-form">
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        <label>{t("Name")}<input required value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Sector")}<input value={sector} maxLength={120} placeholder={t("E.g. Operations, Process Engineering")} onChange={(event) => setSector(event.target.value)} /></label>
        <ProfileFields profile={profile} onChange={setProfile} />
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />} {t("Save")}</button></footer>
    </form>
  </Modal>;
}

export default PersonPage;
