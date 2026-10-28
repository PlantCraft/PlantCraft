import type { HomeAttention, HomeData, HomeStatus, MapFormatSection, MapReport, SessionInfo, WorkspaceUser } from "./types";
import type { PromptText } from "@plantcraft/ui";

import { language, t } from "./i18n";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const UNAUTHORIZED_EVENT = "processcraft:unauthorized";
const OFFLINE_MESSAGE = t("Couldn't connect to the server.");

/** Reads a FastAPI error body: a string, or Pydantic's list of problems. */
export function errorDetail(payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => (item as { msg?: unknown })?.msg).filter((msg): msg is string => typeof msg === "string" && msg !== "");
    return messages.length ? t("Invalid data: {details}", { details: messages.join("; ") }) : t("Invalid data.");
  }
  return t("Couldn't complete the operation.");
}

/** Shared fetch for every API module: translated errors, 401 tells the app. */
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...init,
      headers: { "Content-Type": "application/json", "X-Language": language, ...init?.headers },
    });
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, errorDetail(payload));
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
}

const request = requestJson;

export const api = {
  session: () => request<SessionInfo>("/api/session"),
  switchUser: (username: string) => request<SessionInfo>("/api/session/switch", { method: "POST", body: JSON.stringify({ username }) }),
  login: (username: string, password: string) =>
    request<{ authenticated: boolean; username: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/logout", { method: "POST" }),
  users: () => request<WorkspaceUser[]>("/api/users"),
  settings: () => request<Record<string, unknown>>("/api/settings"),
  help: () => request<Array<Record<string, string>>>("/api/help"),
  helpDocument: (id: string) => request<{ document_id: string; content: string }>(`/api/help/${encodeURIComponent(id)}`),
  mapFormat: () => request<MapFormatSection[]>("/api/map/format"),
  mapPrompt: (question?: string) => request<PromptText>(`/api/prompts/plant-map${question ? `?question=${encodeURIComponent(question)}` : ""}`),
  assetTreePrompt: (question?: string) => request<PromptText>(`/api/prompts/asset-tree${question ? `?question=${encodeURIComponent(question)}` : ""}`),
  mapPreview: (file: File, prune: boolean) => request<MapReport>(`/api/map/preview?${new URLSearchParams({ filename: file.name, prune: String(prune) })}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  mapApply: (file: File, prune: boolean) => request<MapReport>(`/api/map/apply?${new URLSearchParams({ filename: file.name, prune: String(prune) })}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  home: () => request<HomeData>("/api/home"),
  homeStatus: () => request<HomeStatus>("/api/home/status"),
  attention: () => request<HomeAttention[]>("/api/home/attention"),
};
