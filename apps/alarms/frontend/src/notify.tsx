/** Who hears about a rule's alarms: recipients (``owner`` is each alarm's responsible), email,
 * gathering, reminders, hours and escalation. The Messages part of the rule editor's Outputs. */
import { LOCAL_ZONE, RecipientPicker, TimeZoneSelect, timeZoneLabel } from "@plantcraft/ui";
import { Plus, X } from "lucide-react";
import { t } from "./i18n";
import type { Day, Directory, EscalationStep, HoursMode, HoursWindow, NotifyDraft } from "./types";

export const NEW_NOTIFY = (): NotifyDraft => ({
  enabled: true, recipients: ["owner"], email: false, group_seconds: 300, repeat_minutes: 240, notify_cleared: false,
  hours_mode: "always", hours: [], timezone: LOCAL_ZONE, escalations: [],
});

const DAYS: [Day, string][] = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];
const WORKDAYS: HoursWindow = { days: ["mon", "tue", "wed", "thu", "fri"], start: "07:00", end: "17:00" };
const HOURS_WORDS: Record<HoursMode, string> = {
  always: "Always", inside: "Only inside these hours (a shift)", outside: "Only outside these hours (on call)",
};

/** The picker knows people and groups only: the words ``owner`` and ``coordinator`` travel as
 * pseudo-groups in it and as the bare words to the API. */
const PSEUDO = ["owner", "coordinator"];
export const toPicker = (refs: string[]) => refs.map((ref) => (PSEUDO.includes(ref) ? `group:${ref}` : ref));
export const fromPicker = (refs: string[]) => refs.map((ref) => (PSEUDO.includes(ref.slice(6)) && ref.startsWith("group:") ? ref.slice(6) : ref));

/** "Mon–Fri 07:00–17:00": a window's days and times in words. */
export function windowWords(window: HoursWindow): string {
  const order = DAYS.map(([day]) => day);
  const picked = order.filter((day) => window.days.includes(day));
  const label = (day: Day) => t(DAYS.find(([id]) => id === day)?.[1] ?? day);
  const first = order.indexOf(picked[0]);
  const runs = picked.length > 2 && picked.every((day, index) => order.indexOf(day) === first + index);
  const days = picked.length === 7 ? t("Every day") : runs ? `${label(picked[0])}–${label(picked[picked.length - 1])}` : picked.map(label).join(", ");
  return `${days} ${window.start}–${window.end}`;
}

/** When a rule sends, in words. */
export function hoursWords(notify: NotifyDraft): string {
  if (notify.hours_mode === "always" || !notify.hours?.length) return t("Always");
  const windows = notify.hours.map(windowWords).join("; ");
  return notify.hours_mode === "inside" ? t("Only {windows} ({zone})", { windows, zone: timeZoneLabel(notify.timezone, t("Local time")) }) : t("Outside {windows} ({zone})", { windows, zone: timeZoneLabel(notify.timezone, t("Local time")) });
}

export function minutesLabel(minutes: number): string {
  if (!minutes) return t("never");
  if (minutes < 60) return t("every {n} min", { n: minutes });
  return t("every {n} h", { n: Math.round((minutes / 60) * 10) / 10 });
}

type Update = (patch: Partial<NotifyDraft>) => void;

function HoursEditor({ draft, update }: { draft: NotifyDraft; update: Update }) {
  const setWindow = (index: number, patch: Partial<HoursWindow>) => update({ hours: draft.hours.map((item, at) => (at === index ? { ...item, ...patch } : item)) });
  const toggle = (index: number, day: Day) => {
    const days = draft.hours[index].days;
    setWindow(index, { days: days.includes(day) ? days.filter((item) => item !== day) : [...days, day] });
  };
  return <>
    <label>{t("Sends")}<select value={draft.hours_mode} onChange={(event) => {
      const hours_mode = event.target.value as HoursMode;
      update({ hours_mode, hours: hours_mode !== "always" && !draft.hours.length ? [{ ...WORKDAYS, days: [...WORKDAYS.days] }] : draft.hours });
    }}>
      {Object.entries(HOURS_WORDS).map(([id, label]) => <option key={id} value={id}>{t(label)}</option>)}
    </select></label>
    {draft.hours_mode !== "always" && <>
      <label>{t("Time zone")}<TimeZoneSelect value={draft.timezone} onChange={(timezone) => update({ timezone })} /><small>{t("The clock the hours are read on; Local time is the installation's.")}</small></label>
      <div className="field-span al-windows">
        {draft.hours.map((window, index) => <div className="al-window" key={index} role="group" aria-label={t("Hours {n}", { n: index + 1 })}>
          <div className="al-days">{DAYS.map(([day, label]) => <label key={day} className={window.days.includes(day) ? "al-day al-day-on" : "al-day"}>
            <input type="checkbox" checked={window.days.includes(day)} onChange={() => toggle(index, day)} />{t(label)}
          </label>)}</div>
          <label className="al-time">{t("From")}<input type="time" value={window.start} onChange={(event) => setWindow(index, { start: event.target.value })} /></label>
          <label className="al-time">{t("To")}<input type="time" value={window.end === "24:00" ? "00:00" : window.end} onChange={(event) => setWindow(index, { end: event.target.value === "00:00" ? "24:00" : event.target.value })} /></label>
          {draft.hours.length > 1 && <button type="button" className="button button-small button-secondary" aria-label={t("Remove these hours")} onClick={() => update({ hours: draft.hours.filter((_, at) => at !== index) })}><X size={14} /></button>}
        </div>)}
        <button type="button" className="button button-small button-secondary" onClick={() => update({ hours: [...draft.hours, { days: ["sat", "sun"], start: "07:00", end: "19:00" }] })}><Plus size={14} />{t("More hours")}</button>
        <small className="muted">{t("A window that ends before it starts runs past midnight (Fri 17:00–07:00 is Friday night). Outside its hours the rule sends nothing; an alarm still waiting is handed over when its hours begin.")}</small>
      </div>
    </>}
  </>;
}

