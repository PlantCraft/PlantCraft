/** Setup › Corporate sign-in: people sign in with their company account, from Active Directory or
 * LDAP or through single sign-on (OpenID Connect), and the directory's groups become their access
 * here. Off by default; the installation's admin account always signs in with its own password
 * (docs/corporate-login.md). */
import { FormFooter, FormSection, Heading } from "@plantcraft/ui";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, Building2, CheckCircle2, FlaskConical, LoaderCircle, Plus, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { directoryApi, type DirectorySettings, type DirectorySettingsDraft, type GroupRule, type LdapPreset, type LdapSettings, type LdapTestReport, type MappedAccess, type OidcSettings, type OidcTestReport, type Secrets, type TestStep, type Unmatched } from "./directoryApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import type { AccessLevel } from "./types";
import "./access.css";
import "./collab.css";

function Link({ to, children }: { to: string; children: ReactNode }) {
  return <a href={to} onClick={(event) => { event.preventDefault(); navigate(to); }}>{children}</a>;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

const NO_SECRETS: Secrets = { ldap_bind_password: "", clear_ldap_bind_password: false, oidc_client_secret: "", clear_oidc_client_secret: false };

function levelLabel(level: AccessLevel | Unmatched): string {
  return { admin: t("Admin"), editor: t("Editor"), viewer: t("Viewer"), dashboards: t("Dashboards only"), deny: t("Refused: they cannot sign in") }[level];
}

export function draftOf(settings: DirectorySettings): DirectorySettingsDraft {
  const { ready: _l, has_bind_password: _b, ...ldap } = settings.ldap;
  const { ready: _o, redirect_uri: _r, has_client_secret: _c, ...oidc } = settings.oidc;
  return { ldap, oidc, rules: settings.rules, unmatched: settings.unmatched, session_hours: settings.session_hours, local_passwords: settings.local_passwords };
}

/** "Off", or which ways in are on, for the Setup tile and this page. */
export function corporateState(settings: Pick<DirectorySettings, "allowed" | "ldap" | "oidc">): string {
  if (!settings.allowed) return t("Turned off in this installation (PLANTCRAFT_CORPORATE_LOGIN=off)");
  const on = [settings.ldap.enabled && "LDAP", settings.oidc.enabled && "OIDC"].filter(Boolean);
  return on.length ? t("On: {methods}", { methods: on.join(" · ") }) : t("Off: people sign in with accounts created here");
}

function Steps({ steps }: { steps: TestStep[] }) {
  return <ul className="cl-steps">{steps.map((step, index) => <li key={index} className={step.ok ? "ok" : "bad"}>{step.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}<span><strong>{step.step}</strong>{step.detail && <small>{step.detail}</small>}</span></li>)}</ul>;
}

function AccessResult({ access, apps }: { access: MappedAccess | null | undefined; apps: { id: string; name: string }[] }) {
  if (access === undefined) return null;
  if (access === null) return <p className="cl-access bad">{t("This person could not sign in: they are in no group that has access, and people in no group are refused.")}</p>;
  const names = access.apps === null ? t("every app") : access.apps.map((id) => apps.find((app) => app.id === id)?.name ?? id).join(", ") || t("no app");
  return <p className="cl-access">{t("They would sign in as {level}, with {apps}.", { level: levelLabel(access.level), apps: names })}{access.groups.length ? ` ${t("Groups here: {groups}.", { groups: access.groups.join(", ") })}` : ""}</p>;
}

function Text({ label, value, onChange, placeholder, hint, span, mono }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; hint?: string; span?: boolean; mono?: boolean }) {
  return <label className={span ? "field-span" : undefined}>{label}<input className={mono ? "cl-mono" : undefined} value={value} placeholder={placeholder} spellCheck={false} onChange={(event) => onChange(event.target.value)} />{hint && <small className="muted">{hint}</small>}</label>;
}

/** The saved secret only goes to the server it was typed for (security audit 2026-10-22): when
 * the address or the account changes, the API asks for it again, and the page says so first. */
export function serverMoved(saved: readonly string[], draft: readonly string[]): boolean {
  const clean = (value: string) => value.trim().split(/\s+/).join(" ").replace(/\/+$/, "");
  return saved.some((value, index) => clean(value) !== clean(draft[index] ?? ""));
}

