export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; service_key: boolean;
}

/** The licence the app runs under (PlantCraft docs/app-package.md, section 8). */
export interface LicenseState {
  status: "valid" | "grace" | "expired" | "missing" | "invalid"; usable: boolean; message: string;
  days_left: number | null; customer: string | null; expires: string | null;
  limits: Record<string, number>; features: string[];
}

/** A P&ID and its current file. */
export interface Drawing {
  drawing_id: string; number: string; title: string; unit: string; created_at: string; created_by: string;
  rev_id: string | null; filename: string | null; format: string | null; size: number | null;
  status: "queued" | "reading" | "read" | "failed" | "superseded" | null; error: string | null;
  pages: number | null; diagrams: number; uploaded_at: string | null; uploaded_by: string | null;
}
export interface DrawingDetail extends Drawing { pages_read?: number; pages: number | null }

/** A page of a drawing that is a diagram (P&ID), and what the drawing reader found on it. */
export interface DiagramRow {
  rev_id: string; doc_id: string; page: number; sheet: string; title: string; unit: string; source: string;
  items: number; relations: number; doc_title: string; doc_number: string; format: string; filename: string;
}
export interface DrawnItem {
  id: string; tag: string; family: string; cls: string; label: string; box: [number, number, number, number];
  confidence: "high" | "medium" | "low"; why: string; ref_sheet?: string; ref_tag?: string;
}
export interface DrawnRelation { from: string; type: string; to: string; confidence: "high" | "medium" | "low"; why: string }
export interface Diagram extends Omit<DiagramRow, "items" | "relations"> {
  items: number; relations: number;
  /** The page's tags that PlantCraft has (null: PlantCraft not read). */
  in_plantcraft?: string[] | null;
  result: { sheet: string; unit: string; title: string; items: DrawnItem[]; relations: DrawnRelation[]; notes: string[]; width: number; height: number; source: string };
}
export interface MapPlace { doc_id: string; rev_id: string; page: number; sheet: string; doc_title: string; box: [number, number, number, number] }
export interface MapItem {
  tag: string; family: string; cls: string; unit: string; area: string; sheet: string;
  confidence: "high" | "medium" | "low"; why: string; places: MapPlace[]; in_plantcraft: boolean | null; review?: Verdict;
}
export type Verdict = "" | "approved" | "rejected";
export interface MapRelation { from: string; type: string; to: string; confidence: "high" | "medium" | "low"; why: string; sheets: string[]; review?: Verdict }
export interface MapSheet {
  doc_id: string; rev_id: string; page: number; sheet: string; doc_title: string; title: string; unit: string; source: string;
  width: number; height: number; items: Array<{ tag: string; family: string; cls: string; box: [number, number, number, number] }>;
}
export interface MapLoop { loop: string; transmitters: string[]; valves: string[]; equipment: string[]; unit: string; area: string; complete: boolean }
export interface PlantMap {
  items: MapItem[]; relations: MapRelation[]; loops: MapLoop[]; sheets: MapSheet[];
  rejected: Array<{ key: string; kind: "item" | "relation"; by: string }>;
  summary: {
    sheets: number; equipment: number; instruments: number; loops: number; loops_complete: number; feeds: number; relations: number;
    units: Array<{ unit: string; areas: string[]; equipment: Record<string, number>; loops: number; instruments: number }>;
    doubts: Array<{ tag: string; why: string }>; doubt_count: number; in_plantcraft: number | null; new: number | null;
  };
}