function EscalationEditor({ draft, update, directory, email }: { draft: NotifyDraft; update: Update; directory: Directory; email: boolean }) {
  const setStep = (index: number, patch: Partial<EscalationStep>) => update({ escalations: draft.escalations.map((item, at) => (at === index ? { ...item, ...patch } : item)) });
  const extra = [
    { id: "coordinator", name: t("Coordinator of the groups notified"), members: [] },
    { id: "owner", name: t("The alarm's responsible"), members: [] },
  ];
  const next = (draft.escalations[draft.escalations.length - 1]?.after_minutes ?? 0) + 15;
  return <div className="field-span al-windows">
    {draft.escalations.map((step, index) => <div className="al-step" key={index} role="group" aria-label={t("Escalation {n}", { n: index + 1 })}>
      <label className="al-time">{t("After (min)")}<input type="number" min={1} max={1440} value={step.after_minutes} onChange={(event) => setStep(index, { after_minutes: Math.max(1, Number(event.target.value) || 1) })} /></label>
      <div className="al-step-who"><RecipientPicker label={t("Also tell")} value={toPicker(step.recipients)} onChange={(recipients) => setStep(index, { recipients: fromPicker(recipients) })} people={directory.people} groups={[...extra, ...directory.groups]} placeholder={t("The coordinator, a person or a group")} /></div>
      {email && <label className="check"><input type="checkbox" checked={step.email} onChange={(event) => setStep(index, { email: event.target.checked })} /> {t("Email")}</label>}
      <button type="button" className="button button-small button-secondary" aria-label={t("Remove escalation {n}", { n: index + 1 })} onClick={() => update({ escalations: draft.escalations.filter((_, at) => at !== index) })}><X size={14} /></button>
    </div>)}
    {draft.escalations.length < 5 && <button type="button" className="button button-small button-secondary" onClick={() => update({ escalations: [...draft.escalations, { after_minutes: next, recipients: ["coordinator"], email }] })}><Plus size={14} />{t("Add an escalation step")}</button>}
    <small className="muted">{t("Counted from when the alarm was announced; acknowledging it stops the steps still to come. Escalations always go out, even past the hourly limit. The coordinator is the one set on each group in PlantCraft (People, Groups).")}</small>
  </div>;
}

/** A rule's messages: off shows its alarms in Alarms (and on dashboards) only; email only when PlantCraft can send it. */
export function NotifyEditor({ draft, update, directory, limit, email }: { draft: NotifyDraft; update: Update; directory: Directory; limit: number; email: boolean }) {
  const responsible = { id: "owner", name: t("The alarm's responsible"), members: [] };
  return <div className="form-grid">
    <label className="check field-span"><input type="checkbox" checked={draft.enabled} onChange={(event) => update({ enabled: event.target.checked })} /> {t("Send messages (off: the alarms show in Alarms only)")}</label>
    {draft.enabled && <>
      <div className="field-span">
        <span className="al-label">{t("Recipients")}</span>
        <RecipientPicker label={t("Recipients")} value={toPicker(draft.recipients)} onChange={(recipients) => update({ recipients: fromPicker(recipients) })} people={directory.people} groups={[responsible, ...directory.groups]} placeholder={t("The responsible, a person or a group")} />
        <small className="muted">{t("They get a message in PlantCraft's Messages, with Acknowledge on it. The responsible is the owner the app names (in Analytics, the monitor's owner), else the rule's owner.")}</small>
      </div>
      {email ? <label className="check field-span"><input type="checkbox" checked={draft.email} onChange={(event) => update({ email: event.target.checked })} /> {t("Also by email (to the people who allow it in their profile)")}</label>
        : <small className="muted field-span">{t("Email: an administrator sets up PlantCraft's email server first (Settings, Email).")}</small>}
      <label>{t("Gather for (s)")}<input type="number" min={0} max={3600} value={draft.group_seconds} onChange={(event) => update({ group_seconds: Math.max(0, Math.min(3600, Number(event.target.value) || 0)) })} /><small>{t("Every alarm of this rule raised within this time goes out as one message.")}</small></label>
      <label>{t("Remind every (min)")}<input type="number" min={0} max={10080} value={draft.repeat_minutes} onChange={(event) => update({ repeat_minutes: Math.max(0, Number(event.target.value) || 0) })} /><small>{t("While the alarm stays active and unacknowledged; 0 never.")}</small></label>
      <label className="check field-span"><input type="checkbox" checked={Boolean(draft.always_now)} onChange={(event) => update({ always_now: event.target.checked })} /> {t("Always at once (medium and low alarms otherwise wait for the shift summary, as the alarm philosophy says)")}</label>
      <label className="check"><input type="checkbox" checked={draft.notify_cleared} onChange={(event) => update({ notify_cleared: event.target.checked })} /> {t("Also when the alarm clears")}</label>
      <HoursEditor draft={draft} update={update} />
      <h3 className="field-span al-sub">{t("If nobody acknowledges")}</h3>
      <EscalationEditor draft={draft} update={update} directory={directory} email={email} />
      <small className="muted field-span">{t("No one gets more than {n} messages an hour from Alarms; past that they get one note that more are waiting in Alarms.", { n: limit })}</small>
    </>}
  </div>;
}
