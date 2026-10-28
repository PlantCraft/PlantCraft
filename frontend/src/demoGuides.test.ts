// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { demoGuides, GUIDE_IDS, guideById, stopHref } from "./demoGuides";

// The apps' prefixes on an installation (docs/suite.md) and PlantCraft's own pages a visitor reads.
const PREFIXES = ["/link/", "/hist/", "/dash/", "/alarm/", "/model/", "/doc/"];
const PLATFORM = ["/", "/actions", "/messages", "/assistant", "/notebooks", "/calendar", "/admin", "/health", "/help", "/people/me", "/assets/FIC-1003"];

describe("the demo's guides by role", () => {
  it("has one guide per role, each a short walk with words of its own", () => {
    const guides = demoGuides();
    expect(guides.map((guide) => guide.id)).toEqual(GUIDE_IDS);
    const titles = new Set<string>();
    for (const guide of guides) {
      expect(guide.stops.length).toBeGreaterThanOrEqual(5);
      expect(guide.stops.length).toBeLessThanOrEqual(8);
      for (const stop of guide.stops) {
        expect(stop.title.length).toBeLessThan(60);
        expect(stop.body.length).toBeLessThan(330);
        titles.add(stop.title);
        // Every stop opens a page a visitor may read: an app's or PlantCraft's own.
        const page = stop.to.split("?")[0];
        expect(PREFIXES.some((prefix) => page.startsWith(prefix)) || PLATFORM.includes(page)).toBe(true);
      }
    }
    expect(titles.size).toBe(guides.reduce((total, guide) => total + guide.stops.length, 0));
  });

  it("opens an object of the story by its name, else its list", () => {
    const stop = guideById("manager")!.stops[0];
    expect(stopHref(stop, {})).toBe("/dash/");
    expect(stopHref(stop, { "Plant overview": "/dash/dashboards/7" })).toBe("/dash/dashboards/7");
    // Never another site, whatever the links hold.
    expect(stopHref(stop, { "Plant overview": "//evil.example" })).toBe("/dash/");
    const display = guideById("operator")!.stops[1];
    expect(stopHref(display, { "Riverbend Refinery": "/dash/diagrams/2" })).toBe("/dash/diagrams/2");
    expect(guideById("nobody")).toBeNull();
  });
});
