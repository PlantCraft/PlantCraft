/** Corporate sign-in: the sign-in page's ways in, and Setup › Corporate sign-in (admins). */
import { requestJson } from "./api";
import type { AccessLevel, AppRole } from "./types";

export type LdapPreset = "active_directory" | "openldap";

export interface LdapSettings {
  enabled: boolean;
  preset: LdapPreset;
  url: string;
  security: "ldaps" | "starttls";
  verify_certificate: boolean;
  ca_certificate: string;
  bind_dn: string;
  base_dn: string;
  user_filter: string;
  username_attribute: string;
  id_attribute: string;
  group_mode: "memberof" | "search";
  group_base_dn: string;
  group_filter: string;
  group_name_attribute: string;
  display_name_attribute: string;
  email_attribute: string;
  job_title_attribute: string;
  department_attribute: string;
  phone_attribute: string;
  organization_attribute: string;
  unit_attribute: string;
  timeout_seconds: number;
}

export interface OidcSettings {
  enabled: boolean;
  label: string;
  issuer: string;
  client_id: string;
  scopes: string;
  username_claim: string;
  groups_claim: string;
  display_name_claim: string;
  email_claim: string;
  job_title_claim: string;
  department_claim: string;
  public_url: string;
  verify_certificate: boolean;
  ca_certificate: string;
}

export interface GroupRule {
  match: string;
  level: AccessLevel;
  apps: string[] | null;
  app_roles: Record<string, AppRole>;
  groups: string[];
}

export type Unmatched = "deny" | "dashboards" | "viewer" | "editor";

export interface DirectorySettingsDraft {
  ldap: LdapSettings;
  oidc: OidcSettings;
  rules: GroupRule[];
  unmatched: Unmatched;
  session_hours: number;
  local_passwords: boolean;
}

export interface DirectorySettings extends DirectorySettingsDraft {
  ldap: LdapSettings & { ready: boolean; has_bind_password: boolean };
  oidc: OidcSettings & { ready: boolean; redirect_uri: string; has_client_secret: boolean };
  allowed: boolean;
  sign_in_enabled: boolean;
  admin_account: string | null;
  presets: Record<LdapPreset, Partial<LdapSettings>>;
  apps: { id: string; name: string }[];
  groups: { group_id: string; name: string }[];
}

export interface Secrets {
  ldap_bind_password: string;
  clear_ldap_bind_password: boolean;
  oidc_client_secret: string;
  clear_oidc_client_secret: boolean;
}

export interface TestStep { step: string; ok: boolean; detail: string | null }
export interface MappedAccess { level: AccessLevel; apps: string[] | null; app_roles: Record<string, AppRole>; groups: string[]; matched: string[] }
export interface LdapTestReport {
  ok: boolean;
  steps: TestStep[];
  person: { username: string; display_name: string; groups: string[]; profile: Record<string, string> } | null;
  access?: MappedAccess | null;
}
export interface OidcTestReport { ok: boolean; steps: TestStep[]; redirect_uri: string }
export interface SignInMethods { ldap: boolean; oidc: boolean; oidc_label: string | null; error: string | null }

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const directoryApi = {
  methods: () => requestJson<SignInMethods>("/api/sso/methods"),
  settings: () => requestJson<DirectorySettings>("/api/directory"),
  save: (settings: DirectorySettingsDraft, secrets: Secrets) => requestJson<DirectorySettings>("/api/directory", json("PUT", { settings, ...secrets })),
  testLdap: (settings: DirectorySettingsDraft, secrets: Secrets, username: string, password: string) =>
    requestJson<LdapTestReport>("/api/directory/ldap/test", json("POST", { settings, ...secrets, username, password })),
  testOidc: (settings: DirectorySettingsDraft, secrets: Secrets) => requestJson<OidcTestReport>("/api/directory/oidc/test", json("POST", { settings, ...secrets })),
  preview: (settings: DirectorySettingsDraft, groups: string[]) => requestJson<{ access: MappedAccess | null }>("/api/directory/preview", json("POST", { settings, groups })),
};

/** Where the single sign-on starts, coming back to ``next`` (a path on this site) afterwards. */
export function ssoStartUrl(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? `/api/sso/oidc/start?${new URLSearchParams({ next })}` : "/api/sso/oidc/start";
}
