/** The assistant's chats in Desk (docs/assistant.md): its own API under /api/assistant. */
import type { AssistantProposal } from "@plantcraft/ui";
import { requestJson } from "./api";

export type AssistantProfile = { id: string; name: string; subject: string; ready: boolean };
export type ChatRef = { ref: string; kind: string | null; id: string | null; kind_label: string; title: string | null; href: string | null; status?: string | null; exists: boolean };
export type Chat = {
  chat_id: number; title: string; profile: string; profile_name: string; ref: string; ref_view: ChatRef | null; created_at: string; updated_at: string; messages?: number; working?: boolean;
  /** The person's own group of chats ("" none), archived or not, and who else reads it (`everyone`, `user:<name>`, `group:<id>`). */
  folder?: string; archived?: boolean; shared?: string[];
  /** false: someone else's chat shared with this person (read-only), with its owner. */
  mine?: boolean; owner?: string; owner_name?: string;
  /** The person's own marks: a favorite, and unread until opened. */
  starred?: boolean; unread?: boolean;
};
export type ChatStep = { tool: string; title: string; summary: string; state: "running" | "ok" | "error"; error?: string };
export type ChartSeries = { signal: string; kind?: string | null; unit?: string | null; t: string[]; v: Array<number | string | null> };
/** `trends`: the page that opens these signals over this period in Trends, when View is installed. */
export type ChatChart = { title: string; start: string; end: string; step_seconds: number; series: ChartSeries[]; errors: Array<{ signal: string; status: number; detail: string }>; trends?: string | null };
export type ChatMessage = {
  message_id: number; chat_id: number; role: "user" | "assistant"; text: string; state: "working" | "done" | "failed";
  steps: ChatStep[]; charts: ChatChart[]; refs: ChatRef[]; meta: { model?: string; queued?: boolean; proposals?: AssistantProposal[] }; created_at: string; updated_at: string;
};
export type AssistantStatus = { available: boolean; reason: string; profiles: AssistantProfile[]; daily_limit: number; chats: Chat[]; archived?: Chat[]; shared?: Chat[] };
export type ChatView = { chat: Chat; messages: ChatMessage[]; working: boolean };
export type EvalResult = { id: string; title: string; question: string; golden: string; answer: string; passed: boolean; why: string; error: string; tools: string[]; charts: number; seconds: number;
  /** A work's case (Evaluate works): the work, its page and subject, the context sent and the card proposed. */
  work?: string; page?: string; subject?: string; context?: string; proposal?: Record<string, unknown> | null };
export type EvalSuite = "questions" | "works";
export type EvalRun = { run_id: number; username: string; profile: string; model: string; state: "running" | "done" | "failed"; total: number; passed: number; results: EvalResult[]; error: string; suite?: EvalSuite; skipped?: string[]; created_at: string; updated_at: string };

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const assistantApi = {
  status: () => requestJson<AssistantStatus>("/api/assistant"),
  start: (text: string, profile = "", ref = "") => requestJson<{ chat: Chat; messages: ChatMessage[] }>("/api/assistant/chats", { method: "POST", ...json({ text, profile, ref }) }),
  chat: (id: number, after = 0) => requestJson<ChatView>(`/api/assistant/chats/${id}${after ? `?after=${after}` : ""}`),
  /** The last question asked again after its answer failed. */
  retry: (id: number) => requestJson<{ messages: ChatMessage[] }>(`/api/assistant/chats/${id}/retry`, { method: "POST" }),
  ask: (id: number, text: string) => requestJson<{ messages: ChatMessage[] }>(`/api/assistant/chats/${id}/messages`, { method: "POST", ...json({ text }) }),
  rename: (id: number, title: string) => requestJson<Chat>(`/api/assistant/chats/${id}`, { method: "PATCH", ...json({ title }) }),
  /** Put the chat in one of the person's groups ("" takes it out), or archive it / bring it back. */
  change: (id: number, change: { folder?: string; archived?: boolean }) => requestJson<Chat>(`/api/assistant/chats/${id}`, { method: "PATCH", ...json(change) }),
  share: (id: number, grants: string[]) => requestJson<Chat>(`/api/assistant/chats/${id}/sharing`, { method: "PUT", ...json({ grants }) }),
  copy: (id: number) => requestJson<Chat>(`/api/assistant/chats/${id}/copy`, { method: "POST" }),
  remove: (id: number) => requestJson<{ deleted: number }>(`/api/assistant/chats/${id}`, { method: "DELETE" }),
  evals: () => requestJson<{ runs: EvalRun[]; profiles: AssistantProfile[] }>("/api/assistant/evals"),
  startEval: (profile = "", suite: EvalSuite = "questions") => requestJson<EvalRun>("/api/assistant/evals", { method: "POST", ...json({ profile, suite }) }),
  evalRun: (id: number) => requestJson<EvalRun>(`/api/assistant/evals/${id}`),
};

/** Messages kept in order by id: a newer copy of a message replaces the older one. */
export function mergeMessages(current: ChatMessage[], fresh: ChatMessage[]): ChatMessage[] {
  const byId = new Map(current.map((item) => [item.message_id, item]));
  for (const item of fresh) byId.set(item.message_id, item);
  return [...byId.values()].sort((a, b) => a.message_id - b.message_id);
}

/** The last message id that will not change any more (the next poll asks after it). */
export function settledUpTo(messages: ChatMessage[]): number {
  let last = 0;
  for (const item of messages) {
    if (item.state === "working") break;
    last = item.message_id;
  }
  return last;
}

/** The person's chats as the list shows them: each group of theirs (by name), then the rest by when
 * they were last used. */
export function chatSections(chats: Chat[], now = new Date()): Array<{ key: string; folder?: string; chats: Chat[] }> {
  // The favorites first, wherever they are kept.
  const starred = chats.filter((chat) => chat.starred);
  const rest = chats.filter((chat) => !chat.starred);
  const folders = new Map<string, Chat[]>();
  for (const chat of rest) if (chat.folder) folders.set(chat.folder, [...(folders.get(chat.folder) ?? []), chat]);
  const named = [...folders.keys()].sort((a, b) => a.localeCompare(b)).map((folder) => ({ key: `folder:${folder}`, folder, chats: folders.get(folder) ?? [] }));
  return [...(starred.length ? [{ key: "starred", chats: starred }] : []), ...named, ...chatGroups(rest.filter((chat) => !chat.folder), now)];
}

/** The chat's reference, to paste in an action's About or in a message (`#[title](chat:12)`). */
export function chatMention(chat: Pick<Chat, "chat_id" | "title">): string {
  return `#[${chat.title.replace(/[[\]\n]/g, " ").slice(0, 100)}](chat:${chat.chat_id})`;
}

/** Chats grouped by when they were last used: today, the last 7 days, older. */
export function chatGroups(chats: Chat[], now = new Date()): Array<{ key: string; chats: Chat[] }> {
  const start = new Date(now); start.setHours(0, 0, 0, 0);
  const week = new Date(start); week.setDate(week.getDate() - 7);
  const groups: Record<string, Chat[]> = { today: [], week: [], older: [] };
  for (const chat of chats) {
    const at = new Date(chat.updated_at);
    groups[at >= start ? "today" : at >= week ? "week" : "older"].push(chat);
  }
  return ["today", "week", "older"].filter((key) => groups[key].length).map((key) => ({ key, chats: groups[key] }));
}
