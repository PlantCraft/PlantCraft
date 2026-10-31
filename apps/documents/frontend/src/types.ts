export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; service_key: boolean;
  /** The model that turns passages into vectors: "multilingual-e5-small", or "hash-384" without it. */
  embedder: string;
  /** The largest file the library takes, in MB. */
  max_file_mb?: number;
}

/** Who sees and who changes a folder: `user:<name>`, `group:<id>`; empty means everyone. */
export interface Folder {
  folder_id: string; name: string; description: string; viewers: string[]; editors: string[];
  /** May the assistant read its documents. */
  assistant: boolean; documents: number; can_edit: boolean;
}

export type Status = "queued" | "indexing" | "indexed" | "failed" | "superseded";

export interface Revision {
  rev_id: string; revision: string; issued: string; filename: string; sha256: string; size: number;
  format: string; pages: number; status: Status; error: string; embedder: string;
  uploaded_at: string; uploaded_by: string; indexed_at: string | null;
}

export interface DocAsset { asset_id: string; source: "manual" | "suggested"; mentions: number }

/** A row of the list: the document with its current revision's fields. */
export interface DocRow {
  doc_id: string; folder_id: string; number: string; title: string; description: string; kind: string; unit: string; language: string;
  assistant: boolean; created_at: string; created_by: string; updated_at: string; assets: DocAsset[];
  rev_id: string | null; revision: string | null; filename: string | null; format: string | null; pages: number | null;
  size: number | null; status: Status | null; error: string | null; uploaded_at: string | null;
}

export interface Doc extends Omit<DocRow, "rev_id" | "revision" | "filename" | "format" | "pages" | "size" | "status" | "error" | "uploaded_at"> {
  revisions: Revision[]; current: Revision | null; can_edit: boolean;
}

export interface Passage {
  passage_id: number; rev_id: string; doc_id: string; seq: number; text: string;
  page_from: number | null; page_to: number | null; section: string; assets: string[];
}

export interface Hit {
  ref: string; doc_id: string; passage_id: number; number: string; title: string; kind: string; revision: string;
  page: number | null; pages: [number | null, number | null]; section: string; text: string; assets: string[];
  score: number; found_by: string[]; url: string;
}


/** What a person sets for the files they send. */
export interface SendFields {
  folder: string; number: string; title: string; description: string; kind: string; unit: string; language: string; revision: string; issued: string;
}

/** A page of a document that is a diagram (P&ID), and what the drawing reader found on it. */
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
