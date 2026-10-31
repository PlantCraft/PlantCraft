export interface WorkspaceUser {
  username: string;
  display_name: string;
  role: string;
  active: number | boolean;
}
export type AccessLevel = "admin" | "editor" | "viewer" | "dashboards";
/** The person's access profile: level and applications (null: all). */
/** `admin_view`: reads the administration pages (People, Apps, Backups): administrators, and a
 * public demo's visitor, read-only. */
export interface AccessInfo { level: AccessLevel; label: string; applications: string[] | null; can_edit: boolean; is_admin: boolean; admin_view?: boolean; /** Opens Operations (an admin, or the Operations role). */ can_operate?: boolean; /** Temporary support access: when it ends. */ support_until?: string | null; }
export interface SessionInfo { authenticated: boolean; username?: string | null; display_name?: string | null; role?: string | null; can_switch_user?: boolean; is_admin?: boolean; access?: AccessInfo | null; public_demo?: { seats: number; minutes: number; contact_url?: string } | null; demo_visit?: { seconds_left: number; minutes: number } | null; installation?: Installation | null; }
/** The installation the sign-in page names: its plant and version. */
export interface Installation { name: string; version: string }
/** What a person says about themselves; every field may be empty. */
export interface Profile { job_title: string; affiliation: "" | "internal" | "external"; organization: string; email: string; phone: string; unit: string }
export type AppRole = "viewer" | "editor";
export interface UserAccount { username: string; display_name: string; role: string; active: boolean; access_level: AccessLevel; access_label: string; applications: string[] | null; app_roles?: Record<string, AppRole>; profile?: Profile; has_password: boolean; auth_source?: "local" | "ldap" | "oidc"; environment_admin: boolean; groups?: string[]; asset_scope?: string[] | null; asset_roots?: string[] | null; }
/** A person's page: anyone signed in sees who they are and what they own; access only themselves and admins. */
export interface PersonCard { username: string; display_name: string; role: string; active: boolean; profile: Profile; is_me: boolean; actions: Array<{ action_id: number; title: string; status: string; status_label: string; due_at: string | null; overdue: boolean }>; access?: UserAccount; apps?: Array<{ application_id: string; name: string; role: AppRole }>; groups?: Array<{ group_id: string; name: string; kind: string; kind_label: string; coordinator: boolean }> }
export interface UserAccounts { users: UserAccount[]; levels: Array<{ id: AccessLevel; label: string }>; applications: Array<{ application_id: string; name: string }>; groups?: Array<{ group_id: string; name: string; kind_label: string }>; sign_in: boolean; }

export type SourceType = "opcua" | "pi_web_api" | "csv";
export interface MapIssue { sheet: string; line: number | null; level: "error" | "warning"; message: string }
export interface MapSectionSummary { name: string; label: string; rows: number; create: number; update: number; unchanged: number; remove: number }
export interface MapReport {
  file: string;
  sections: MapSectionSummary[];
  issues: MapIssue[];
  errors: number;
  warnings: number;
  changes: Array<{ section: string; action: "create" | "update" | "remove"; key: string }>;
  can_apply: boolean;
  prune: boolean;
  applied?: boolean;
}
export interface MapFormatSection { name: string; label: string; columns: Array<{ name: string; required: boolean; description: string }> }
/** ``GET /api/home``: the installation, people, counts and the apps of the suite. */
/** ``asset_types``: the types the app shows at <url>assets/<id> (its manifest); null when PlantCraft has not seen its manifest. */
export interface SuiteAppCard { id: string; name: string; url: string; version: string | null; access: "editor" | "viewer" | null; asset_types: string[] | null }
export interface HomeJourney {
  last_run: { app: string; id: string; name: string; status: string; started_at: string | null; finished_at: string | null; updated_at: string } | null;
  schedules: number;
  findings: Record<string, { alarm?: number; warning?: number; unknown?: number; total: number }>;
  actions: { open: number; overdue: number; done: number; total: number };
}
/** One result that needs someone (``GET /api/home`` ``attention``): alarm first, lowest score first. */
export interface HomeAttention { app: string; subject: string; subject_kind: string; name: string; kind: string; status: string; score: number | null; value: number | null; summary: string; at: string; url: string | null }
/** Home's quick status (``/api/home/status``): apps online, the Historian's connections. */
export type LiveState = "online" | "offline" | "off" | "unknown";
export interface HomeStatus {
  at: string;
  apps: Array<{ id: string; name: string; url: string; state: LiveState; detail: string; seen_at: string | null }>;
  historian: { kind: "histcraft" | "local"; ok: boolean; detail: string; sources: Array<{ id: string; name: string; type: string; state: LiveState; detail: string }> };
}
export interface HomeData {
  version?: string;
  scenario: { name: string; display_name: string; description: string };
  source: { type: SourceType; label: string; names: string[] };
  users: WorkspaceUser[];
  counts: { sources: number; signals: number; assets: Record<string, number>; users: number };
  apps: SuiteAppCard[];
  /** Home's path: the apps' last run, enabled schedules, subjects by worst status per app, actions. */
  journey?: HomeJourney;
  /** What needs someone now, across the apps (Home's first list). */
  attention?: HomeAttention[];
  /** A public demo (PLANTCRAFT_PUBLIC_DEMO); demo_tour: the demo story is here (`processcraft demo seed`). */
  public_demo?: boolean;
  demo_tour?: boolean;
}
