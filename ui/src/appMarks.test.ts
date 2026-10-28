import { describe, expect, it } from "vitest";
import { APP_COLORS, APP_GLYPHS, APP_IDS, APP_NAMES, appDisplayName, appFullName, appIdFor, isFamilyApp, appLabel, appShortName, markSvg } from "./appMarks";

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe("apps outside the family", () => {
  it("are told apart from the family and keep their own name", () => {
    expect(isFamilyApp("linkcraft")).toBe(true);
    expect(isFamilyApp("starter")).toBe(false);
    expect(appDisplayName("linkcraft", "Anything")).toBe("Analytics");
    expect(appDisplayName("starter", "StarterCraft")).toBe("StarterCraft");
    expect(appDisplayName("starter")).toBe("starter");
  });
});

describe("app family", () => {
  it("every app has a name, a glyph and a colour per theme", () => {
    for (const id of APP_IDS) {
      expect(APP_NAMES[id]).toBeTruthy();
      expect(APP_GLYPHS[id].length).toBeGreaterThan(0);
      expect(APP_COLORS[id].light).toMatch(/^#[0-9a-f]{6}$/);
      expect(APP_COLORS[id].dark).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
  it("the white glyph reads on every tile (contrast >= 4.5:1)", () => {
    for (const id of APP_IDS) for (const theme of ["light", "dark"] as const) {
      expect((1.05 / (luminance(APP_COLORS[id][theme]) + 0.05))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("tile colours are all different", () => {
    expect(new Set(APP_IDS.map((id) => APP_COLORS[id].light)).size).toBe(APP_IDS.length);
  });
  it("maps the machine ids served today", () => {
    expect(appIdFor("cpm")).toBe("linkcraft");
    expect(appIdFor("data_quality")).toBe("linkcraft");
    expect(appIdFor("dashboards")).toBe("dashcraft");
    expect(appIdFor("trendcraft")).toBe("dashcraft");
    expect(appIdFor("modelcraft")).toBe("modelcraft");
    expect(appIdFor("unknown")).toBeNull();
  });
  it("standalone marks name the app", () => {
    expect(markSvg("linkcraft")).toContain("<title>PlantCraft Analytics</title>");
    expect(appShortName("PlantCraft Historian")).toBe("Historian");
    expect(appShortName("PlantCraft Historian")).toBe("Historian");
    expect(appShortName("Wiki")).toBe("Wiki");
    // A renamed module reads the same everywhere: Dashboards is shown as View, whatever its manifest says.
    expect(appLabel("dashcraft", "PlantCraft View")).toBe("View");
    expect(appLabel("trendcraft", "TrendCraft")).toBe("View");
    expect(appLabel("wiki", "PlantCraft Wiki")).toBe("Wiki");
    expect(appFullName("processcraft")).toBe("PlantCraft");
  });
});
