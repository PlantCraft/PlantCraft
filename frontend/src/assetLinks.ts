/** Asset deep links (docs/app-standard.md, section 2): PlantCraft shows an asset at /assets/<id>,
 * and every app that works on assets shows its own page for it at <prefix>assets/<id>. */
import type { SuiteAppCard } from "./types";

export const ASSETS_PATH = "/assets";

/** PlantCraft's page for one asset. */
export function assetPath(assetId: string) {
  return `${ASSETS_PATH}/${encodeURIComponent(assetId)}`;
}

/** The asset pages' old address (/plant, /plant/<id>) under the current one, or null. */
export function currentAssetPath(path: string): string | null {
  if (path === "/plant") return ASSETS_PATH;
  if (path.startsWith("/plant/")) return `${ASSETS_PATH}/${path.slice(7)}`;
  return null;
}

/** An app's page for this asset: its address plus assets/<id>. */
export function appAssetHref(appUrl: string, assetId: string) {
  return `${appUrl.endsWith("/") ? appUrl : `${appUrl}/`}assets/${encodeURIComponent(assetId)}`;
}

/** The apps the asset page links to, in launcher order. An app is linked when this person may
 * open it and either its manifest lists the asset's type or a type it descends from
 * (`[requires] asset_types`), or PlantCraft has not seen its manifest (`asset_types` null:
 * PLANTCRAFT_APPS or an external app), in which case the app itself says whether it covers
 * the asset. */
export function appsForAsset(apps: SuiteAppCard[], assetId: string, typePath: string[]) {
  return apps
    .filter((app) => app.access && (app.asset_types == null || app.asset_types.some((kind) => typePath.includes(kind))))
    .map((app) => ({ id: app.id, name: app.name, href: appAssetHref(app.url, assetId) }));
}

/** Sources and signals live in the Historian (owner, 2026-10-23); null when it is not installed. */
export function sourcesUrl(data: { apps: Array<{ id: string; url: string; access?: string | null }> }): string | null {
  const hist = data.apps.find((app) => app.id === "histcraft" && app.access);
  return hist ? `${hist.url.replace(/\/?$/, "/")}sources` : null;
}
