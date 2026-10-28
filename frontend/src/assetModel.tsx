/** The asset model in the interface: types, records, relations and signal roles (see docs/api-v1.md). */
import { Box } from "lucide-react";
import { TYPE_ICONS } from "./typeIcons";
import { requestJson } from "./api";
import { language, t } from "./i18n";
import { suiteApi } from "./suiteApi";

export type DataType = "text" | "number" | "choice" | "date" | "asset";
export type AttributeValue = string | number | null;

export interface TypeAttribute { key: string; name: string; data_type: DataType; unit: string; required: boolean; default: AttributeValue; options: string[]; from?: string }
export interface TypeRole { key: string; name: string; unit: string; required: boolean; from?: string }
export interface AssetType {
  id: string;
  name: string;
  description: string;
  icon: string;
  parent: string | null;
  path: string[];
  attributes: TypeAttribute[];
  roles: TypeRole[];
  children: string[];
  own_children?: string[];
  builtin?: boolean;
  count?: number;
  total?: number;
  updated_at?: string | null;
  updated_by?: string | null;
}
export interface RelationKind { id: string; label: string; inverse: string }
export interface TypeCatalog { types: AssetType[]; data_types: DataType[]; relations: RelationKind[] }
export interface RelatedAsset { asset_id: string; name: string; kind: string; kind_label: string }
export interface RelationRow { type: string; label: string; origin: string; created_at: string; created_by: string; asset: RelatedAsset }
export interface AssetRelations { outgoing: RelationRow[]; incoming: RelationRow[] }
export interface Missing { attributes: string[]; roles: string[] }
export interface TypeDefinition { id?: string; name: string; description: string; icon: string; parent: string | null; attributes: TypeAttribute[]; roles: TypeRole[]; children: string[] }
export interface CatalogSignal { id: string; name: string; unit: string; source: string; description: string }

const enc = encodeURIComponent;

export const modelApi = {
  types: () => requestJson<TypeCatalog>("/api/asset-types"),
  type: (id: string) => requestJson<AssetType>(`/api/asset-types/${enc(id)}`),
  createType: (definition: TypeDefinition) => requestJson<AssetType>("/api/asset-types", { method: "POST", body: JSON.stringify(definition) }),
  updateType: (id: string, definition: TypeDefinition) => requestJson<AssetType>(`/api/asset-types/${enc(id)}`, { method: "PUT", body: JSON.stringify(definition) }),
  deleteType: (id: string) => noContent(`/api/asset-types/${enc(id)}`),
  setAttributes: (assetId: string, values: Record<string, AttributeValue>) =>
    requestJson<{ attributes: Record<string, AttributeValue>; changes: unknown[]; missing: Missing }>(`/api/assets/${enc(assetId)}/attributes`, { method: "PATCH", body: JSON.stringify({ values }) }),
  addRelation: (assetId: string, type: string, to: string) => requestJson<AssetRelations>(`/api/assets/${enc(assetId)}/relations`, { method: "POST", body: JSON.stringify({ type, to }) }),
  removeRelation: (assetId: string, type: string, to: string) => noContent(`/api/assets/${enc(assetId)}/relations?${new URLSearchParams({ type, to })}`),
  bindSignal: (assetId: string, signalId: string, role: string) => requestJson<unknown>(`/api/assets/${enc(assetId)}/signals`, { method: "POST", body: JSON.stringify({ signal_id: signalId, role }) }),
  unbindSignal: (assetId: string, signalId: string) => noContent(`/api/assets/${enc(assetId)}/signals?${new URLSearchParams({ signal_id: signalId })}`),
  /** The signal catalog of every source (API v1), for "Bind signal". */
  searchSignals: async (q: string) => {
    const { token } = await suiteApi.renewToken();
    return requestJson<CatalogSignal[]>(`/api/v1/signals?${new URLSearchParams({ q })}`, { headers: { Authorization: `Bearer ${token}` } });
  },
};

async function noContent(path: string) {
  let response: Response;
  try {
    response = await fetch(path, { method: "DELETE", credentials: "same-origin", headers: { "X-Language": language } });
  } catch {
    throw new Error(t("Couldn't connect to the server."));
  }
  if (!response.ok) throw new Error(((await response.json().catch(() => null)) as { detail?: string } | null)?.detail ?? t("Couldn't complete the operation."));
}

export { ICON_GROUPS, TYPE_ICONS } from "./typeIcons";
const KIND_ICONS: Record<string, string> = { site: "building", unit: "factory", area: "map-pin", loop: "gauge", equipment: "box" };

export function TypeIcon({ icon, kind, size = 15 }: { icon?: string | null; kind?: string; size?: number }) {
  const Icon = TYPE_ICONS[icon || KIND_ICONS[kind ?? ""] || "box"] ?? Box;
  return <Icon size={size} />;
}

export const DATA_TYPE_LABELS: Record<DataType, string> = { text: t("Text"), number: t("Number"), choice: t("Choice"), date: t("Date"), asset: t("Asset") };

/** A value as people read it: the number with its unit, or the text. */
export function showValue(value: AttributeValue | undefined, attribute?: TypeAttribute) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return `${value.toLocaleString()}${attribute?.unit ? ` ${attribute.unit}` : ""}`;
  return attribute?.unit && attribute.data_type === "number" ? `${value} ${attribute.unit}` : String(value);
}

/** Types by id, and every type under one (itself included). */
export function typeIndex(types: AssetType[]) {
  const byId = new Map(types.map((item) => [item.id, item]));
  const under = (id: string) => new Set(types.filter((item) => item.path.includes(id)).map((item) => item.id));
  return { byId, under };
}
