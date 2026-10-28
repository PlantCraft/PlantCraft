import { describe, expect, it } from "vitest";
import { initialDoc } from "./HelpPage";

describe("help addresses", () => {
  it("open a method's page from /help/methods/<id>", () => {
    expect(initialDoc("/help/methods/sq_spikes", "")).toBe("methods/sq_spikes");
    expect(initialDoc("/help/methods/oscillation_autocorrelation", "?doc=guides/runs")).toBe("methods/oscillation_autocorrelation");
  });
  it("open the page the address names, or none", () => {
    expect(initialDoc("/help", "?doc=guides%2Fsignals")).toBe("guides/signals");
    expect(initialDoc("/help", "")).toBeUndefined();
  });
});