function Secret({ label, saved, moved, value, clear, onValue, onClear }: { label: string; saved: boolean; moved: boolean; value: string; clear: boolean; onValue: (value: string) => void; onClear: (clear: boolean) => void }) {
  const retype = saved && moved && !value && !clear;
  return <>
    <label>{label}<input type="password" value={value} autoComplete="new-password" aria-invalid={retype || undefined} placeholder={retype ? t("Type it again for the new server") : saved ? t("Saved: leave empty to keep it") : t("Paste it here")} onChange={(event) => { onValue(event.target.value); onClear(false); }} />
      {retype ? <small className="cl-retype"><AlertTriangle size={12} /> {t("The server changed: type the password again. The saved one is only ever sent to the server it was typed for.")}</small> : <small className="muted">{t("Kept beside the database, never shown again.")}</small>}</label>
    {saved && <label className="check"><input type="checkbox" checked={clear} onChange={(event) => { onClear(event.target.checked); onValue(""); }} /> {t("Remove the saved one")}</label>}
  </>;
}

function Certificate({ value, verify, onValue, onVerify }: { value: string; verify: boolean; onValue: (value: string) => void; onVerify: (verify: boolean) => void }) {
  return <>
    <label className="field-span">{t("Company CA certificate (optional)")}<textarea className="cl-mono" rows={3} value={value} spellCheck={false} placeholder="-----BEGIN CERTIFICATE-----" onChange={(event) => onValue(event.target.value)} /><small className="muted">{t("Only when the server's certificate comes from your company's own authority: paste its PEM text, the one IT hands out for internal sites.")}</small></label>
    <label className="check field-span"><input type="checkbox" checked={verify} onChange={(event) => onVerify(event.target.checked)} /> {t("Check the server's certificate (turn off only in a test: without it, anyone on the network could pose as the server)")}</label>
  </>;
}

function RuleRow({ rule, apps, groups, onChange, onRemove }: { rule: GroupRule; apps: DirectorySettings["apps"]; groups: DirectorySettings["groups"]; onChange: (rule: GroupRule) => void; onRemove: () => void }) {
  const allApps = rule.apps === null;
  const toggleApp = (id: string, on: boolean) => onChange({ ...rule, apps: on ? [...(rule.apps ?? []), id] : (rule.apps ?? []).filter((item) => item !== id) });
  const toggleGroup = (id: string, on: boolean) => onChange({ ...rule, groups: on ? [...rule.groups, id] : rule.groups.filter((item) => item !== id) });
  const setRole = (id: string, role: string) => {
    const roles = { ...rule.app_roles };
    if (role) roles[id] = role as "viewer" | "editor"; else delete roles[id];
    onChange({ ...rule, app_roles: roles });
  };
  return <div className="cl-rule">
    <div className="cl-rule-head">
      <label>{t("Group in the directory")}<input className="cl-mono" value={rule.match} placeholder="PC-Engineering" spellCheck={false} onChange={(event) => onChange({ ...rule, match: event.target.value })} /><small>{t("Its name (CN) or its full DN.")}</small></label>
      <label>{t("Access here")}<select value={rule.level} onChange={(event) => onChange({ ...rule, level: event.target.value as AccessLevel })}>
        {(["viewer", "editor", "dashboards", "admin"] as AccessLevel[]).map((level) => <option key={level} value={level}>{levelLabel(level)}</option>)}
      </select></label>
      <button type="button" className="button button-ghost button-icon cl-remove" title={t("Remove rule")} aria-label={t("Remove rule")} onClick={onRemove}><Trash2 /></button>
    </div>
    {rule.level !== "admin" && <fieldset className="cl-fieldset">
      <legend>{t("Apps")}</legend>
      <label className="check"><input type="checkbox" checked={allApps} onChange={(event) => onChange({ ...rule, apps: event.target.checked ? null : [] })} /> {t("Every app")}</label>
      <div className="cl-apps">{apps.map((app) => <div key={app.id} className="cl-app">
        <label className="check"><input type="checkbox" checked={allApps || (rule.apps ?? []).includes(app.id)} disabled={allApps} onChange={(event) => toggleApp(app.id, event.target.checked)} /> {app.name}</label>
        <select aria-label={t("Role in {app}", { app: app.name })} value={rule.app_roles[app.id] ?? ""} onChange={(event) => setRole(app.id, event.target.value)}>
          <option value="">{t("Role of the level")}</option>
          <option value="viewer">{t("Viewer")}</option>
          <option value="editor">{t("Editor")}</option>
        </select>
      </div>)}</div>
    </fieldset>}
    {groups.length > 0 && <fieldset className="cl-fieldset">
      <legend>{t("Member of these groups here")}</legend>
      <div className="cl-groups">{groups.map((group) => <label key={group.group_id} className="check"><input type="checkbox" checked={rule.groups.includes(group.group_id)} onChange={(event) => toggleGroup(group.group_id, event.target.checked)} /> {group.name}</label>)}</div>
    </fieldset>}
  </div>;
}

