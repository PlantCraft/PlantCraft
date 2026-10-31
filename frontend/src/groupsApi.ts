/** Groups of people, the email server and each person's notification preferences. */
import { requestJson } from "./api";
import { t } from "./i18n";

export type GroupKind = "department" | "area" | "discipline" | "team" | "company";
export interface GroupMember { username: string; display_name: string; active: boolean }
export interface Group { group_id: string; name: string; kind: GroupKind; kind_label: string; description: string; asset_id: string | null; coordinator: string | null; coordinator_name: string | null; members: GroupMember[]; parent_id: string | null; parent_name: string | null; children: string[]; asset_scope?: string[] | null; path?: GroupLink[]; subgroups?: GroupLink[]; can_manage?: boolean; can_edit_members?: boolean; is_member?: boolean;
  /** A company: the last day its people sign in, and its sponsor at the plant. */
  access_until?: string | null; sponsor?: string | null }
export interface GroupLink { group_id: string; name: string }
export interface GroupList { groups: Group[]; kinds: Array<{ id: GroupKind; label: string }> }
export interface GroupDraft { name: string; group_id?: string; kind: GroupKind; description: string; asset_id: string | null; coordinator: string | null; members: string[]; parent_id: string | null; asset_scope?: string[] | null; access_until?: string | null; sponsor?: string | null }
export interface PersonGroup { group_id: string; name: string; kind: GroupKind; kind_label: string; coordinator: boolean; parent_id?: string | null }

/** Groups in tree order (each after its parent), with their depth: the list reads as the hierarchy. */
export function groupTree(groups: Group[]): Array<{ group: Group; depth: number }> {
  const byParent = new Map<string | null, Group[]>();
  const ids = new Set(groups.map((group) => group.group_id));
  for (const group of groups) {
    const parent = group.parent_id && ids.has(group.parent_id) ? group.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), group]);
  }
  const found: Array<{ group: Group; depth: number }> = [];
  const walk = (parent: string | null, depth: number) => {
    for (const group of [...(byParent.get(parent) ?? [])].sort((a, b) => a.name.localeCompare(b.name))) {
      if (found.some((item) => item.group.group_id === group.group_id)) continue;
      found.push({ group, depth });
      walk(group.group_id, depth + 1);
    }
  };
  walk(null, 0);
  return found;
}

/** A group and every group under it (a group cannot move under one of these). */
export function groupAndBelow(groups: Group[], groupId: string): Set<string> {
  const found = new Set([groupId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const group of groups) if (group.parent_id && found.has(group.parent_id) && !found.has(group.group_id)) { found.add(group.group_id); grew = true; }
  }
  return found;
}

export type Priority = "critical" | "high" | "medium" | "low";
export interface MailSettings { enabled: boolean; host: string; port: number; security: "starttls" | "tls" | "none"; username: string; sender: string; verify_certificate: boolean; has_password: boolean; ready: boolean; outbox: { pending: number; sent: number; failed: number; last_error: string; last_error_at: string | null } }
export interface MailDraft { enabled: boolean; host: string; port: number; security: MailSettings["security"]; username: string; password: string; clear_password: boolean; sender: string; verify_certificate: boolean }
export interface NotificationPreferences { email: boolean; email_min_priority: Priority; email_ready: boolean }

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const path = (value: string) => encodeURIComponent(value);

export const groupsApi = {
  list: () => requestJson<GroupList>("/api/groups"),
  get: (id: string) => requestJson<Group>(`/api/groups/${path(id)}`),
  create: (draft: GroupDraft) => requestJson<Group>("/api/groups", json("POST", draft)),
  update: (id: string, draft: GroupDraft) => requestJson<Group>(`/api/groups/${path(id)}`, json("PUT", draft)),
  setMembers: (id: string, members: string[]) => requestJson<Group>(`/api/groups/${path(id)}/members`, json("PUT", { members })),
  remove: (id: string) => requestJson<{ deleted: string }>(`/api/groups/${path(id)}`, json("DELETE")),
  mail: () => requestJson<MailSettings>("/api/mail"),
  saveMail: (draft: MailDraft) => requestJson<MailSettings>("/api/mail", json("PUT", draft)),
  testMail: (to: string) => requestJson<{ sent: boolean; to: string; error?: string }>("/api/mail/test", json("POST", { to })),
  preferences: () => requestJson<NotificationPreferences>("/api/me/notifications"),
  savePreferences: (value: { email: boolean; email_min_priority: Priority }) => requestJson<NotificationPreferences>("/api/me/notifications", json("PUT", value)),
};

export const priorityLabels = (): Record<Priority, string> => ({ critical: t("Critical"), high: t("High"), medium: t("Medium"), low: t("Low") });
