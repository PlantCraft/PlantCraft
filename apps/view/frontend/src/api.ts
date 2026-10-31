import { createApiClient, jsonBody, query, type HelpEntry, type HelpPage } from "@plantcraft/ui";
import { href } from "./nav";
import type { Analysis, AssistantSpec, AssistantVersion, AssistantWritten, EventKind, Report, ReportDraft, ReportRun, Section, SectionData, AssetDashboards, Directory, Folder, FolderDraft, ResultKind, Template, Version, AssetKind, AssetOption, Card, CardData, Dashboard, DashboardDraft, Me, ShareLink, ShareTarget, ExportFormat, SignalOption, Trend, TrendData, TrendView, Variable, VariableOption } from "./types";

const client = createApiClient({ app: "dashcraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
export const request = client.request;
const body = jsonBody;
const id = encodeURIComponent;

/** The values picked for a dashboard's variables, as `var-<name>` query parameters. */
export function varsQuery(vars: Record<string, string[]>, window: string | null): string {
  const params = new URLSearchParams();
  for (const [name, values] of Object.entries(vars)) for (const value of values) params.append(`var-${name}`, value);
  if (window) params.set("window", window);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Where a dashboard page reads its cards and its pickers: as a signed-in person, or through a public link. */
export interface CardSource {
  card: (cardId: string, vars: Record<string, string[]>, window: string | null) => Promise<CardData>;
  options: (variable: Variable, parents: string[]) => Promise<VariableOption[]>;
}

function parentsQuery(parents: string[]): string {
  const params = new URLSearchParams();
  for (const parent of parents) params.append("parent", parent);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const api = {
  me: () => request<Me>("/api/me"),
  dashboards: () => request<Dashboard[]>("/api/dashboards"),
  dashboard: (dashboardId: string) => request<Dashboard>(`/api/dashboards/${id(dashboardId)}`),
  create: (draft: DashboardDraft) => request<Dashboard>("/api/dashboards", body("POST", draft)),
  templates: () => request<Template[]>("/api/templates"),
  folders: () => request<Folder[]>("/api/folders"),
  createFolder: (draft: FolderDraft) => request<Folder>("/api/folders", body("POST", draft)),
  saveFolder: (folderId: string, draft: FolderDraft) => request<Folder>(`/api/folders/${id(folderId)}`, body("PUT", draft)),
  removeFolder: (folderId: string) => request<void>(`/api/folders/${id(folderId)}`, { method: "DELETE" }),
  directory: () => request<Directory>("/api/directory"),
  versions: (dashboardId: string) => request<Version[]>(`/api/dashboards/${id(dashboardId)}/versions`),
  restore: (dashboardId: string, version: number) => request<Dashboard>(`/api/dashboards/${id(dashboardId)}/versions/${version}/restore`, { method: "POST" }),
  save: (dashboardId: string, draft: DashboardDraft, baseUpdatedAt?: string | null) => request<Dashboard>(`/api/dashboards/${id(dashboardId)}`, body("PUT", { ...draft, base_updated_at: baseUpdatedAt ?? null })),
  copy: (dashboardId: string) => request<Dashboard>(`/api/dashboards/${id(dashboardId)}/copy`, { method: "POST" }),
  remove: (dashboardId: string) => request<void>(`/api/dashboards/${id(dashboardId)}`, { method: "DELETE" }),
  preview: (card: Card, variables: Variable[], values: Record<string, string[]>, window: string | null) => request<CardData>("/api/preview", body("POST", { card, variables, values, window })),
  variableOptions: (variable: Variable, parent: string[]) => request<VariableOption[]>("/api/variable-options", body("POST", { variable, parent })),
  assets: (kind?: string | null, q?: string) => request<AssetOption[]>(`/api/assets${query({ kind, q })}`),
  assetKinds: () => request<AssetKind[]>("/api/asset-kinds"),
  signals: (q: string) => request<SignalOption[]>(`/api/signals${query({ q, limit: "30" })}`),
  assetDashboards: (assetId: string) => request<AssetDashboards>(`/api/asset-dashboards${query({ asset: assetId })}`),
  resultKinds: (kind?: string | null) => request<ResultKind[]>(`/api/result-kinds${query({ kind })}`),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
  /** Public links of a dashboard or a report (`target`). */
  shares: (targetId: string, target: ShareTarget = "dashboard") => request<ShareLink[]>(`/api/${target}s/${id(targetId)}/shares`),
  createShare: (targetId: string, label: string, target: ShareTarget = "dashboard", days: number | null = 90) => request<ShareLink>(`/api/${target}s/${id(targetId)}/shares`, body("POST", { label, days })),
  /** Every link that still opens something (administrators only). */
  allShares: () => request<ShareLink[]>("/api/shares"),
  revokeAnyShare: (shareId: string) => request<void>(`/api/shares/${id(shareId)}`, { method: "DELETE" }),
  revokeShare: (targetId: string, shareId: string, target: ShareTarget = "dashboard") => request<void>(`/api/${target}s/${id(targetId)}/shares/${id(shareId)}`, { method: "DELETE" }),
  trends: () => request<Trend[]>("/api/trends"),
  trend: (trendId: string) => request<Trend>(`/api/trends/${id(trendId)}`),
  trendData: (view: TrendView) => request<TrendData>("/api/trends/data", body("POST", view)),
  createTrend: (trend: TrendView & { name: string; description?: string }) => request<Trend>("/api/trends", body("POST", trend)),
  saveTrend: (trendId: string, trend: TrendView & { name: string; description?: string }) => request<Trend>(`/api/trends/${id(trendId)}`, body("PUT", trend)),
  removeTrend: (trendId: string) => request<void>(`/api/trends/${id(trendId)}`, { method: "DELETE" }),
  reports: () => request<Report[]>("/api/reports"),
  report: (reportId: string) => request<Report>(`/api/reports/${id(reportId)}`),
  createReport: (draft: ReportDraft) => request<Report>("/api/reports", body("POST", draft)),
  saveReport: (reportId: string, draft: ReportDraft, baseUpdatedAt?: string | null) => request<Report>(`/api/reports/${id(reportId)}`, body("PUT", { ...draft, base_updated_at: baseUpdatedAt ?? null })),
  copyReport: (reportId: string) => request<Report>(`/api/reports/${id(reportId)}/copy`, { method: "POST" }),
  removeReport: (reportId: string) => request<void>(`/api/reports/${id(reportId)}`, { method: "DELETE" }),
  reportSection: (reportId: string, sectionId: string, period: string | null) => request<SectionData>(`/api/reports/${id(reportId)}/sections/${id(sectionId)}${query({ period })}`),
  reportPreview: (section: Section, period: string) => request<SectionData>("/api/report-preview", body("POST", { section, period })),
  eventKinds: () => request<EventKind[]>("/api/event-kinds"),
  analyses: () => request<Analysis[]>("/api/report-analyses"),
  proposeScope: (description: string) => request<{ asset_ids: string[]; analyses: string[]; why: string; dropped: string[] }>("/api/report-assistant/scope", body("POST", { description })),
  assistantHistory: (reportId: string, sectionId: string) => request<{ assistant: AssistantSpec; drafts: AssistantWritten[]; versions: AssistantVersion[] }>(`/api/reports/${id(reportId)}/assistant/${id(sectionId)}`),
  assistantFeedback: (reportId: string, sectionId: string, feedback: string, runId: string | null) => request<{ version: number; requirements: string; previous: string; versions: AssistantVersion[] }>(`/api/reports/${id(reportId)}/assistant/${id(sectionId)}/feedback`, body("POST", { feedback, run_id: runId })),
  assistantRequirements: (reportId: string, sectionId: string, requirements: string) => request<{ version: number; requirements: string; versions: AssistantVersion[] }>(`/api/reports/${id(reportId)}/assistant/${id(sectionId)}/requirements`, body("PUT", { requirements })),
  reportRuns: (reportId: string) => request<ReportRun[]>(`/api/reports/${id(reportId)}/runs`),
  /** A new report's start from a dashboard: its pages as headings, its cards as cells. */
  dashboardAsReport: (dashboardId: string) => request<Pick<ReportDraft, "name" | "description" | "folder_id" | "sections">>(`/api/dashboards/${id(dashboardId)}/as-report`),
  makePdf: (reportId: string) => request<ReportRun>(`/api/reports/${id(reportId)}/pdf`, { method: "POST" }),
  sendReport: (reportId: string) => request<ReportRun>(`/api/reports/${id(reportId)}/send`, { method: "POST" }),
  source: (dashboardId: string): CardSource => ({
    card: (cardId, vars, window) => request<CardData>(`/api/dashboards/${id(dashboardId)}/cards/${id(cardId)}${varsQuery(vars, window)}`),
    options: (variable, parents) => request<VariableOption[]>(`/api/dashboards/${id(dashboardId)}/variables/${id(variable.name)}${parentsQuery(parents)}`),
  }),
};

/** A run's PDF, opened in the browser (or saved, `download`); the session cookie signs it. */
/** The report read now as a Word, HTML or Markdown file (a download link). */
export function exportUrl(reportId: string, form: ExportFormat): string {
  return href(`/api/reports/${id(reportId)}/export/${form}`);
}

export function pdfUrl(run: Pick<ReportRun, "report_id" | "run_id">, download = false): string {
  return href(`/api/reports/${id(run.report_id)}/runs/${id(run.run_id)}/pdf${download ? "?download=1" : ""}`);
}

/** A public link: no sign-in, no token renewal. */
export const publicApi = {
  dashboard: (token: string) => request<Dashboard>(`/api/public/${id(token)}`, undefined, { signedIn: false }),
  source: (token: string): CardSource => ({
    card: (cardId, vars, window) => request<CardData>(`/api/public/${id(token)}/cards/${id(cardId)}${varsQuery(vars, window)}`, undefined, { signedIn: false }),
    options: (variable, parents) => request<VariableOption[]>(`/api/public/${id(token)}/variables/${id(variable.name)}${parentsQuery(parents)}`, undefined, { signedIn: false }),
  }),
};
