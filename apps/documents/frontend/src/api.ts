import { createApiClient, jsonBody, query, type HelpEntry, type HelpPage } from "@plantcraft/ui";
import { href } from "./nav";
import type { Diagram, DiagramRow, Doc, DocRow, Folder, Hit, Me, Passage, PlantMap, SendFields, Verdict } from "./types";

const client = createApiClient({ app: "doccraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
const request = client.request;
const id = encodeURIComponent;

export interface FolderDraft { name: string; description: string; viewers: string[]; editors: string[]; assistant: boolean }

export const api = {
  me: () => request<Me>("/api/me"),
  kinds: () => request<string[]>("/api/kinds"),
  folders: () => request<Folder[]>("/api/folders"),
  createFolder: (draft: FolderDraft) => request<Folder>("/api/folders", jsonBody("POST", draft)),
  saveFolder: (folderId: string, draft: FolderDraft) => request<Folder>(`/api/folders/${id(folderId)}`, jsonBody("PUT", draft)),
  removeFolder: (folderId: string) => request<void>(`/api/folders/${id(folderId)}`, { method: "DELETE" }),
  documents: (filter: { folder?: string; asset?: string; kind?: string } = {}) => request<DocRow[]>(`/api/documents${query(filter)}`),
  document: (docId: string) => request<Doc>(`/api/documents/${id(docId)}`),
  /** The file is the body; the description goes in the query (the server reads the body as it comes). */
  send: (file: File, fields: Partial<SendFields>) => request<Doc>(
    `/api/documents${query({ filename: file.name, ...Object.fromEntries(Object.entries(fields).filter(([, value]) => value)) })}`,
    { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } },
  ),
  update: (docId: string, fields: Partial<Pick<Doc, "folder_id" | "number" | "title" | "description" | "kind" | "unit" | "language" | "assistant">>) =>
    request<Doc>(`/api/documents/${id(docId)}`, jsonBody("PATCH", fields)),
  setAssets: (docId: string, assets: string[]) => request<Doc>(`/api/documents/${id(docId)}/assets`, jsonBody("PUT", { assets })),
  reindex: (docId: string) => request<{ queued: boolean }>(`/api/documents/${id(docId)}/reindex`, { method: "POST" }),
  remove: (docId: string) => request<void>(`/api/documents/${id(docId)}`, { method: "DELETE" }),
  /** A Word file as a page: its text in a fixed set of tags, escaped by the server. */
  view: (docId: string) => request<{ revision: string; filename: string; html: string }>(`/api/documents/${id(docId)}/view`),
  passages: (docId: string, page?: number) => request<Passage[]>(`/api/documents/${id(docId)}/passages${query({ page: page ? String(page) : undefined })}`),
  /** The original file; a PDF shown inline opens at `page` (the browser's viewer reads `#page=`). */
  fileUrl: (docId: string, options: { revision?: string; inline?: boolean; page?: number } = {}) =>
    href(`/api/documents/${id(docId)}/file${query({ revision: options.revision, inline: options.inline ? "true" : undefined })}`) + (options.inline && options.page ? `#page=${options.page}` : ""),
  search: (body: { query: string; asset?: string; kind?: string; folder?: string; limit?: number }) =>
    request<{ query: string; passages: Hit[] }>("/api/search", jsonBody("POST", body)),
  diagrams: () => request<DiagramRow[]>("/api/diagrams"),
  diagram: (revId: string, page: number) => request<Diagram>(`/api/diagrams/${id(revId)}/${page}`),
  /** The page read again by the language model of "diagram-read" (an editor; 409 with no model). */
  readWithModel: (revId: string, page: number) => request<Diagram>(`/api/diagrams/${id(revId)}/${page}/read-with-model`, { method: "POST" }),
  /** The page drawn as a picture by the server (never the file itself in the page). */
  diagramImage: (revId: string, page: number) => href(`/api/diagrams/${id(revId)}/${page}/image`),
  plantMap: () => request<PlantMap>("/api/plant-map"),
  assetFileUrl: () => href("/api/plant-map/asset-file"),
  dexpiUrl: () => href("/api/plant-map/dexpi.xml"),
  /** Approve, reject or uncheck an item (its tag) or a relation (`from|type|to`) of the map. */
  review: (key: string, kind: "item" | "relation", verdict: Verdict) =>
    request<{ key: string; verdict: Verdict }>("/api/plant-map/reviews", jsonBody("PUT", { key, kind, verdict })),
  listUrl: (kind: "equipment" | "instruments" | "lines" | "loops") => href(`/api/plant-map/lists/${kind}.csv`),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
};
