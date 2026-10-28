/** Setup › Email: the plant's own mail server (SMTP), so the apps' notifications can also reach
 * people by email. Off by default; the suite runs offline and never needs it: every notification
 * reaches Messages anyway (owner, 2026-10-22). */
import { FormSection, Heading } from "@plantcraft/ui";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, LoaderCircle, Mail, Send, ShieldCheck } from "lucide-react";
import { groupsApi, type MailDraft, type MailSettings } from "./groupsApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useIsAdmin } from "./session";
import "./access.css";

function Link({ to, children }: { to: string; children: ReactNode }) {
  return <a href={to} onClick={(event) => { event.preventDefault(); navigate(to); }}>{children}</a>;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function draftOf(settings: MailSettings): MailDraft {
  return { enabled: settings.enabled, host: settings.host, port: settings.port, security: settings.security, username: settings.username, password: "", clear_password: false, sender: settings.sender, verify_certificate: settings.verify_certificate };
}

/** Settings › Email in one line: "Off", "Not set up" or "<server> as <sender>". */
export function mailState(settings: Pick<MailSettings, "enabled" | "ready" | "host" | "sender">): string {
  if (!settings.enabled) return t("Off: notifications reach Messages only");
  if (!settings.ready) return t("Not set up: fill in the server and the sender");
  return t("{server} as {sender}", { server: settings.host, sender: settings.sender });
}

export function MailSettingsPage() {
  const isAdmin = useIsAdmin();
  const [settings, setSettings] = useState<MailSettings | null>(null);
  const [draft, setDraft] = useState<MailDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [to, setTo] = useState("");
  const [test, setTest] = useState<{ sent: boolean; to: string; error?: string } | null>(null);
  useEffect(() => { if (isAdmin) groupsApi.mail().then((value) => { setSettings(value); setDraft(draftOf(value)); }).catch((err) => setError(message(err))); }, [isAdmin]);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins set up email.")}</span></div>;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError("");
    try { const saved = await groupsApi.saveMail(draft); setSettings(saved); setDraft(draftOf(saved)); setNotice(t("Email settings saved.")); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  async function sendTest() {
    setBusy(true);
    setTest(null);
    try { setTest(await groupsApi.testMail(to)); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  const outbox = settings?.outbox;
  // The saved password only goes to the server it was typed for (security audit 2026-10-22).
  const retype = Boolean(settings?.has_password && draft && !draft.password && !draft.clear_password
    && (draft.host !== settings.host || draft.port !== settings.port || draft.username !== settings.username));
  return <>
    <Heading eyebrow={<><Mail size={14} /> {t("Administration")} · <Link to="/setup">{t("Settings")}</Link></>} title={t("Email")}
      detail={t("The apps' notifications (an alarm, an action assigned) always reach Messages. With your company's mail server set here, they can also go by email to the people who allow it in their profile.")} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {!draft && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {draft && settings && <section className="panel form-panel">
        <form onSubmit={submit}>
          <FormSection id="mail-server" title={t("Mail server (SMTP)")} detail={<><p>{mailState(settings)}</p><p>{t("The password is kept beside the database, never shown again. The suite connects only to this server; nothing goes to the internet.")}</p></>}>
          <div className="form-grid">
            <label className="check field-span"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /> {t("Send notifications by email too")}</label>
            <label>{t("Server")}<input value={draft.host} maxLength={253} placeholder="smtp.company.local" onChange={(event) => setDraft({ ...draft, host: event.target.value.trim() })} /></label>
            <label>{t("Security")}<select value={draft.security} onChange={(event) => { const security = event.target.value as MailDraft["security"]; setDraft({ ...draft, security, port: security === "tls" ? 465 : draft.port === 465 ? 587 : draft.port }); }}>
              <option value="starttls">{t("STARTTLS (usually port 587)")}</option>
              <option value="tls">{t("TLS (usually port 465)")}</option>
              <option value="none">{t("None (an internal relay, usually port 25)")}</option>
            </select></label>
            <label>{t("Port")}<input type="number" min={1} max={65535} value={draft.port} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) || 587 })} /></label>
            <label>{t("Sender address")}<input value={draft.sender} maxLength={200} placeholder="processcraft@company.local" onChange={(event) => setDraft({ ...draft, sender: event.target.value.trim() })} /></label>
            <label>{t("User (optional)")}<input value={draft.username} maxLength={200} autoComplete="off" onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></label>
            <label>{t("Password")}<input type="password" value={draft.password} autoComplete="new-password" aria-invalid={retype || undefined} placeholder={retype ? t("Type it again for the new server") : settings.has_password ? t("Saved: leave empty to keep it") : t("Only if the server asks for one")} onChange={(event) => setDraft({ ...draft, password: event.target.value, clear_password: false })} />
              {retype && <small className="cl-retype"><AlertTriangle size={12} /> {t("The server changed: type the password again. The saved one is only ever sent to the server it was typed for.")}</small>}</label>
            {settings.has_password && <label className="check field-span"><input type="checkbox" checked={draft.clear_password} onChange={(event) => setDraft({ ...draft, clear_password: event.target.checked, password: "" })} /> {t("Remove the saved password")}</label>}
            <label className="check field-span"><input type="checkbox" checked={draft.verify_certificate} onChange={(event) => setDraft({ ...draft, verify_certificate: event.target.checked })} /> {t("Check the server's certificate (turn off only for a server with a self-signed certificate)")}</label>
          </div>
          <div><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" />} {t("Save")}</button></div>
          </FormSection>
        </form>
        <FormSection id="mail-test" title={t("Test")} detail={outbox ? `${t("Outbox: {sent} sent, {pending} waiting, {failed} given up.", { sent: outbox.sent, pending: outbox.pending, failed: outbox.failed })}${outbox.last_error ? ` ${t("Last error: {error}", { error: outbox.last_error })}` : ""}` : undefined}>
        <div className="form-grid">
          <label className="field-span">{t("Send a test email to")}<input type="email" value={to} placeholder={t("Your email (from your profile when empty)")} onChange={(event) => setTo(event.target.value)} /></label>
          {test && <div className={`sp-test-result field-span${test.sent ? " ok" : ""}`}><strong>{test.sent ? <><CheckCircle2 size={14} /> {t("Sent to {to}", { to: test.to })}</> : t("Not sent")}</strong>{test.error && <p>{test.error}</p>}</div>}
        </div>
        <div><button type="button" className="button button-secondary" disabled={busy} onClick={() => void sendTest()}><Send /> {t("Send test")}</button></div>
        </FormSection>
    </section>}
  </>;
}

export default MailSettingsPage;
