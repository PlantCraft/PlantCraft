import { describe, expect, it } from "vitest";
import { IMAGE_MAX_BYTES, imageProblem, withImageHrefs } from "./BlockDrawing.js";

describe("block images (round 9 M2)", () => {
  it("takes a PNG, JPEG, WebP or SVG of at most 256 KB", () => {
    expect(imageProblem({ type: "image/png", size: 1000 })).toBe("");
    expect(imageProblem({ type: "image/svg+xml", size: IMAGE_MAX_BYTES })).toBe("");
    expect(imageProblem({ type: "image/gif", size: 10 })).toMatch(/PNG, JPEG, WebP or SVG/);
    expect(imageProblem({ type: "image/png", size: IMAGE_MAX_BYTES + 1 })).toMatch(/257 KB.*at most 256 KB/);
  });

  it("turns the catalog's image paths into the browser's", () => {
    const blocks = [{ block_id: "a", image: "/api/blocks/a/image?v=1" }, { block_id: "b", image: null }, { block_id: "c", image: "data:image/png;base64,x" }];
    expect(withImageHrefs(blocks, (path) => `/link${path}`).map((item) => item.image)).toEqual(["/link/api/blocks/a/image?v=1", null, "data:image/png;base64,x"]);
  });
});
