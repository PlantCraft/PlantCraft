/** Messages, actions and specialists (docs/collaboration.md, "Interface API"). */
import { requestJson } from "./api";

/** Conversation and action ids as the API gives them (whole numbers today; kept as they come). */
export type Id = number | string;
export type MemberKind = "person" | "specialist" | "system";
export interface Contact { username: string; display_name: string; role: string; kind: MemberKind; subject?: string | null; model_on?: boolean | null }
/** A group of people as the new-conversation dialog shows it: its members (without you), and whether you are in it. */
export interface ContactGroup { group_id: string; name: string; kind_label: string; members: string[]; mine: boolean }
export interface Contacts { people: Contact[]; specialists: Contact[]; groups?: ContactGroup[]; suggested: string[]; model_allowed: boolean }
export interface ConversationMember { username: string; display_name: string; role: string; kind: MemberKind; busy: boolean }
export interface LastMessage { message_id: number; author: string; author_name: string; text: string; created_at: string }
export interface Conversation {
  conversation_id: Id; title: string; display_title: string; is_group: boolean; has_specialist: boolean; unread: number;
  /** A group's own conversation: its participants follow the group. */
  group_id?: string | null;
  busy: string[]; members: ConversationMember[]; last_message: LastMessage | null; created_at: string; updated_at: string;
  /** The person's own marks: a favorite, and unread again until opened. */
  starred?: boolean; marked_unread?: boolean;
}
export interface ResolvedRef { ref: string; kind: string; id: string; kind_label: string; title: string; href: string | null; exists: boolean }
export interface Message {
  message_id: number; conversation_id: Id; author: string; author_name: string; author_kind: MemberKind; text: string;
  refs: ResolvedRef[]; meta: { writer?: string; fallback?: boolean; kind?: string; app?: string; priority?: string; priority_label?: string; url?: string | null } | null; created_at: string;
}
export interface RefOption { ref: string; kind: string; kind_label: string; title: string; detail: string }

/** Messages' Notifications (GET /api/notifications): apps' notifications (one thread per app and key),
 * changes others made to the person's actions, alarms on what they follow. */
export type NoticeCategory = "alarm" | "run" | "action" | "info";
export type NoticeState = "unread" | "read" | "archived";
export interface NoticeStep { title: string; text: string; at: string; priority?: string | null }
export interface Notice {
  key: string; kind: "notice" | "action" | "followed"; category: NoticeCategory; priority: string; priority_label?: string | null;
  app: string; from: string; title: string; detail: string; at: string; href: string | null;
  actions: Array<{ label: string; href: string; method?: "GET" | "POST" }>; refs: ResolvedRef[]; history: NoticeStep[]; state: NoticeState;
  /** The app settled it (an alarm acknowledged): for everyone, with who did it. */
  resolved?: { note: string; at: string } | null;
  /** One of the person's favorites (it keeps the star when a new event arrives). */
  starred?: boolean;
}
/** What a person marks for themselves: a favorite, or unread again (conversations and assistant chats). */
export type PersonMark = "star" | "unread";
export interface NoticeFeed { items: Notice[]; counts: Record<NoticeState, number> }

