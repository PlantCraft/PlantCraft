/** The apps of the suite (API v1) and the app keys they use; see docs/api-v1.md. */
import { requestJson } from "./api";

export interface SuiteApp { id: string; name: string; url: string; access: "editor" | "viewer"; version: string | null }
export interface TokenGrant { token: string; expires_at: string }
export interface AppKey { key_id: string; app_id: string; label: string; created_by: string | null; created_at: string; revoked_at: string | null; revoked_by: string | null; last_used_at: string | null; active: boolean; scopes?: string[] | null }
export interface NewAppKey extends AppKey { key: string }
export interface AppKeyList { keys: AppKey[]; apps: { id: string; name: string; url: string }[] }

/** How often the browser renews the token the apps read (it lives 15 minutes). */
export const TOKEN_RENEW_MS = 10 * 60 * 1000;

export const suiteApi = {
  /** A fresh token for this session; also renews the processcraft_token cookie the apps read. */
  renewToken: () => requestJson<TokenGrant>("/api/v1/auth/token", { method: "POST" }),
  /** The apps this person may open, with their URLs. */
  apps: async () => {
    const { token } = await suiteApi.renewToken();
    return requestJson<SuiteApp[]>("/api/v1/apps", { headers: { Authorization: `Bearer ${token}` } });
  },
  appKeys: () => requestJson<AppKeyList>("/api/app-keys"),
  createAppKey: (app_id: string, label: string, scopes: string[] | null = null) => requestJson<NewAppKey>("/api/app-keys", { method: "POST", body: JSON.stringify({ app_id, label, scopes }) }),
  revokeAppKey: (keyId: string) => requestJson<AppKey>(`/api/app-keys/${encodeURIComponent(keyId)}`, { method: "DELETE" }),
};
