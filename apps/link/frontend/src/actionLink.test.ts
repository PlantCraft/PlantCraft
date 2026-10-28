import { describe, expect, it } from "vitest";
import { processCraftActionUrl } from "./AssetLink";
import type { Me } from "./types";

const me = { processcraft_url: "/" } as Me;

describe("processCraftActionUrl", () => {
  it("opens PlantCraft's action form filled in for the loop's asset", () => {
    const url = new URL(processCraftActionUrl(me, "FIC-1003", "FIC-1003: Stiction"), "https://suite.local");
    expect(url.pathname).toBe("/actions");
    expect(url.searchParams.get("new")).toBe("1");
    expect(url.searchParams.get("ref")).toBe("asset:FIC-1003");
    expect(url.searchParams.get("title")).toBe("FIC-1003: Stiction");
  });

  it("keeps PlantCraft's own prefix", () => {
    expect(processCraftActionUrl({ processcraft_url: "https://suite.local/" } as Me, "a b", "x"))
      .toBe("https://suite.local/actions?new=1&ref=asset%3Aa+b&title=x");
  });
});
