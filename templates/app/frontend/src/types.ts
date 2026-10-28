export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; service_key: boolean;
}

/** With `follow_up` (a day) and `follow_up_by` (a username), the note is also on Desk's calendar
 * and in that person's to-do (app.toml [contributes]). */
export interface NoteDraft { asset_id: string; text: string; follow_up?: string | null; follow_up_by?: string | null }

export interface Note extends NoteDraft {
  note_id: string; created_at: string; created_by: string; updated_at: string; updated_by: string;
  /** The asset's name in PlantCraft (on the note's own page and after a change). */
  asset_name?: string;
}
