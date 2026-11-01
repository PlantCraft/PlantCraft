import { createApiClient, jsonBody, query, type HelpEntry, type HelpPage } from "@plantcraft/ui";
import { href } from "./nav";
import type { Diagram, DiagramRow, Drawing, LicenseState, Me, PlantMap, Verdict } from "./types";

const client = createApiClient({ app: "pidcraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
const request = client.request;
const id = encodeURIComponent;

export interface DrawingFields { number?: string; title?: string; unit?: string }

export const api = {
  me: () => request<Me>("/api/me"),
  license: () => request<LicenseState>("/api/license"),
  drawings: () => request<Drawing[]>("/api/drawings"),
  drawing: (drawingId: string) => request<Drawing & { pages: DiagramRow[] }>(`/api/drawings/${id(drawingId)}`),
  /** The file as the body, its name and fields in the query (as PlantCraft's own uploads). */
  send: (file: File, fields: DrawingFields) =>
    request<Drawing>(`/api/drawings${query({ filename: file.name, ...fields })}`, {
      method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" },
    }),
  readAgain: (drawingId: string) => request<Drawing>(`/api/drawings/${id(drawingId)}/read`, { method: "POST" }),
  remove: (drawingId: string) => request<{ deleted: boolean }>(`/api/drawings/${id(drawingId)}`, { method: "DELETE" }),
  diagrams: () => request<DiagramRow[]>("/api/diagrams"),
  diagram: (revId: string, page: number) => request<Diagram>(`/api/diagrams/${id(revId)}/${page}`),
  /** The page read again by the language model of "diagram-read" (an editor; 409 with no model). */
  readWithModel: (revId: string, page: number) => request<Diagram>(`/api/diagrams/${id(revId)}/${page}/read-with-model`, { method: "POST" }),
  diagramImage: (revId: string, page: number) => href(`/api/diagrams/${id(revId)}/${page}/image`),
  plantMap: () => request<PlantMap>("/api/plant-map"),
  assetFileUrl: () => href("/api/plant-map/asset-file"),
  dexpiUrl: () => href("/api/plant-map/dexpi.xml"),
  summaryUrl: () => href("/api/plant-map/summary.md"),
  review: (key: string, kind: "item" | "relation", verdict: Verdict) =>
    request<{ key: string; verdict: Verdict }>("/api/plant-map/reviews", jsonBody("PUT", { key, kind, verdict })),
  listUrl: (kind: "equipment" | "instruments" | "lines" | "loops") => href(`/api/plant-map/lists/${kind}.csv`),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
};
