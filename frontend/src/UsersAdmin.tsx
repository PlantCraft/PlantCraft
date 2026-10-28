/** Administration of people: access level, applications, password and whether they are active. */
import { AlertTriangle, KeyRound, LoaderCircle, Pencil, Plus, Power, ShieldCheck, UserRound, Users } from "lucide-react";
import { DataTable } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { accessApi, EMPTY_PROFILE, type UserDraft } from "./accessApi";
import { AssetScopeField } from "./AssetScopeField";
import { PersonLink } from "./collab";
import { t } from "./i18n";
import { useAdminView } from "./session";
import type { AccessLevel, AppRole, Profile, UserAccount, UserAccounts } from "./types";
import { UserTabs } from "./Specialists";
import "./access.css";
import { Modal } from "./Modal";

/** What each level means, in the words the administrator chooses by. */
const LEVEL_HINTS: Record<AccessLevel, string> = {
  admin: t("Everything, including people, data sources and app keys."),
  editor: t("Engineering: changes the plant data in PlantCraft and edits in the apps."),
  viewer: t("Sees the plant data and opens their apps read-only; changes nothing."),
  dashboards: t("Dashboards only: for control-room screens (View); no plant data in PlantCraft."),
};

const ROLE_LABELS: Record<AppRole, string> = { viewer: t("Viewer"), editor: t("Editor") };
const PROFILE_FIELDS: Array<{ key: Exclude<keyof Profile, "affiliation">; label: string; placeholder: string; type?: string }> = [
  { key: "job_title", label: t("Job title"), placeholder: t("E.g. Process engineer") },
  { key: "unit", label: t("Unit or site"), placeholder: t("E.g. U-200, Riverbend") },
  { key: "email", label: t("Email"), placeholder: "name@company.com", type: "email" },
  { key: "phone", label: t("Phone"), placeholder: "+55 11 5555-0000", type: "tel" },
];

