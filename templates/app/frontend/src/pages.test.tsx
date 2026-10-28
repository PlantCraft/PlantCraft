import { describe, expect, it } from "vitest";
import { NAV } from "./pages";

describe("the frame's pages", () => {
  it("Notes holds each note and the asset deep link", () => {
    const [notes] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/"]);
    for (const path of ["/", "/notes/abc", "/assets/FIC-1001"]) expect(notes.match?.(path)).toBe(true);
    expect(notes.match?.("/help")).toBe(false);
  });
});
