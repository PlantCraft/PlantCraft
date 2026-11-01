import { createApiClient, jsonBody, query, type HelpEntry, type HelpPage } from "@plantcraft/ui";
import { href } from "./nav";
import type { Me, Note, NoteDraft } from "./types";

const client = createApiClient({ app: "starter", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
const request = client.request;
const id = encodeURIComponent;

export const api = {
  me: () => request<Me>("/api/me"),
  notes: (asset?: string) => request<Note[]>(`/api/notes${query({ asset })}`),
  note: (noteId: string) => request<Note>(`/api/notes/${id(noteId)}`),
  create: (draft: NoteDraft) => request<Note>("/api/notes", jsonBody("POST", draft)),
  save: (noteId: string, draft: NoteDraft) => request<Note>(`/api/notes/${id(noteId)}`, jsonBody("PUT", draft)),
  remove: (noteId: string) => request<void>(`/api/notes/${id(noteId)}`, { method: "DELETE" }),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
};
