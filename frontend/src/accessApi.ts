/** User administration. */
import { requestJson } from "./api";
import type { AccessLevel, AppRole, PersonCard, Profile, UserAccount, UserAccounts } from "./types";

export interface UserDraft { display_name: string; role: string; access_level: AccessLevel; applications: string[] | null; app_roles?: Record<string, AppRole>; profile?: Profile; groups?: string[]; active?: boolean; asset_scope?: string[] | null }
export const EMPTY_PROFILE: Profile = { job_title: "", affiliation: "", organization: "", email: "", phone: "", unit: "" };

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const path = (value: string) => encodeURIComponent(value);

export const accessApi = {
  accounts: () => requestJson<UserAccounts>("/api/users/accounts"),
  createUser: (draft: UserDraft & { username: string; password?: string }) => requestJson<UserAccount>("/api/users", json("POST", draft)),
  updateUser: (username: string, draft: UserDraft) => requestJson<UserAccount>(`/api/users/${path(username)}`, json("PUT", draft)),
  person: (username: string) => requestJson<PersonCard>(`/api/people/${path(username)}`),
  me: () => requestJson<PersonCard>("/api/me/profile"),
  saveMe: (draft: { display_name: string; role: string; profile: Profile }) => requestJson<PersonCard>("/api/me/profile", json("PUT", draft)),
  resetPassword: (username: string, password: string) => requestJson<UserAccount>(`/api/users/${path(username)}/password`, json("POST", { password })),
};
