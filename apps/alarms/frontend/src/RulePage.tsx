import { useAssistantPage } from "@plantcraft/ui";
import { Pencil, Power } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { useDirectory, whoLabel } from "./people";
import { EDITOR_WORDS } from "./RulesPage";
import { AlarmTable } from "./SummaryPage";
import type { Me, Rule } from "./types";
import { ErrorBox, Heading, Link, Loading, PriorityPill, message } from "./ui";

/** One rule: what it watches, when it raises, what it makes and who hears, then its alarms (one per
 * target); each alarm keeps its own history. */
export function RulePage({ ruleId, me }: { ruleId: string; me: Me }) {
  const [rule, setRule] = useState<Rule | null>(null);
  const [error, setError] = useState("");
  const directory = useDirectory();
  const load = useCallback(() => api.rule(ruleId).then(setRule).catch((err) => setError(message(err))), [ruleId]);
  useEffect(() => { void load(); }, [load]);
  // The rule as its works read it (app.toml): what it covers and when it raises.
  useAssistantPage(rule && { page: "alarmcraft:rule", title: rule.name, place: t("Alarms › Rule {name}", { name: rule.name }), platformUrl: me.processcraft_url,
    facts: { rule: rule.rule_id, editor: rule.editor_label, when: rule.sentence, where: rule.where_words, value: rule.simple?.conditions.find((item) => item.value?.signal)?.value?.signal ?? "",
      priority: rule.priority_label, enabled: rule.enabled, alarms: rule.alarms, active: rule.active, owner: rule.owner ?? "", recipients: rule.recipients.slice(0, 10) } });
  if (!rule) return error ? <ErrorBox text={error} /> : <Loading />;
  const notify = rule.notify;
  const rows = rule.alarm_rows ?? [];
  const outputs = [t("Alarms"), rule.dashboards ? t("dashboards") : "", notify.enabled ? (notify.email ? t("messages and email") : t("messages")) : ""].filter(Boolean).join(", ");
  const facts: Array<[string, ReactNode]> = [
    [t("When"), <>{rule.sentence} <span className="muted">({t(EDITOR_WORDS[rule.editor] ?? rule.editor)})</span></>],
    [t("Where"), rule.where_words],
    [t("Makes"), <><PriorityPill priority={rule.priority} /> {t(rule.creates_label)}</>],
    [t("Outputs"), notify.enabled ? `${outputs} · ${t("to {who}", { who: notify.recipients.map((ref) => whoLabel(ref, directory)).join(", ") })}` : outputs],
    [t("Owner"), whoLabel(rule.owner, directory)],
    ...(rule.action ? [[t("Corrective action"), rule.action] as [string, ReactNode]] : []),
  ];
  return <>
    <Heading eyebrow={<Link to="/rules">{t("Rules")}</Link>} title={rule.name}
      actions={me.can_edit && <>
        <button type="button" className="button button-secondary" onClick={() => void api.enableRule(rule.rule_id, !rule.enabled).then(setRule).catch((err) => setError(message(err)))}>
          <Power size={16} />{rule.enabled ? t("Turn off") : t("Turn on")}
        </button>
        <Link to={`/rules/${rule.rule_id}/edit`} className="button button-primary"><Pencil size={16} />{t("Change")}</Link>
      </>} />
    {error && <ErrorBox text={error} />}
    {!rule.enabled && <div className="notice">{t("This rule is off: it evaluates nothing and its alarms are out of service.")}</div>}
    {!rule.valid && <div className="notice notice-error">{t("This rule cannot run as it is saved. Change it to fix it.")}</div>}
    <section className="panel"><dl className="al-facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>
    <h2 className="section-title">{t("Its alarms")}</h2>
    {rows.length ? <AlarmTable alarms={rows} me={me} onChanged={() => void load()} searchable={rows.length > 10} />
      : <p className="muted">{rule.where.anywhere ? t("None yet: an alarm appears for each asset the events are about.") : t("None: nothing under the rule has what it reads (an asset with the signal role, a monitor with assets).")}</p>}
  </>;
}
