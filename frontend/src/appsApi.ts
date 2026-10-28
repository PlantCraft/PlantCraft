/** The Apps page API (/api/apps, administrators only); see docs/app-package.md. */
import { requestJson } from "./api";

export type AppOrigin = "configured" | "package" | "catalog" | "external";
export interface Permission { id: string; label: string }
export interface Publisher { id?: string; name?: string; key_id?: string }
export interface Health { ok: boolean | null; status: number | null; detail: string; checked_at: string }
/** What an app adds to PlantCraft, counted by kind (its [contributes] and series; docs/app-standard.md, 4b). */
export type Adds = Record<string, number>;
export interface InstalledApp {
  id: string; name: string; version: string | null; url: string; origin: AppOrigin; status: string; message: string; summary?: string;
  publisher: Publisher; permissions: Permission[]; previous_version: string | null; has_sbom: boolean; needs_key: boolean;
  health: Health | null; installed_by?: string | null; installed_at?: string | null; request_id?: string; warning?: string; app_key?: string;
  /** null: the app has not told PlantCraft yet (it sends it when it starts). */
  adds?: Adds | null; adds_unknown?: string[];
}
export interface AppsOverview {
  install_enabled: boolean;
  installer: { online: boolean; last_seen: string | null };
  catalog: { enabled: boolean; configured: boolean; switch: boolean; url: string | null };
  trusted_publishers: string[];
  max_mb: number;
  apps: InstalledApp[];
}
export interface SbomSummary { format: string; name: string; created: string; packages: number; components: { name: string; version: string; license: string }[] }
export interface PackagePreview {
  upload_id: string; origin: AppOrigin; replaces: string | null; warnings: string[];
  installer: { online: boolean; last_seen: string | null };
  app: {
    id: string; name: string; version: string; category: string; summary: string; description: string; license: string;
    prefix: string; port: number; uid: number; image: string; image_id: string;
    publisher: Publisher; permissions: Permission[]; plant_write: boolean; outbound: string[]; sha256: string; size: number;
    adds?: Adds;
  };
  sbom: SbomSummary;
}
export interface CatalogEntry { id: string; name: string; version: string; summary?: string; description: string; publisher: Publisher; size: number; installed_version: string | null }
export interface Catalog { enabled: boolean; configured?: boolean; apps: CatalogEntry[]; how?: string }

const post = (body?: unknown): RequestInit => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const id = (value: string) => encodeURIComponent(value);

export const appsApi = {
  overview: () => requestJson<AppsOverview>("/api/apps"),
  upload: (file: Blob) => requestJson<PackagePreview>("/api/apps/packages", { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  install: (uploadId: string) => requestJson<InstalledApp>(`/api/apps/packages/${id(uploadId)}/install`, post()),
  discard: (uploadId: string) => requestJson<{ ok: boolean }>(`/api/apps/packages/${id(uploadId)}`, { method: "DELETE" }),
  catalog: () => requestJson<Catalog>("/api/apps/catalog"),
  switchCatalog: (enabled: boolean) => requestJson<AppsOverview["catalog"]>("/api/apps/catalog", { method: "PUT", body: JSON.stringify({ enabled }) }),
  download: (appId: string, version?: string) => requestJson<PackagePreview>(`/api/apps/catalog/${id(appId)}/download`, post(version ? { version } : {})),
  registerExternal: (body: { id: string; name: string; url: string; version: string | null }) => requestJson<InstalledApp>("/api/apps/external", post(body)),
  check: (appId: string) => requestJson<InstalledApp>(`/api/apps/${id(appId)}/check`, post()),
  uninstall: (appId: string) => requestJson<InstalledApp>(`/api/apps/${id(appId)}/uninstall`, post()),
  rollback: (appId: string) => requestJson<InstalledApp>(`/api/apps/${id(appId)}/rollback`, post()),
  giveKey: (appId: string) => requestJson<InstalledApp>(`/api/apps/${id(appId)}/key`, post()),
  sbomUrl: (appId: string) => `/api/apps/${id(appId)}/sbom`,
  packageSbomUrl: (uploadId: string) => `/api/apps/packages/${id(uploadId)}/sbom`,
};

/** Setup › Apps: what the apps declare in [[contributes.settings]] and [[contributes.setup]]. */
export type AppSetting = { key: string; title: string; help: string; type: "text" | "number" | "integer" | "boolean" | "choice"; default?: string | number | boolean | null; options: string[]; min: number | null; max: number | null; unit: string; secret: boolean; value: string | number | boolean | null; changed: boolean; set?: boolean };
export type AppSetupPage = { title: string; path: string; description: string };
export type SetupApp = { app: string; name: string; version: string; settings: AppSetting[]; pages: AppSetupPage[] };
export const setupAppsApi = {
  list: () => requestJson<{ apps: SetupApp[] }>("/api/setup/apps"),
  save: (app: string, values: Record<string, unknown>) => requestJson<SetupApp>(`/api/setup/apps/${encodeURIComponent(app)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }) }),
};
