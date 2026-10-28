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