export function CorporateLoginPage() {
  const isAdmin = useIsAdmin();
  const [settings, setSettings] = useState<DirectorySettings | null>(null);
  const [draft, setDraft] = useState<DirectorySettingsDraft | null>(null);
  const [secrets, setSecrets] = useState<Secrets>(NO_SECRETS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tester, setTester] = useState({ username: "", password: "" });
  const [ldapTest, setLdapTest] = useState<LdapTestReport | null>(null);
  const [oidcTest, setOidcTest] = useState<OidcTestReport | null>(null);
  const [previewGroups, setPreviewGroups] = useState("");
  const [preview, setPreview] = useState<MappedAccess | null | undefined>(undefined);
  const take = (value: DirectorySettings) => { setSettings(value); setDraft(draftOf(value)); setSecrets(NO_SECRETS); };
  useEffect(() => { if (isAdmin) directoryApi.settings().then(take).catch((err) => setError(message(err))); }, [isAdmin]);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins set up corporate sign-in.")}</span></div>;

  const ldap = (change: Partial<LdapSettings>) => draft && setDraft({ ...draft, ldap: { ...draft.ldap, ...change } });
  const oidc = (change: Partial<OidcSettings>) => draft && setDraft({ ...draft, oidc: { ...draft.oidc, ...change } });
  const rules = (next: GroupRule[]) => draft && setDraft({ ...draft, rules: next });

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (draft) await run(async () => { take(await directoryApi.save(draft, secrets)); setNotice(t("Corporate sign-in saved.")); });
  }
  const usePreset = (preset: LdapPreset) => settings && ldap({ ...settings.presets[preset], preset });
  const redirect = draft?.oidc.public_url ? `${draft.oidc.public_url.replace(/\/+$/, "")}/api/sso/oidc/callback` : "";

  return <>
    <Heading eyebrow={<><Building2 size={14} /> {t("Administration")} · <Link to="/setup">{t("Settings")}</Link></>} title={t("Corporate sign-in")}
      detail={t("People sign in with their company account, from Active Directory or LDAP or through your single sign-on, instead of an account created here one by one. Their groups in the directory decide what they open here, and the account is created the first time they sign in.")} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {!draft && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {draft && settings && <form className="panel form-panel cl-form" onSubmit={submit}>
      <p className="muted cl-state">{corporateState(settings)}</p>
      {!settings.allowed && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("This installation turned corporate sign-in off (PLANTCRAFT_CORPORATE_LOGIN=off). The settings are kept but never used.")}</div>}
      {!settings.sign_in_enabled && <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("Sign-in is off in this installation (demo): corporate sign-in applies once sign-in is on.")}</div>}
      <div className="ac-notice"><ShieldCheck size={15} /> {settings.admin_account ? t("The installation's admin account ({account}) always signs in with its own password, so a directory that stops answering never locks you out.", { account: settings.admin_account }) : t("The installation's admin account always signs in with its own password, so a directory that stops answering never locks you out.")}</div>

      <FormSection id="cl-ldap" title={t("Active Directory or LDAP")} detail={t("People type their company username and password on the usual sign-in page. PlantCraft looks them up with a read-only service account, checks the password with the directory and reads their groups. Always encrypted: passwords never travel in clear.")}>
        <div className="form-grid">
          <label className="check field-span"><input type="checkbox" checked={draft.ldap.enabled} onChange={(event) => ldap({ enabled: event.target.checked })} /> {t("Sign in with the company directory")}</label>
          <label>{t("Kind of directory")}<select value={draft.ldap.preset} onChange={(event) => usePreset(event.target.value as LdapPreset)}>
            <option value="active_directory">Active Directory</option>
            <option value="openldap">OpenLDAP</option>
          </select><small className="muted">{t("Choosing one fills in the usual filters and attributes below.")}</small></label>
          <label>{t("Encryption")}<select value={draft.ldap.security} onChange={(event) => ldap({ security: event.target.value as LdapSettings["security"] })}>
            <option value="ldaps">{t("LDAPS (ldaps://, usually port 636)")}</option>
            <option value="starttls">{t("StartTLS (ldap://, usually port 389)")}</option>
          </select></label>
          <Text span mono label={t("Servers")} value={draft.ldap.url} placeholder={draft.ldap.security === "ldaps" ? "ldaps://dc1.company.local ldaps://dc2.company.local" : "ldap://dc1.company.local"} hint={t("One or more, separated by spaces: the next one is tried when the first does not answer.")} onChange={(url) => ldap({ url })} />
          <Text span mono label={t("Search base")} value={draft.ldap.base_dn} placeholder="DC=company,DC=local" hint={t("Where people are looked up, with everything under it.")} onChange={(base_dn) => ldap({ base_dn })} />
          <Text mono label={t("Service account (DN)")} value={draft.ldap.bind_dn} placeholder="CN=svc-processcraft,OU=Service,DC=company,DC=local" hint={t("A read-only account IT creates for PlantCraft.")} onChange={(bind_dn) => ldap({ bind_dn })} />
          <Secret label={t("Service account password")} saved={settings.ldap.has_bind_password} moved={serverMoved([settings.ldap.url, settings.ldap.bind_dn], [draft.ldap.url, draft.ldap.bind_dn])} value={secrets.ldap_bind_password} clear={secrets.clear_ldap_bind_password} onValue={(ldap_bind_password) => setSecrets({ ...secrets, ldap_bind_password })} onClear={(clear_ldap_bind_password) => setSecrets({ ...secrets, clear_ldap_bind_password })} />
          <Certificate value={draft.ldap.ca_certificate} verify={draft.ldap.verify_certificate} onValue={(ca_certificate) => ldap({ ca_certificate })} onVerify={(verify_certificate) => ldap({ verify_certificate })} />
          <details className="field-span cl-advanced">
            <summary>{t("Filters and attributes")}</summary>
            <div className="form-grid">
              <Text span mono label={t("User filter")} value={draft.ldap.user_filter} hint={t("{username} is replaced by what the person typed.")} onChange={(user_filter) => ldap({ user_filter })} />
              <Text mono label={t("Username attribute")} value={draft.ldap.username_attribute} hint={t("Their username here.")} onChange={(username_attribute) => ldap({ username_attribute })} />
              <Text mono label={t("Unique id attribute")} value={draft.ldap.id_attribute} hint={t("Stays the same when the person is renamed.")} onChange={(id_attribute) => ldap({ id_attribute })} />
              <label>{t("Groups from")}<select value={draft.ldap.group_mode} onChange={(event) => ldap({ group_mode: event.target.value as LdapSettings["group_mode"] })}>
                <option value="search">{t("A search for the groups they are a member of")}</option>
                <option value="memberof">{t("The person's memberOf attribute")}</option>
              </select></label>
              <Text mono label={t("Group search base (optional)")} value={draft.ldap.group_base_dn} hint={t("Empty: the search base above.")} onChange={(group_base_dn) => ldap({ group_base_dn })} />
              {draft.ldap.group_mode === "search" && <Text span mono label={t("Group filter")} value={draft.ldap.group_filter} hint={t("{dn} is the person's DN, {username} their username.")} onChange={(group_filter) => ldap({ group_filter })} />}
              <Text mono label={t("Name")} value={draft.ldap.display_name_attribute} onChange={(display_name_attribute) => ldap({ display_name_attribute })} />
              <Text mono label={t("Email")} value={draft.ldap.email_attribute} onChange={(email_attribute) => ldap({ email_attribute })} />
              <Text mono label={t("Job title")} value={draft.ldap.job_title_attribute} onChange={(job_title_attribute) => ldap({ job_title_attribute })} />
              <Text mono label={t("Sector or team")} value={draft.ldap.department_attribute} onChange={(department_attribute) => ldap({ department_attribute })} />
              <Text mono label={t("Phone")} value={draft.ldap.phone_attribute} onChange={(phone_attribute) => ldap({ phone_attribute })} />
              <Text mono label={t("Organization")} value={draft.ldap.organization_attribute} onChange={(organization_attribute) => ldap({ organization_attribute })} />
              <Text mono label={t("Unit")} value={draft.ldap.unit_attribute} onChange={(unit_attribute) => ldap({ unit_attribute })} />
            </div>
          </details>
        </div>
        <div className="cl-test">
          <h3>{t("Test")}</h3>
          <p className="muted">{t("With the settings on this page, saved or not. Without a username it only checks the connection and the service account; with one, it also finds the person, reads their groups and shows the access they would get. With their password, it checks it too.")}</p>
          <div className="form-grid">
            <label>{t("Username (optional)")}<input value={tester.username} autoComplete="off" onChange={(event) => setTester({ ...tester, username: event.target.value })} /></label>
            <label>{t("Their password (optional)")}<input type="password" value={tester.password} autoComplete="new-password" onChange={(event) => setTester({ ...tester, password: event.target.value })} /></label>
          </div>
          <button type="button" className="button button-secondary" disabled={busy} onClick={() => void run(async () => { setLdapTest(null); setLdapTest(await directoryApi.testLdap(draft, secrets, tester.username, tester.password)); })}><FlaskConical /> {t("Test the directory")}</button>
          {ldapTest && <div className={`sp-test-result${ldapTest.ok ? " ok" : ""}`}><Steps steps={ldapTest.steps} />{ldapTest.person && <p>{t("{name}: {groups}", { name: ldapTest.person.display_name || ldapTest.person.username, groups: ldapTest.person.groups.join(", ") || t("no groups") })}</p>}<AccessResult access={ldapTest.access} apps={settings.apps} /></div>}
        </div>
      </FormSection>

      <FormSection id="cl-oidc" title={t("Single sign-on (OpenID Connect)")} detail={t("The sign-in page shows a button that takes people to your company's sign-in page (Keycloak, Microsoft Entra ID, AD FS, Okta and others) and back, already signed in. PlantCraft never sees their password.")}>
        <div className="form-grid">
          <label className="check field-span"><input type="checkbox" checked={draft.oidc.enabled} onChange={(event) => oidc({ enabled: event.target.checked })} /> {t("Sign in with single sign-on")}</label>
          <Text label={t("Button")} value={draft.oidc.label} hint={t("The page shows \"Sign in with {label}\".", { label: draft.oidc.label || t("company account") })} onChange={(label) => oidc({ label })} />
          <Text mono label={t("Provider address (issuer)")} value={draft.oidc.issuer} placeholder="https://sso.company.local/realms/plant" hint={t("From the provider's settings; PlantCraft reads the rest from it.")} onChange={(issuer) => oidc({ issuer })} />
          <Text mono label={t("Client id")} value={draft.oidc.client_id} placeholder="processcraft" onChange={(client_id) => oidc({ client_id })} />
          <Secret label={t("Client secret")} saved={settings.oidc.has_client_secret} moved={serverMoved([settings.oidc.issuer, settings.oidc.client_id], [draft.oidc.issuer, draft.oidc.client_id])} value={secrets.oidc_client_secret} clear={secrets.clear_oidc_client_secret} onValue={(oidc_client_secret) => setSecrets({ ...secrets, oidc_client_secret })} onClear={(clear_oidc_client_secret) => setSecrets({ ...secrets, clear_oidc_client_secret })} />
          <Text span mono label={t("PlantCraft's address")} value={draft.oidc.public_url} placeholder={window.location.origin} hint={t("As people open it. Register this return address with the provider: {address}", { address: redirect || `${window.location.origin}/api/sso/oidc/callback` })} onChange={(public_url) => oidc({ public_url })} />
          {!draft.oidc.public_url && <div className="field-span"><button type="button" className="button button-secondary" onClick={() => oidc({ public_url: window.location.origin })}>{t("Use this address ({address})", { address: window.location.origin })}</button></div>}
          <Certificate value={draft.oidc.ca_certificate} verify={draft.oidc.verify_certificate} onValue={(ca_certificate) => oidc({ ca_certificate })} onVerify={(verify_certificate) => oidc({ verify_certificate })} />
          <details className="field-span cl-advanced">
            <summary>{t("Scopes and claims")}</summary>
            <div className="form-grid">
              <Text span mono label={t("Scopes")} value={draft.oidc.scopes} hint={t("Add the scope your provider needs for groups, if any.")} onChange={(scopes) => oidc({ scopes })} />
              <Text mono label={t("Username claim")} value={draft.oidc.username_claim} onChange={(username_claim) => oidc({ username_claim })} />
              <Text mono label={t("Groups claim")} value={draft.oidc.groups_claim} hint={t("A dotted path reads nested claims: realm_access.roles")} onChange={(groups_claim) => oidc({ groups_claim })} />
              <Text mono label={t("Name claim")} value={draft.oidc.display_name_claim} onChange={(display_name_claim) => oidc({ display_name_claim })} />
              <Text mono label={t("Email claim")} value={draft.oidc.email_claim} onChange={(email_claim) => oidc({ email_claim })} />
              <Text mono label={t("Job title claim (optional)")} value={draft.oidc.job_title_claim} onChange={(job_title_claim) => oidc({ job_title_claim })} />
              <Text mono label={t("Sector claim (optional)")} value={draft.oidc.department_claim} onChange={(department_claim) => oidc({ department_claim })} />
            </div>
          </details>
        </div>
        <div className="cl-test">
          <button type="button" className="button button-secondary" disabled={busy} onClick={() => void run(async () => { setOidcTest(null); setOidcTest(await directoryApi.testOidc(draft, secrets)); })}><FlaskConical /> {t("Test the provider")}</button>
          {oidcTest && <div className={`sp-test-result${oidcTest.ok ? " ok" : ""}`}><Steps steps={oidcTest.steps} />{oidcTest.ok && <p>{t("Reached. To try a real sign-in, save, sign out and use the button on the sign-in page.")}</p>}</div>}
        </div>
      </FormSection>

      <FormSection id="cl-rules" title={t("Access from the directory's groups")} detail={<><p>{t("Each rule gives the people of one directory group an access level here, the apps they open with their role in each, and the groups here they belong to. Someone in several groups gets the most of each.")}</p><p>{t("The directory is the source of truth: every sign-in brings their access and these groups up to date, so a change made here by hand lasts until their next sign-in.")}</p></>}>
        {draft.rules.length === 0 && <p className="muted">{t("No rules yet.")}</p>}
        {draft.rules.map((rule, index) => <RuleRow key={index} rule={rule} apps={settings.apps} groups={settings.groups} onChange={(next) => rules(draft.rules.map((item, at) => (at === index ? next : item)))} onRemove={() => rules(draft.rules.filter((_item, at) => at !== index))} />)}
        <div><button type="button" className="button button-secondary" onClick={() => rules([...draft.rules, { match: "", level: "viewer", apps: null, app_roles: {}, groups: [] }])}><Plus /> {t("Add rule")}</button></div>
        <div className="form-grid">
          <label>{t("People in none of these groups")}<select value={draft.unmatched} onChange={(event) => setDraft({ ...draft, unmatched: event.target.value as Unmatched })}>
            {(["deny", "dashboards", "viewer", "editor"] as Unmatched[]).map((level) => <option key={level} value={level}>{levelLabel(level)}</option>)}
          </select></label>
          <label>{t("Sign in again after (hours)")}<input type="number" min={1} max={168} value={draft.session_hours} onChange={(event) => setDraft({ ...draft, session_hours: Number(event.target.value) || 12 })} /><small className="muted">{t("So someone turned off in the directory loses access here within this time.")}</small></label>
          <label className="check field-span"><input type="checkbox" checked={draft.local_passwords} onChange={(event) => setDraft({ ...draft, local_passwords: event.target.checked })} /> {t("People created here, outside the directory, still sign in with their password (turn off to allow only company accounts, and the admin account)")}</label>
        </div>
        <div className="cl-test">
          <h3>{t("Check the rules")}</h3>
          <div className="form-grid">
            <label className="field-span">{t("Directory groups of someone, separated by commas")}<input className="cl-mono" value={previewGroups} placeholder="PC-Engineering, PC-Operators" onChange={(event) => setPreviewGroups(event.target.value)} /></label>
          </div>
          <button type="button" className="button button-secondary" disabled={busy} onClick={() => void run(async () => { setPreview((await directoryApi.preview(draft, previewGroups.split(",").map((item) => item.trim()).filter(Boolean))).access); })}><FlaskConical /> {t("Check")}</button>
          <AccessResult access={preview} apps={settings.apps} />
        </div>
      </FormSection>
      <FormFooter sticky note={t("Tests use the settings on this page, saved or not.")}><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button></FormFooter>
    </form>}
  </>;
}

export default CorporateLoginPage;
