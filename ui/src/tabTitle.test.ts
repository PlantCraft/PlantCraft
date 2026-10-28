// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { BRAND_NAME } from "./appMarks.js";
import { BRAND_FAVICON, headingText, tabTitle } from "./tabTitle.js";

describe("tab title", () => {
  it("reads page, app, brand", () => {
    expect(tabTitle("linkcraft", "FIC-1003")).toBe("FIC-1003 · Analytics · PlantCraft");
    expect(tabTitle("histcraft", "Points")).toBe("Points · Historian · PlantCraft");
  });

  it("names an app outside the family by its manifest's name, else its id", () => {
    expect(tabTitle("starter", "Notes", 0, "StarterCraft")).toBe("Notes · StarterCraft · PlantCraft");
    expect(tabTitle("starter", "Notes")).toBe("Notes · starter · PlantCraft");
  });

  it("is just the brand on the platform's home, and page · brand on its pages", () => {
    expect(tabTitle("processcraft")).toBe(BRAND_NAME);
    expect(tabTitle("processcraft", "Assets")).toBe("Assets · PlantCraft");
  });

  it("drops a page that repeats the app or the brand", () => {
    expect(tabTitle("linkcraft", "Analytics")).toBe("Analytics · PlantCraft");
    expect(tabTitle("processcraft", "PlantCraft")).toBe("PlantCraft");
    expect(tabTitle("dashcraft", "  ")).toBe("View · PlantCraft");
  });

  it("cuts a long page name", () => {
    const title = tabTitle("alarmcraft", "x".repeat(200));
    expect(title.endsWith("… · Alarms · PlantCraft")).toBe(true);
    expect(title.length).toBeLessThan(90);
  });

  it("reads a heading's words, without icons or pills", () => {
    const h1 = document.createElement("h1");
    h1.innerHTML = '<svg aria-hidden="true"></svg><span class="as-tag">FIC-1003</span><span>Feed flow</span><span class="pill">Alarm</span>';
    expect(headingText(h1)).toBe("FIC-1003 Feed flow");
    h1.setAttribute("data-tab-title", "Own title");
    expect(headingText(h1)).toBe("Own title");
  });

  it("uses the platform's mark as the icon", () => {
    expect(BRAND_FAVICON.startsWith("data:image/svg+xml,")).toBe(true);
    expect(decodeURIComponent(BRAND_FAVICON)).toContain("#0a66d0");
  });
});
