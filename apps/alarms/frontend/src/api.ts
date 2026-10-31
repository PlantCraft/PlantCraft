import { createApiClient, jsonBody, query, type ExploreAnswer, type ExploreHit, type HelpEntry, type HelpPage } from "@plantcraft/ui";
import type { Diagram, DiagramCheck } from "@plantcraft/ui/blockEditor";
import { href } from "./nav";
import type { Alarm, AlarmListImport, AlarmHistory, AssetAlarms, AssetOption, Catalog, Condition, ConsoleLoads, Directory, EventDetail, Incoming, JournalEntry, Me, Performance, Philosophy, PhilosophyRecord, Rule, RuleDraft, Sent, SignalOption, Silence, SilenceDraft, SimpleLogic, Summary, TryResult, Execution } from "./types";

const client = createApiClient({ app: "alarmcraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
const request = client.request;
const body = jsonBody;
const id = encodeURIComponent;

export const api = {
  me: () => request<Me>("/api/me"),
  summary: (rule?: string) => request<Summary>(`/api/summary${query({ rule })}`),
  alarms: () => request<Alarm[]>("/api/alarms"),
  alarm: (alarmId: string) => request<Alarm>(`/api/alarms/${id(alarmId)}`),
  history: (alarmId: string, window: string) => request<AlarmHistory>(`/api/alarms/${id(alarmId)}/history${query({ window })}`),
  enable: (alarmId: string, enabled: boolean) => request<Alarm>(`/api/alarms/${id(alarmId)}/enabled`, body("POST", { enabled })),
  ack: (alarmId: string) => request<Alarm>(`/api/alarms/${id(alarmId)}/ack`, { method: "POST" }),
  ackAll: (alarmIds?: string[]) => request<{ acknowledged: number }>("/api/ack", body("POST", { alarm_ids: alarmIds ?? null })),
  shelve: (alarmId: string, minutes: number, reason: string) => request<Alarm>(`/api/alarms/${id(alarmId)}/shelve`, body("POST", { minutes, reason })),
  unshelve: (alarmId: string) => request<Alarm>(`/api/alarms/${id(alarmId)}/unshelve`, { method: "POST" }),
  rules: () => request<Rule[]>("/api/rules"),
  rule: (ruleId: string) => request<Rule>(`/api/rules/${id(ruleId)}`),
  createRule: (draft: RuleDraft) => request<Rule>("/api/rules", body("POST", draft)),
  saveRule: (ruleId: string, draft: RuleDraft, baseUpdatedAt: string) => request<Rule>(`/api/rules/${id(ruleId)}`, body("PUT", { ...draft, base_updated_at: baseUpdatedAt })),
  removeRule: (ruleId: string) => request<void>(`/api/rules/${id(ruleId)}`, { method: "DELETE" }),
  enableRule: (ruleId: string, enabled: boolean) => request<Rule>(`/api/rules/${id(ruleId)}/enabled`, body("POST", { enabled })),
  tryRule: (rule: RuleDraft, window: string, ruleId?: string) => request<TryResult>("/api/rules/try", body("POST", { rule, window, rule_id: ruleId ?? null })),
  checkDiagram: (diagram: Diagram) => request<DiagramCheck>("/api/rules/check", body("POST", { diagram })),
  simple: (simple: SimpleLogic) => request<{ diagram: Diagram; sentence: string }>("/api/rules/simple", body("POST", { simple })),
  ruleFromEvent: (eventId: number) => request<Partial<RuleDraft>>(`/api/rules/from-event/${eventId}`),
  ruleFromCatalog: (kind: string) => request<Partial<RuleDraft>>(`/api/rules/from-catalog${query({ kind })}`),
  catalog: () => request<Catalog>("/api/catalog"),
  conditions: () => request<Condition[]>("/api/conditions"),
  philosophy: () => request<PhilosophyRecord>("/api/philosophy"),
  savePhilosophy: (draft: Philosophy) => request<PhilosophyRecord>("/api/philosophy", body("PUT", draft)),
  ruleJournal: (ruleId: string, window: string) => request<JournalEntry[]>(`/api/rules/${id(ruleId)}/journal${query({ window })}`),
  event: (eventId: number) => request<EventDetail>(`/api/incoming/${eventId}`),
  condition: (app: string, key: string) => request<EventDetail>(`/api/incoming/condition${query({ app, key })}`),
  incoming: (filters: { window: string; app?: string; kind?: string; severity?: string; subject?: string }) => request<Incoming>(`/api/incoming${query({ ...filters, limit: "1000" })}`),
  journal: (window: string, alarm?: string) => request<JournalEntry[]>(`/api/journal${query({ window, alarm, limit: "2000" })}`),
  performance: (window: string, console?: string) => request<Performance>(`/api/performance${query({ window, console })}`),
  consoleLoads: (window: string) => request<ConsoleLoads>(`/api/performance/consoles${query({ window })}`),
  run: () => request<Record<string, number>>("/api/run", { method: "POST" }),
  assets: (q?: string) => request<AssetOption[]>(`/api/assets${query({ q })}`),
  signals: (q: string) => request<SignalOption[]>(`/api/signals${query({ q, limit: "30" })}`),
  explore: (asset?: string) => request<ExploreAnswer>(`/api/explore${query({ asset })}`),
  exploreSearch: (q: string) => request<{ hits: ExploreHit[] }>(`/api/explore${query({ q })}`),
  value: (signal: string) => request<{ value: unknown; at?: string | null; unit?: string | null }>(`/api/value${query({ signal })}`),
  executions: () => request<Execution[]>("/api/executions"),
  assetTypes: () => request<Array<{ id: string; name: string }>>("/api/asset-types"),
  assetAlarms: (assetId: string) => request<AssetAlarms>(`/api/asset-alarms${query({ asset: assetId })}`),
  directory: () => request<Directory>("/api/directory"),
  sent: () => request<Sent>("/api/sent"),
  silences: () => request<Silence[]>("/api/silences"),
  addSilence: (draft: SilenceDraft) => request<Silence>("/api/silences", body("POST", draft)),
  endSilence: (silenceId: number) => request<Silence>(`/api/silences/${silenceId}/end`, { method: "POST" }),
  alarmLists: () => request<AlarmListImport[]>("/api/alarm-list"),
  alarmList: (importId: number) => request<AlarmListImport>(`/api/alarm-list/${importId}`),
  readAlarmList: (filename: string, content: string) => request<AlarmListImport>("/api/alarm-list", body("POST", { filename, content })),
  applyAlarmList: (importId: number, skip: string[]) => request<AlarmListImport>(`/api/alarm-list/${importId}/apply`, body("POST", { skip })),
  discardAlarmList: (importId: number) => request<AlarmListImport>(`/api/alarm-list/${importId}/discard`, { method: "POST" }),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
};
