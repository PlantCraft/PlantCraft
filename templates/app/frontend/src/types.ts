export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; service_key: boolean;
}

/** What a person sends: the same fields as NoteDraft in src/starter/notes/models.py. */
export interface NoteDraft { asset_id: string; text: string }

export interface Note extends NoteDraft {
  note_id: string; created_at: string; created_by: string; updated_at: string; updated_by: string;
  /** The asset's name in PlantCraft (on the note's own page and after a change). */
  asset_name?: string;
}
