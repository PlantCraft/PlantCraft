/** Operations › Support access: an administrator lets a person into Operations for a few hours
 * (an integrator's engineer or IT called for a problem), for a reason and often a request. The
 * access ends by itself; an administrator ends it earlier. Both are in the audit log.
 * See docs/operations.md, section 4, and plantcraft/auth/support_access.py. */
import { AlertTriangle, KeyRound, LoaderCircle, Plus } from "lucide-react";
import { type DataColumn, DataTable, Dialog, Heading } from "@plantcraft/ui";
import { useCallback, useEffect, useState } from "react";
import { errorText, fullWhen, Go, PersonLink, shortWhen } from "./collab";
import { t } from "./i18n";
import { operationsApi, type SupportGrant } from "./operationsApi";
import { minutesText } from "./OperationsRequests";
import { useIsAdmin } from "./session";
import "./apps.css";
import "./operations.css";

export interface SupportPerson { username: string; display_name: string }

/** What the person reads about a grant: "ends in 3 h", "ended 12 Oct 14:05". */
export function grantState(grant: Pick<SupportGrant, "active" | "ends_at" | "ended_at">, now = Date.now()): { text: string; active: boolean } {
  if (grant.active) return { text: t("ends in {time}", { time: minutesText((Date.parse(grant.ends_at) - now) / 60000) }), active: true };
  return { text: grant.ended_at ? t("ended early, {when}", { when: shortWhen(grant.ended_at) }) : t("ended {when}", { when: shortWhen(grant.ends_at) }), active: false };
}

/** The form's start from the address: ?new=1&user=&request= (a request's page links here). */
export function readGrantPrefill(search: string): { username: string; request: string } | null {
  const params = new URLSearchParams(search);
  if (!params.get("new")) return null;
  return { username: params.get("user") ?? "", request: params.get("request") ?? "" };
}

export function SupportPage({ people }: { people: SupportPerson[] }) {
  const admin = useIsAdmin();
  const [grants, setGrants] = useState<SupportGrant[] | null>(null);
  const [maxHours, setMaxHours] = useState(72);
  const [error, setError] = useState("");
  const [granting, setGranting] = useState<{ username: string; request: string } | null>(null);
  const load = useCallback(() => operationsApi.supportAccess().then((found) => { setGrants(found.grants); setMaxHours(found.max_hours); setError(""); }, (err) => setError(errorText(err))), []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const prefill = readGrantPrefill(window.location.search);
    if (prefill && admin) { setGranting(prefill); window.history.replaceState(window.history.state, "", window.location.pathname); }
  }, [admin]);
  async function end(grant: SupportGrant) {
    try { await operationsApi.endSupport(grant.grant_id); await load(); } catch (err) { setError(errorText(err)); }
  }
  const columns: DataColumn<SupportGrant>[] = [
    { key: "person", label: t("Person"), sort: (item) => item.display_name, render: (item) => <PersonLink username={item.username} name={item.display_name} /> },
    { key: "reason", label: t("Reason"), sort: (item) => item.reason, render: (item) => <>{item.reason}{item.action_id && <small className="apps-sub"><Go to={`/actions/${item.action_id}`}>{t("Request #{id}", { id: item.action_id })}</Go></small>}</> },
    { key: "state", label: t("Access"), sort: (item) => (item.active ? "0" : "1") + item.ends_at, filter: { value: (item) => (item.active ? t("In force") : t("Ended")) }, render: (item) => { const state = grantState(item); return <span className={`apps-chip${state.active ? " apps-chip-warn" : ""}`} title={fullWhen(item.ends_at)}>{state.text}</span>; } },
    { key: "by", label: t("Given by"), phone: "hide", sort: (item) => item.granted_by_name, render: (item) => <PersonLink username={item.granted_by} name={item.granted_by_name} /> },
    { key: "end", label: "", render: (item) => (admin && item.active ? <button type="button" className="button button-ghost" onClick={(event) => { event.stopPropagation(); void end(item); }}>{t("End now")}</button> : null) },
  ];
  return <div className="apps-page ops-support">
    <Heading title={t("Support access")} actions={admin ? <button type="button" className="button button-primary" onClick={() => setGranting({ username: "", request: "" })}><Plus size={15} /> {t("Give support access")}</button> : undefined} />
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!grants && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {grants && <DataTable rows={grants} columns={columns} rowKey={(item) => String(item.grant_id)} label={t("Support access")} initialSort={{ key: "state", descending: false }}
      searchText={(item) => `${item.display_name} ${item.reason}`} searchPlaceholder={t("Filter")} empty={t("Nobody had support access in the last 30 days.")} />}
    {granting && <GrantDialog people={people} maxHours={maxHours} prefill={granting} onClose={() => setGranting(null)} onGranted={() => { setGranting(null); void load(); }} />}
  </div>;
}

function GrantDialog({ people, maxHours, prefill, onClose, onGranted }: { people: SupportPerson[]; maxHours: number; prefill: { username: string; request: string }; onClose: () => void; onGranted: () => void }) {
  const [username, setUsername] = useState(prefill.username);
  const [hours, setHours] = useState("4");
  const [reason, setReason] = useState("");
  const [request, setRequest] = useState(prefill.request);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const value = Number(hours.replace(",", "."));
  const ready = Boolean(username) && value > 0 && value <= maxHours && Boolean(reason.trim());
  async function submit() {
    if (!ready) return;
    setBusy(true);
    try { await operationsApi.grantSupport({ username, hours: value, reason: reason.trim(), action_id: request ? Number(request) : null }); onGranted(); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <Dialog title={t("Give support access")} onClose={onClose} onSubmit={() => void submit()}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !ready}>{busy ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />} {t("Give access")}</button></>}>
    <div className="ops-ask">
      <label><span>{t("Person")}</span><select value={username} required onChange={(event) => setUsername(event.target.value)}>
        <option value="">{t("Choose a person")}</option>
        {people.map((person) => <option key={person.username} value={person.username}>{person.display_name}</option>)}
      </select></label>
      <label><span>{t("For how many hours (up to {count})", { count: maxHours })}</span><input inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value)} /></label>
      <label className="ops-ask-text"><span>{t("Why")}</span><input value={reason} maxLength={300} required onChange={(event) => setReason(event.target.value)} placeholder={t("Alarms stopped after the update")} /></label>
      <label><span>{t("Request number (optional)")}</span><input inputMode="numeric" value={request} onChange={(event) => setRequest(event.target.value.replace(/\D/g, ""))} /></label>
    </div>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
  </Dialog>;
}