export type ActionStatus = "open" | "in_progress" | "blocked" | "done" | "cancelled";
export interface ActionDraft { title: string; description: string; priority: string; owner: string | null; group_id?: string | null; due_at: string | null; refs: string[]; kind?: ActionKind; category?: string | null }
/** An action, or a request someone asked of IT or an integrator (Operations › Requests). */
export type ActionKind = "action" | "request";
export interface RequestDraft { title: string; description: string; category: string; priority?: string; group_id: string | null; refs: string[] }
/** Time logged on an action, in hours on a day. */
export interface TimeEntry { entry_id: number; username: string; display_name: string; day: string; hours: number; note: string; billable: boolean; created_at: string; /** Its month's hours are approved: closed to changes. */ locked?: boolean }
/** Where a request stands against one target (plantcraft/actions/sla.py). */
export interface SlaClock { target_minutes: number; used_minutes: number; state: "running" | "at_risk" | "met" | "breached"; due_at: string | null; paused_minutes?: number; paused?: boolean }
export interface RequestSla { response: SlaClock; resolution: SlaClock }
export interface ActionHistory { kind: "created" | "changed" | "status" | "comment" | "checklist" | "hours"; text: string; actor: string; actor_name: string; created_at: string }
/** One line of an action's checklist: what, who and by when, ticked when done. */
export interface ActionItem { item_id: number; text: string; done: boolean; owner: string | null; owner_name: string | null; due_at: string | null; overdue: boolean; done_by: string | null; done_by_name: string | null; done_at: string | null }
export interface ItemChange { text?: string; owner?: string | null; due_at?: string | null; done?: boolean }
export interface Action {
  action_id: Id; title: string; description: string; status: ActionStatus; status_label: string; priority: string; priority_label: string;
  owner: string | null; owner_name: string | null; due_at: string | null; overdue: boolean; refs: ResolvedRef[];
  /** The group it is assigned to. */
  group_id?: string | null; group_name?: string | null;
  created_by: string; created_by_name: string; created_at: string; updated_at: string; completed_at: string | null; history?: ActionHistory[];
  /** When it took its current status (its last status change, else its creation). */
  status_since?: string;
  kind?: ActionKind; kind_label?: string;
  /** A request's category, and when someone other than who asked first answered. */
  category?: string | null; category_label?: string | null; first_response_at?: string | null;
  /** The hours logged on it in all, and (on its own page) each entry. */
  hours_logged?: number; hours?: TimeEntry[];
  /** A request's first answer and resolution against its targets (none when archived). */
  sla?: RequestSla | null;
  /** Items ticked and in all (the board's cards). */
  checklist?: { done: number; total: number };
  /** On the action's own page: the checklist, and the #references written in the text and comments. */
  items?: ActionItem[];
  mentions?: ResolvedRef[];
}
export interface Choice { id: string; label: string }
export type ActionView = "visible" | "mine" | "groups" | "created";
export interface ActionList {
  items: Action[]; statuses: Choice[]; open_statuses?: string[]; priorities: Choice[]; people: Array<{ username: string; display_name: string }>;
  /** Every group, and whether it is one of this person's (theirs or below one they lead). */
  groups?: Array<{ group_id: string; name: string; mine: boolean }>;
  /** The quick filters (Jira's "Assigned to me", "My groups"...). */
  views?: Array<{ id: ActionView; label: string }>;
  /** An administrator: sees every action. */
  everything?: boolean;
  kinds?: Choice[]; categories?: Choice[];
}
export interface ActionQuery { status?: string[]; owner?: string; ref?: string; q?: string; mine?: boolean; view?: ActionView; kind?: ActionKind }

/** installation: the default set up in Setup; provider: a saved provider and one of its models;
 * own: the fields of the profile (older profiles); off: scripted answers. */
