import { ApiError, createApiClient, type HelpEntry, type HelpPage, jsonBody, saveFile } from "@plantcraft/ui";
import { t } from "./i18n";
import { href } from "./nav";
import type { AppMeta, ExportOptions, ExportPreview, ImportCheck, ImportItem, Me, ReadOptions, Overview, Point, RequestAnswer, RunInfo, RunsSeries, Series, Settings, Source, SourceSettings, Variable } from "./types";

const client = createApiClient({ app: "histcraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
const request = client.request;
const body = jsonBody;
const id = encodeURIComponent;

/** What a source form sends: `password` only when typed (null keeps the stored one). */
export type SourceIn = Pick<Source, "id" | "name" | "kind" | "endpoint" | "namespace_uri" | "username" | "password_env" | "options" | "enabled"> & SourceSettings & { mode: Source["mode"] | ""; password: string | null };

/** What each step of an export keeps. */
export type Aggregate = "mean" | "first" | "last" | "min" | "max";
/** What an export takes (``POST /api/export``): tags and assets (each with what is under it). */
export interface ExportChoice { signals: string[]; assets: string[]; expand_assets?: boolean; start?: string; end?: string; hours?: number; step_seconds?: number | null; aggregate?: Aggregate; anonymize: boolean }
/** A tag in the export list: what ``/api/export/resolve`` answers for an asset, or a tag picked by itself. */
export interface ExportTag { signal: string; tag: string; name: string; unit: string; archived: boolean; asset_id?: string; asset_name?: string; role?: string }
/** A choice saved under a name (``/api/export/saved``). A relative period has ``hours``; a fixed one ``start`` and ``end``. */
export interface SavedExportIn { name: string; signals: string[]; assets: string[]; hours: number | null; start: string | null; end: string | null; step_seconds: number | null; aggregate?: Aggregate; anonymize: boolean }
export interface SavedExport extends SavedExportIn { id: string; created_by: string; updated_by: string; created: string; updated: string }

/** The two example files of an import: one column per tag, or one value per line. */
export type ExampleShape = "wide" | "long";

/** What a downloaded package holds (its manifest's counts, sent as headers). */
export type Downloaded = { name: string; bytes: number; signals?: number; rows?: number; notRead?: number };

/** Saves an answer as a file under the name the server gave it. */
async function download(path: string, payload: unknown, fallback: string): Promise<Downloaded> {
  const response = await client.send(path, payload === undefined ? {} : body("POST", payload));
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? fallback;
  const blob = await response.blob();
  saveFile(name, blob);
  const count = (header: string) => { const value = response.headers.get(header); return value === null ? undefined : Number(value); };
  return { name, bytes: blob.size, signals: count("X-Package-Signals"), rows: count("X-Package-Rows"), notRead: count("X-Package-Not-Read") };
}

/** What a point list in CSV would do, or did (``POST /api/points/import``). */
export type PointsImport = {
  add: string[]; update: string[]; unchanged: string[];
  errors: { line: number; signal: string; message: string }[];
  added?: string[]; updated?: string[]; skipped?: { signal: string; reason: string }[];
};

export type NewPoint = Partial<Point> & { tag: string; source_id: string; address: string };

/** A point an admin removed, kept with its archive until ``purge_ms`` (``/api/points/retired``). */
export type RetiredPoint = { id: number; signal: string; source_id: string; tag: string; name: string; unit: string; kind: string; retired_ms: number; retired_by: string; purge_ms: number };

export const api = {
  me: () => request<Me>("/api/me"),
  meta: () => request<AppMeta>("/api/meta"),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
  point: (signal: string) => request<Point>(`/api/points/${id(signal)}`),
  overview: () => request<Overview>("/api/overview"),
  sources: () => request<Source[]>("/api/sources"),
  addSource: (source: SourceIn) => request<Source>("/api/sources", body("POST", source)),
  updateSource: (source: SourceIn) => request<Source>(`/api/sources/${id(source.id)}`, body("PUT", source)),
  exportPoints: (sourceId?: string) => download(`/api/points/export${sourceId ? `?source_id=${id(sourceId)}` : ""}`, undefined, "historian-points.csv"),
  importPoints: (file: File, apply: boolean) => request<PointsImport>(`/api/points/import?apply=${apply}`, { method: "POST", body: file, headers: { "Content-Type": "text/csv" } }),
  trustServer: (sourceId: string, thumbprint: string) => request<Source>(`/api/sources/${id(sourceId)}/trust`, body("POST", { thumbprint })),
  clientCertificate: () => download("/api/opcua/certificate", undefined, "plantcraft-historian.der"),
  deleteSource: (sourceId: string, withPoints = false) => request<void>(`/api/sources/${id(sourceId)}${withPoints ? "?with_points=true" : ""}`, { method: "DELETE" }),
  testSource: (sourceId: string) => request<{ request: number; collector: boolean }>(`/api/sources/${id(sourceId)}/test`, { method: "POST" }),
  backfillSource: (sourceId: string, hours: number) => request<{ request: number; collector: boolean }>(`/api/sources/${id(sourceId)}/backfill`, body("POST", { hours })),
  browseSource: (sourceId: string) => request<{ request: number; collector: boolean }>(`/api/sources/${id(sourceId)}/browse`, body("POST", {})),
  imports: () => request<ImportItem[]>("/api/imports"),
  // ``options``: how to read it (empty: detected); ``into``: the import it would join.
  checkImport: (file: File, timezone: string, options: Partial<ReadOptions> = {}, into = "") => request<ImportCheck>(`/api/imports/check?${new URLSearchParams({ name: file.name, timezone, options: JSON.stringify(options), ...(into ? { into } : {}) })}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  createImport: (token: string, name: string, into = "") => request<ImportItem>("/api/imports", body("POST", { token, name, into })),
  importExample: (shape: ExampleShape) => download(`/api/imports/example/${shape}.csv`, undefined, `historian-import-${shape}.csv`),
  // The same file, kept in the page: the import dialog opens with it, checked.
  exampleFile: async (shape: ExampleShape) => {
    const name = `historian-import-${shape}.csv`;
    const response = await client.send(`/api/imports/example/${shape}.csv`, {});
    return new File([await response.blob()], name, { type: "text/csv" });
  },
  repeatImport: (importId: string, pattern: string, checkMinutes: number) => request<ImportItem & { found: number }>(`/api/imports/${id(importId)}/repeat`, body("PUT", { pattern, check_minutes: checkMinutes })),
  cancelImport: (importId: string) => request<{ id: string; deleted: boolean }>(`/api/imports/${id(importId)}/cancel`, { method: "POST" }),
  deleteImport: (importId: string) => request<{ id: string; points: number }>(`/api/imports/${id(importId)}`, { method: "DELETE" }),
  answer: <T,>(requestId: number) => request<RequestAnswer<T>>(`/api/requests/${requestId}`),
  points: (q = "", source = "") => request<Point[]>(`/api/points?${new URLSearchParams({ q, ...(source ? { source } : {}) })}`),
  addPoints: (points: NewPoint[]) => request<{ added: string[]; skipped: { signal: string; tag: string; reason: string }[] }>("/api/points", body("POST", { points })),
  updatePoint: (signal: string, patch: Partial<Omit<Point, "mode" | "own_mode" | "scan_seconds" | "deviation" | "max_seconds" | "retention_days" | "exception">> & { mode?: Point["own_mode"]; scan_seconds?: number | null; deviation?: number | null; exception?: number | null; min_seconds?: number | null; max_seconds?: number | null; retention_days?: number | null }) => request<Point>(`/api/points/${id(signal)}`, body("PATCH", patch)),
  deletePoints: (signals: string[]) => request<{ removed: number; retired: number; days: number }>("/api/points/delete", body("POST", { signals })),
  retiredPoints: () => request<{ points: RetiredPoint[]; days: number }>("/api/points/retired"),
  restorePoints: (ids: number[]) => request<{ restored: string[]; refused: { id: number; signal?: string; reason: string }[] }>("/api/points/restore", body("POST", { ids })),
  purgePoints: (ids: number[], confirm: string) => request<{ purged: number }>("/api/points/purge", body("POST", { ids, confirm })),
  // ``extremes``: on a grid, each cell's lowest and highest value too (``low``, ``high``; up to a week).
  // A runs point (H2): its executions, and one run (an ISO run time) or the newest `count`.
  runList: (signal: string) => request<{ signal: string; runs: RunInfo[] }>(`/api/points/${id(signal)}/runs`),
  runs: (signal: string, pick: { run?: string; runs?: number }) =>
    request<RunsSeries>(`/api/points/${id(signal)}/series?${new URLSearchParams(pick.run ? { run: pick.run } : { runs: String(pick.runs ?? 1) })}`),
  series: (signal: string, start: string, end: string, step?: number, extremes = false) =>
    request<Series>(`/api/points/${id(signal)}/series?${new URLSearchParams({ start, end, ...(step ? { step: String(step) } : {}), ...(extremes ? { extremes: "true" } : {}) })}`),
  exportOptions: () => request<ExportOptions>("/api/export/options"),
  exportPreview: (choice: Pick<ExportChoice, "signals" | "assets" | "expand_assets">) => request<ExportPreview>("/api/export/preview", body("POST", choice)),
  exportPackage: (choice: ExportChoice) => download("/api/export", choice, "historian-package.zip"),
  exportKey: (choice: ExportChoice) => download("/api/export/key", choice, "historian-package-key.csv"),
  exportResolve: (assets: string[]) => request<{ tags: ExportTag[] }>("/api/export/resolve", body("POST", { assets })),
  savedExports: () => request<SavedExport[]>("/api/export/saved"),
  saveExport: (value: SavedExportIn) => request<SavedExport>("/api/export/saved", body("POST", value)),
  updateSavedExport: (exportId: string, value: SavedExportIn) => request<SavedExport>(`/api/export/saved/${id(exportId)}`, body("PUT", value)),
  deleteSavedExport: (exportId: string) => request<{ deleted: string }>(`/api/export/saved/${id(exportId)}`, { method: "DELETE" }),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (settings: Partial<Settings>) => request<Settings>("/api/settings", body("PUT", settings)),
};

/** Ask the collector something (browse, test) and wait for its answer. */
export async function askCollector<T>(start: () => Promise<{ request: number; collector: boolean }>, timeoutMs = 180_000): Promise<RequestAnswer<T>> {
  const { request: requestId } = await start();
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const answer = await api.answer<T>(requestId);
    if (answer.status !== "pending") return answer;
    await new Promise((resolve) => window.setTimeout(resolve, 800));
  }
  throw new ApiError(0, t("The collector did not answer. Check that it is running and reaches the plant network."));
}

export type BrowseResult = { variables: Variable[]; truncated: boolean; limit: number };
