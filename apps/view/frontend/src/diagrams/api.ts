/** The routes of View › Diagrams (`api/routers/diagrams.py`). */
import { jsonBody, query } from "@plantcraft/ui";
import { request } from "../api";
import type { PublicDiagram } from "../types";
import type { Diagram, DiagramData, DiagramDraft, DiagramSummary, SymbolDef } from "./model";

const id = encodeURIComponent;

export interface DiagramVersion { version: number; saved_by: string | null; saved_at: string; name: string; elements: number }

/** A drawing that is not saved yet, and what was left out or changed on the way. */
export interface DiagramStart { diagram: DiagramDraft; notes: string[] }

export const diagramsApi = {
  symbols: () => request<SymbolDef[]>("/api/diagram-symbols"),
  list: () => request<DiagramSummary[]>("/api/diagrams"),
  get: (diagramId: string) => request<Diagram>(`/api/diagrams/${id(diagramId)}`),
  create: (draft: DiagramDraft) => request<Diagram>("/api/diagrams", jsonBody("POST", draft)),
  save: (diagramId: string, draft: DiagramDraft, baseUpdatedAt?: string | null) => request<Diagram>(`/api/diagrams/${id(diagramId)}`, jsonBody("PUT", { ...draft, base_updated_at: baseUpdatedAt ?? null })),
  remove: (diagramId: string) => request<void>(`/api/diagrams/${id(diagramId)}`, { method: "DELETE" }),
  versions: (diagramId: string) => request<DiagramVersion[]>(`/api/diagrams/${id(diagramId)}/versions`),
  version: (diagramId: string, version: number) => request<{ version: number; diagram: DiagramDraft }>(`/api/diagrams/${id(diagramId)}/versions/${version}`),
  data: (diagramId: string, window: string | null, end: string | null, page?: string | null) => request<DiagramData>(`/api/diagrams/${id(diagramId)}/data${query({ window, end, page: page || null })}`),
  preview: (diagram: DiagramDraft, window: string | null) => request<DiagramData>("/api/diagrams/preview", jsonBody("POST", { diagram, window })),
  drawFromAssets: (unitId: string) => request<DiagramStart>("/api/diagrams/draw-from-assets", jsonBody("POST", { unit_id: unitId })),
  drawPlant: () => request<DiagramStart>("/api/diagrams/draw-plant", { method: "POST" }),
  draft: (description: string, unitId: string | null) => request<DiagramStart>("/api/diagrams/draft", jsonBody("POST", { description, unit_id: unitId })),
  assetSignals: (assetId: string) => request<Array<{ role: string; signal: string }>>(`/api/diagram-assets/${id(assetId)}/signals`),
};

/** A diagram's public link (`share/diagram/<token>`): no sign-in, no token renewal. */
export const publicDiagramsApi = {
  get: (token: string) => request<PublicDiagram>(`/api/public/diagram/${id(token)}`, undefined, { signedIn: false }),
  data: (token: string, window: string | null, end: string | null, page?: string | null) => request<DiagramData>(`/api/public/diagram/${id(token)}/data${query({ window, end, page: page || null })}`, undefined, { signedIn: false }),
};
