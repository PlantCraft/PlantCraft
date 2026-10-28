import { describe, expect, it } from "vitest";
import { assistantUrl } from "./Assistant";

describe("assistantUrl", () => {
  it("builds Desk's address under the platform's", () => {
    expect(assistantUrl("https://plant.example/", "app:linkcraft")).toBe("https://plant.example/assistant/new?ref=app%3Alinkcraft");
    expect(assistantUrl(null, "asset:FIC-101", "  ", ["a", "b"])).toBe("/assistant/new?ref=asset%3AFIC-101&s=a&s=b");
    expect(assistantUrl("/", "run:linkcraft/42", "Why did it fail?")).toBe("/assistant/new?ref=run%3Alinkcraft%2F42&q=Why+did+it+fail%3F");
  });
});