export type ModelSource = "installation" | "provider" | "own" | "off";
export interface SpecialistModel { source: ModelSource; enabled: boolean; ready: boolean; provider: string; provider_id: string; name: string; endpoint: string; api_key_set: boolean; api_key_hint: string | null }
/** A language model provider saved in Setup (its key only as a hint). */
export interface LanguageProvider { provider_id: string; name: string; kind: string; kind_label: string; endpoint: string; models: string[]; reasoning: string; api_key_set: boolean; api_key_hint: string | null; ready: boolean; used_by: string[]; updated_at: string; updated_by: string }
/** What a use writes with: the default, off, or a provider's model. */
export interface UseChoice { source: "default" | "off" | "provider"; provider_id?: string; model?: string }
/** enabled: a default is chosen, which is what turns models on. */
export interface LanguageSettings { enabled: boolean; provider_id: string; model: string; uses: Record<string, UseChoice>; allowed: boolean; updated_at: string | null; updated_by: string | null }
/** A part of the suite that writes with a model: PlantCraft's own (app null) or one an app declared ([[contributes.llm]]), with what it sends. */
export interface LanguageUse { use: string; label: string; description: string; reads: string; app: string | null; choice: UseChoice; ready: boolean }
export interface LanguageModels { providers: LanguageProvider[]; settings: LanguageSettings; uses: LanguageUse[]; kinds: Choice[]; max_providers: number; saved?: string; orphans?: string[]; tests?: Record<string, SpecialistTest> }
/** api_key: null keeps the saved key, "" removes it, text sets it. */
/** reasoning: how hard OpenAI's reasoning models think; "" leaves it to the service. */
export interface ProviderDraft { name: string; kind: string; endpoint: string; models: string[]; api_key: string | null; reasoning: string }
/** The installation's language model (its key only as a hint). */
export interface LanguageModel { enabled: boolean; provider: string; provider_id?: string; provider_name?: string; name: string; endpoint: string; api_key_set: boolean; api_key_hint: string | null; ready: boolean; allowed: boolean; updated_at: string | null; updated_by: string | null; providers?: Choice[] }
export interface Specialist {
  username: string; display_name: string; subject: string; instructions: string; apps: string[]; active: boolean; model: SpecialistModel;
  answers: number; last_answer_at: string | null; updated_at: string | null; updated_by: string | null;
}
export interface SpecialistList { items: Specialist[]; apps: Array<{ application_id: string; name: string }>; model_allowed: boolean; defaults: { provider: string; model: string }; providers?: Choice[]; connection?: LanguageModel; language_providers?: Array<Pick<LanguageProvider, "provider_id" | "name" | "kind_label" | "models" | "ready">> }
export interface SpecialistDraft {
  display_name: string; subject: string; instructions: string; apps: string[]; active: boolean;
  /** api_key: null keeps the saved key, "" removes it, text sets it. */
  model: { source: ModelSource; provider: string; provider_id: string; name: string; endpoint: string; api_key: string | null };
}
export interface SpecialistTest { ok: boolean; writer: string; text: string }

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const seg = (value: Id) => encodeURIComponent(String(value));

