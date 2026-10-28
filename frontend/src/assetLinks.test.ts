import { describe, expect, it } from "vitest";
import { appAssetHref, appsForAsset, assetPath, currentAssetPath } from "./assetLinks";
import type { SuiteAppCard } from "./types";

const app = (id: string, url: string, asset_types: string[] | null, access: SuiteAppCard["access"] = "viewer"): SuiteAppCard =>
  ({ id, name: id, url, version: null, access, asset_types });

describe("asset deep links", () => {
  it("an asset opens at /assets/<id>", () => {
    expect(assetPath("FIC-101")).toBe("/assets/FIC-101");
    expect(assetPath("a/b c")).toBe("/assets/a%2Fb%20c");
  });
  it("the old /plant addresses map to /assets", () => {
    expect(currentAssetPath("/plant")).toBe("/assets");
    expect(currentAssetPath("/plant/FIC-101")).toBe("/assets/FIC-101");
    expect(currentAssetPath("/plantx")).toBeNull();
    expect(currentAssetPath("/assets/FIC-101")).toBeNull();
  });
  it("an app's page for an asset is <prefix>assets/<id>", () => {
    expect(appAssetHref("/cpm/", "FIC-101")).toBe("/cpm/assets/FIC-101");
    expect(appAssetHref("http://127.0.0.1:8070/cpm", "FIC-101")).toBe("http://127.0.0.1:8070/cpm/assets/FIC-101");
  });
  it("links the apps that cover the asset's type (or an ancestor) and the ones with no manifest", () => {
    const apps = [
      app("cpmcraft", "/cpm/", ["loop"]),
      app("trendcraft", "/trend/", null),
      app("alarmcraft", "/alarm/", []),
      app("twincraft", "/twin/", ["equipment"]),
      app("datacraft", "/quality/", ["loop"], null),
    ];
    expect(appsForAsset(apps, "FIC-101", ["loop", "flow_loop"]).map((item) => item.href)).toEqual(["/cpm/assets/FIC-101", "/trend/assets/FIC-101"]);
    expect(appsForAsset(apps, "P-101", ["equipment", "pump"]).map((item) => item.id)).toEqual(["trendcraft", "twincraft"]);
  });
});