/** The profile's fields: shared by the administrators' form and each person's own. */
export function ProfileFields({ profile, onChange }: { profile: Profile; onChange: (profile: Profile) => void }) {
  return <>
    {PROFILE_FIELDS.map((field) => <label key={field.key}>{field.label}<input type={field.type ?? "text"} value={profile[field.key]} maxLength={field.key === "email" ? 200 : field.key === "phone" ? 40 : 120} placeholder={field.placeholder} onChange={(event) => onChange({ ...profile, [field.key]: event.target.value })} /></label>)}
    <label>{t("Internal or external")}<select value={profile.affiliation} onChange={(event) => onChange({ ...profile, affiliation: event.target.value as Profile["affiliation"] })}><option value="">—</option><option value="internal">{t("Internal (staff)")}</option><option value="external">{t("External (contractor, partner)")}</option></select></label>
    <label>{t("Organization")}<input value={profile.organization} maxLength={120} placeholder={profile.affiliation === "external" ? t("The company they work for") : t("E.g. the department")} onChange={(event) => onChange({ ...profile, organization: event.target.value })} /></label>
  </>;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

export function UsersPage() {
  const isAdmin = useAdminView();
  const [data, setData] = useState<UserAccounts | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<UserAccount | "new" | null>(null);
  const [password, setPassword] = useState<UserAccount | null>(null);
  const [notice, setNotice] = useState("");
  const load = useCallback(() => accessApi.accounts().then(setData).catch((err) => setError(message(err))), []);
  useEffect(() => { if (isAdmin) void load(); }, [isAdmin, load]);

  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins manage users.")}</span></div>;
  const appName = (id: string) => data?.applications.find((app) => app.application_id === id)?.name ?? id;

  async function toggle(user: UserAccount) {
    const off = user.active;
    if (off && !window.confirm(t("Deactivate {name}? They will no longer be able to sign in; their history is kept.", { name: user.display_name }))) return;
    try {
      await accessApi.updateUser(user.username, { display_name: user.display_name, role: user.role, access_level: user.access_level, applications: user.applications, active: !off });
      setNotice(off ? t("{name} was deactivated.", { name: user.display_name }) : t("{name} was reactivated.", { name: user.display_name }));
      await load();
    } catch (err) { setError(message(err)); }
  }

  return <>
    <div className="page-heading">
      <div><span className="eyebrow"><Users size={14} /> {t("Administration")}</span><h1>{t("People")}</h1><p>{t("Who signs in to the suite, what they can do and which apps they can open.")}</p></div>
      <div className="heading-actions"><button className="button button-primary" onClick={() => setEditing("new")}><Plus size={16} /> {t("New user")}</button></div>
    </div>
    <UserTabs current="people" />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {data && !data.sign_in && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("Sign-in is off in this installation (demo): anyone can switch users from the menu. Access levels apply to whoever is selected; passwords only take effect once sign-in is on.")}</div>}
    <section className="ac-levels" aria-label={t("Access levels")}>
      {(data?.levels ?? []).map((level) => <article key={level.id}><span className={`ac-level ac-level-${level.id}`}>{level.label}</span><p>{LEVEL_HINTS[level.id]}</p></article>)}
    </section>
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading users…")}</span></div>}
    {data && <section className="panel ac-users" data-tour="users">
      <DataTable rows={data.users} rowKey={(user) => user.username} label={t("People")} rowClassName={(user) => (user.active ? undefined : "ac-inactive")}
        searchText={(user) => `${user.display_name} ${user.username} ${user.role} ${user.profile?.job_title ?? ""} ${user.profile?.unit ?? ""}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "person", descending: false }}
        columns={[
          { key: "person", label: t("Person"), sort: (user) => user.display_name, render: (user) => <span className="ac-person"><span className="avatar">{initials(user.display_name)}</span><span><strong><PersonLink username={user.username} name={user.display_name} /></strong><small>{user.profile?.job_title || `@${user.username}`}</small></span></span> },
          { key: "role", label: t("Sector"), sort: (user) => user.role, filter: { value: (user) => user.role }, render: (user) => user.role || "—" },
          { key: "access", label: t("Access"), sort: (user) => user.access_label, filter: { value: (user) => user.access_label }, render: (user) => <span className={`ac-level ac-level-${user.access_level}`}>{user.access_label}</span> },
          { key: "apps", label: t("Apps"), render: (user) => <>{user.access_level === "admin" || user.applications === null ? t("All") : user.applications.length ? user.applications.map(appName).join(", ") : t("None")}{user.access_level !== "admin" && Object.keys(user.app_roles ?? {}).length > 0 && <small className="ac-app-roles">{Object.entries(user.app_roles ?? {}).map(([id, role]) => `${appName(id)}: ${ROLE_LABELS[role]}`).join(" · ")}</small>}</> },
          { key: "plant", label: t("Plant"), filter: { value: (user) => (user.asset_roots == null ? t("Whole plant") : t("Limited")) }, render: (user) => (user.asset_roots == null ? t("Whole plant") : <span title={user.asset_roots.join(", ")}>{user.asset_roots.length === 1 ? t("1 asset and below") : t("{count} assets and below", { count: user.asset_roots.length })}</span>) },
          { key: "password", label: t("Password"), render: (user) => (user.environment_admin ? t("From the install file") : user.auth_source === "ldap" ? t("Company directory") : user.auth_source === "oidc" ? t("Single sign-on") : user.has_password ? t("Set") : <span className="muted">{t("No password")}</span>) },
          { key: "active", label: t("Account status"), sort: (user) => (user.active ? 0 : 1), filter: { value: (user) => (user.active ? t("Active") : t("Deactivated")) }, render: (user) => (user.active ? t("Active") : t("Deactivated")) },
          { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (user) => !user.environment_admin && <>
            <button className="icon-button" title={t("Edit")} aria-label={t("Edit {name}", { name: user.display_name })} onClick={() => setEditing(user)}><Pencil size={15} /></button>
            {(user.auth_source ?? "local") === "local" && <button className="icon-button" title={t("Reset password")} aria-label={t("Reset password for {name}", { name: user.display_name })} onClick={() => setPassword(user)}><KeyRound size={15} /></button>}
            <button className="icon-button" title={user.active ? t("Deactivate") : t("Reactivate")} aria-label={user.active ? t("Deactivate {name}", { name: user.display_name }) : t("Reactivate {name}", { name: user.display_name })} onClick={() => void toggle(user)}><Power size={15} /></button>
          </> },
        ]} />
    </section>}
    {editing && data && <UserForm data={data} user={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={(user, created) => { setEditing(null); setNotice(created ? t("{name} was created.", { name: user.display_name }) : t("{name} was updated.", { name: user.display_name })); void load(); }} />}
    {password && <PasswordForm user={password} onClose={() => setPassword(null)} onSaved={() => { setNotice(t("Password for {name} was reset. Their open sessions were ended.", { name: password.display_name })); setPassword(null); void load(); }} />}
  </>;
}

function Dialog({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: ReactNode }) {
  return <Modal label={title} eyebrow={<><UserRound size={13} /> {t("User")}</>} title={title} description={subtitle} onClose={onClose} className="ac-form">
    {children}
  </Modal>;
}

function UserForm({ data, user, onClose, onSaved }: { data: UserAccounts; user: UserAccount | null; onClose: () => void; onSaved: (user: UserAccount, created: boolean) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [draft, setDraft] = useState<UserDraft>({ display_name: user?.display_name ?? "", role: user?.role ?? "", access_level: user?.access_level ?? "viewer", applications: user?.applications ?? null, app_roles: user?.app_roles ?? {}, profile: { ...EMPTY_PROFILE, ...user?.profile }, groups: user?.groups ?? [], active: user?.active ?? true, asset_scope: user?.asset_scope ?? null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const all = draft.applications === null || draft.access_level === "admin";
  function toggleApp(id: string) {
    const current = draft.applications ?? data.applications.map((app) => app.application_id);
    setDraft({ ...draft, applications: current.includes(id) ? current.filter((item) => item !== id) : [...current, id] });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = { ...draft, applications: draft.access_level === "admin" ? null : draft.applications };
      const saved = user ? await accessApi.updateUser(user.username, payload) : await accessApi.createUser({ ...payload, username, password: password || undefined });
      onSaved(saved, !user);
    } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <Dialog title={user ? user.display_name : t("New user")} subtitle={user ? `@${user.username}` : t("The person signs in with the username and password set here.")} onClose={onClose}>
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        {!user && <label>{t("Username")}<input required value={username} autoComplete="off" placeholder={t("first.last")} pattern="[^\s@#]+" title={t("No spaces, @ or #")} onChange={(event) => setUsername(event.target.value.toLowerCase())} /></label>}
        <label>{t("Name")}<input required value={draft.display_name} maxLength={120} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></label>
        <label className={user ? "" : "field-span"}>{t("Sector")}<input value={draft.role} maxLength={120} placeholder={t("E.g. Operations, Process Engineering")} onChange={(event) => setDraft({ ...draft, role: event.target.value })} /></label>
        <ProfileFields profile={draft.profile ?? EMPTY_PROFILE} onChange={(profile) => setDraft({ ...draft, profile })} />
        {!user && <label className="field-span">{data.sign_in ? t("Initial password") : t("Initial password (applies once sign-in is on)")}<input type="password" value={password} minLength={8} autoComplete="new-password" placeholder={t("At least 8 characters")} onChange={(event) => setPassword(event.target.value)} /></label>}
        {(data.groups ?? []).length > 0 && <fieldset className="field-span ac-fieldset">
          <legend>{t("Groups")}</legend>
          <p className="ac-hint">{user?.auth_source && user.auth_source !== "local" ? t("The company directory also sets the groups at each sign-in.") : t("A person may be in several groups: an area, a discipline, a team.")}</p>
          <div className="ac-group-choice">{(data.groups ?? []).map((group) => { const on = (draft.groups ?? []).includes(group.group_id); return <label key={group.group_id} className="ac-check">
            <input type="checkbox" checked={on} onChange={() => setDraft({ ...draft, groups: on ? (draft.groups ?? []).filter((item) => item !== group.group_id) : [...(draft.groups ?? []), group.group_id] })} /> {group.name} <small className="muted">{group.kind_label}</small>
          </label>; })}</div>
        </fieldset>}
        <fieldset className="field-span ac-fieldset">
          <legend>{t("Access level")}</legend>
          <div className="ac-level-choice" role="radiogroup">
            {data.levels.map((level) => <label key={level.id} className={draft.access_level === level.id ? "active" : ""}>
              <input type="radio" name="access_level" checked={draft.access_level === level.id} onChange={() => setDraft({ ...draft, access_level: level.id })} />
              <span><strong>{level.label}</strong><small>{LEVEL_HINTS[level.id]}</small></span>
            </label>)}
          </div>
        </fieldset>
        <AssetScopeField legend={draft.access_level === "admin" ? t("Assets (admins see the whole plant)") : t("Assets they see")} hint={t("Only these assets, their signals and what apps publish about them. The assets of their limited groups add to these; with the whole plant here and no limited group, they see everything.")} disabled={draft.access_level === "admin"} value={draft.asset_scope ?? null} onChange={(asset_scope) => setDraft({ ...draft, asset_scope })} />
        <fieldset className="field-span ac-fieldset" disabled={draft.access_level === "admin"}>
          <legend>{draft.access_level === "admin" ? t("Apps (admins open all)") : t("Apps")}</legend>
          <label className="ac-check"><input type="checkbox" checked={all} onChange={() => setDraft({ ...draft, applications: all ? [] : null })} /> {t("All apps, including those installed later")}</label>
          <p className="ac-hint">{t("The role in each app follows the access level; choose another for an app where the person only reads or also edits.")}</p>
          {data.applications.map((app) => { const open = all || (draft.applications ?? []).includes(app.application_id); const role = draft.app_roles?.[app.application_id] ?? ""; return <div key={app.application_id} className="ac-app-row">
            <label className="ac-check"><input type="checkbox" disabled={all} checked={open} onChange={() => toggleApp(app.application_id)} /> {app.name}</label>
            <select aria-label={t("Role in {app}", { app: app.name })} value={role} disabled={!open || draft.access_level === "admin"} onChange={(event) => { const next = { ...(draft.app_roles ?? {}) }; if (event.target.value) next[app.application_id] = event.target.value as AppRole; else delete next[app.application_id]; setDraft({ ...draft, app_roles: next }); }}>
              <option value="">{t("As the level ({role})", { role: draft.access_level === "admin" || draft.access_level === "editor" ? ROLE_LABELS.editor : ROLE_LABELS.viewer })}</option>
              <option value="viewer">{ROLE_LABELS.viewer}</option>
              <option value="editor">{ROLE_LABELS.editor}</option>
            </select>
          </div>; })}
        </fieldset>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />} {user ? t("Save") : t("Create user")}</button></footer>
    </form>
  </Dialog>;
}

function PasswordForm({ user, onClose, onSaved }: { user: UserAccount; onClose: () => void; onSaved: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try { await accessApi.resetPassword(user.username, password); onSaved(); } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <Dialog title={t("Reset password")} subtitle={t("{name} (@{username}) will sign in with the new password; open sessions end.", { name: user.display_name, username: user.username })} onClose={onClose}>
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        <label className="field-span">{t("New password")}<input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />} {t("Reset")}</button></footer>
    </form>
  </Dialog>;
}

function initials(value: string) {
  const words = value.trim().split(/\s+/).filter(Boolean);
  return `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? words[0]?.[1] ?? ""}`.toUpperCase() || "?";
}

export default UsersPage;