/** Query string of the actions list; several statuses repeat the parameter (?status=open&status=blocked). */
export function actionQuery(query: ActionQuery): string {
  const params = new URLSearchParams();
  for (const status of query.status ?? []) params.append("status", status);
  if (query.owner) params.set("owner", query.owner);
  if (query.ref) params.set("ref", query.ref);
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.mine) params.set("mine", "true");
  if (query.view && query.view !== "visible") params.set("view", query.view);
  if (query.kind) params.set("kind", query.kind);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const collabApi = {
  contacts: (ref?: string | null) => requestJson<Contacts>(`/api/messages/contacts${ref ? `?${new URLSearchParams({ ref })}` : ""}`),
  conversations: () => requestJson<{ unread: number; items: Conversation[] }>("/api/messages/conversations"),
  startConversation: (body: { members: string[]; title?: string; text?: string; ref?: string | null }) => requestJson<{ conversation: Conversation; message: Message | null }>("/api/messages/conversations", json("POST", body)),
  conversation: (id: Id, after?: number) => requestJson<{ conversation: Conversation; messages: Message[] }>(`/api/messages/conversations/${seg(id)}${after ? `?after=${after}` : ""}`),
  send: (id: Id, text: string, ref?: string | null) => requestJson<Message>(`/api/messages/conversations/${seg(id)}/messages`, json("POST", ref ? { text, ref } : { text })),
  read: (id: Id, messageId?: number) => requestJson<{ unread: number }>(`/api/messages/conversations/${seg(id)}/read`, json("POST", messageId ? { message_id: messageId } : {})),
  groupConversation: (groupId: string) => requestJson<Conversation>(`/api/messages/groups/${seg(groupId)}`, json("POST")),
  addMembers: (id: Id, members: string[]) => requestJson<Conversation>(`/api/messages/conversations/${seg(id)}/members`, json("POST", { members })),
  notifications: () => requestJson<NoticeFeed>("/api/notifications"),
  markNotifications: (keys: string[], state: "read" | "archived" | null) => requestJson<{ state: string | null }>("/api/notifications/marks", json("POST", { keys, state })),
  /** A notification (its key), `conversation:<id>` or `chat:<id>`, marked or not; only for this person. */
  mark: (key: string, mark: PersonMark, on: boolean) => requestJson<{ key: string; mark: PersonMark; on: boolean }>("/api/me/marks", json("PUT", { key, mark, on })),
  references: (q: string) => requestJson<RefOption[]>(`/api/messages/references?${new URLSearchParams({ q })}`),

  actions: (query: ActionQuery = {}) => requestJson<ActionList>(`/api/actions${actionQuery(query)}`),
  action: (id: Id) => requestJson<Action>(`/api/actions/${seg(id)}`),
  createAction: (draft: ActionDraft) => requestJson<Action>("/api/actions", json("POST", draft)),
  updateAction: (id: Id, draft: ActionDraft & { status: ActionStatus }) => requestJson<Action>(`/api/actions/${seg(id)}`, json("PUT", draft)),
  comment: (id: Id, text: string) => requestJson<Action>(`/api/actions/${seg(id)}/comments`, json("POST", { text })),
  addItem: (id: Id, item: { text: string; owner: string | null; due_at: string | null }) => requestJson<Action>(`/api/actions/${seg(id)}/items`, json("POST", item)),
  changeItem: (id: Id, itemId: number, change: ItemChange) => requestJson<Action>(`/api/actions/${seg(id)}/items/${itemId}`, json("PATCH", change)),
  deleteItem: (id: Id, itemId: number) => requestJson<Action>(`/api/actions/${seg(id)}/items/${itemId}`, json("DELETE")),
  ask: (draft: RequestDraft) => requestJson<Action>("/api/requests", json("POST", draft)),
  logHours: (id: Id, entry: { hours: number; day: string | null; note: string; billable: boolean }) => requestJson<Action>(`/api/actions/${seg(id)}/hours`, json("POST", entry)),
  deleteHours: (id: Id, entryId: number) => requestJson<Action>(`/api/actions/${seg(id)}/hours/${entryId}`, json("DELETE")),

  specialists: () => requestJson<SpecialistList>("/api/specialists"),
  createSpecialist: (draft: SpecialistDraft & { username: string }) => requestJson<Specialist>("/api/specialists", json("POST", draft)),
  updateSpecialist: (username: string, draft: SpecialistDraft) => requestJson<Specialist>(`/api/specialists/${seg(username)}`, json("PUT", draft)),
  deleteSpecialist: (username: string) => requestJson<{ removed: string }>(`/api/specialists/${seg(username)}`, json("DELETE")),
  testSpecialist: (username: string) => requestJson<SpecialistTest>(`/api/specialists/${seg(username)}/test`, json("POST")),
  languageModel: () => requestJson<LanguageModel>("/api/language-model"),
  saveLanguageModel: (draft: { enabled: boolean; provider: string; name: string; endpoint: string; api_key: string | null }) => requestJson<LanguageModel>("/api/language-model", json("PUT", draft)),
  languageModels: () => requestJson<LanguageModels>("/api/language-models"),
  addProvider: (draft: ProviderDraft) => requestJson<LanguageModels>("/api/language-models/providers", json("POST", draft)),
  saveProvider: (id: string, draft: ProviderDraft) => requestJson<LanguageModels>(`/api/language-models/providers/${encodeURIComponent(id)}`, json("PUT", draft)),
  removeProvider: (id: string) => requestJson<LanguageModels>(`/api/language-models/providers/${encodeURIComponent(id)}`, json("DELETE")),
  testProvider: (id: string, model: string) => requestJson<SpecialistTest>(`/api/language-models/providers/${encodeURIComponent(id)}/test`, json("POST", { model })),
  saveModelSettings: (settings: { provider_id: string; model: string; uses?: Record<string, UseChoice> }) => requestJson<LanguageModels>("/api/language-models/settings", json("PUT", settings)),
  testLanguageModel: () => requestJson<SpecialistTest>("/api/language-model/test", json("POST")),
};
