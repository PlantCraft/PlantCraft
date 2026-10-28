import { describe, expect, it } from "vitest";
import { overviewCatalog } from "./Overview";
import type { WidgetDef } from "./Widgets";

describe("App Overview", () => {
  it("puts the page's own widgets first, prefixed with the app, and drops a published twin", () => {
    const published: WidgetDef[] = [
      { id: "linkcraft:worst", app: "linkcraft", title: "Worst", size: "m" },
      { id: "linkcraft:runs", app: "linkcraft", title: "Runs", size: "m" },
    ];
    const catalog = overviewCatalog("linkcraft", [{ id: "worst", title: "Worst (drawn)", size: "l", render: () => null }, { id: "kinds", title: "Kinds", size: "s", render: () => null }], published);
    expect(catalog.map((item) => item.id)).toEqual(["linkcraft:worst", "linkcraft:kinds", "linkcraft:runs"]);
    expect(catalog[0].title).toBe("Worst (drawn)");
    expect(catalog.every((item) => item.app === "linkcraft")).toBe(true);
  });

  it("drops the app's name from a published title on the app's own page", () => {
    const published: WidgetDef[] = [{ id: "alarmcraft:active", app: "alarmcraft", title: "Alarms: active", size: "s" }];
    expect(overviewCatalog("alarmcraft", [], published, "Alarms")[0].title).toBe("Active");
    expect(overviewCatalog("alarmcraft", [], published)[0].title).toBe("Alarms: active");
  });
});
