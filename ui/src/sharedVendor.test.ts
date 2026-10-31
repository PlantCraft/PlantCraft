// @vitest-environment jsdom
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSharedPlotly } from "./Plot";
import { SHARED_FILES, SHARED_FONTS, SHARED_PLOTLY, sharedName } from "./sharedVendor";

// vitest runs in ui/, so the sources are in src/.
const here = `${process.cwd()}/src/`;
const local = (file: { package: string; file: string }) => file.package === "@plantcraft/ui"
  ? here + file.file.replace(/^dist\//, "")
  : here + "../node_modules/" + file.package + "/" + file.file;
const sha = (path: string) => createHash("sha256").update(readFileSync(path)).digest("hex");

describe("the files the platform serves once for the suite", () => {
  it("are named after the bytes this ui ships (node ui/scripts/shared-vendor-names.mjs)", () => {
    for (const file of SHARED_FILES) {
      const name = file.name.split("/").pop();
      expect(name).toBe(sharedName(file.file, sha(local(file))));
    }
  });

  it("are asked first by every font face, with the app's own copy after", () => {
    const css = readFileSync(here + "fonts.css", "utf8");
    for (const font of SHARED_FONTS) {
      const own = "./fonts/" + font.file.split("/").pop();
      const shared = "/static/vendor/" + font.name;
      const face = css.split("@font-face").find((block) => block.includes(own));
      expect(face).toBeDefined();
      expect(face!.indexOf(shared)).toBeGreaterThan(0);
      expect(face!.indexOf(shared)).toBeLessThan(face!.indexOf(own));
    }
  });

  it("name a file by its stem, the hash and every extension", () => {
    expect(sharedName("plotly-cartesian.min.js", "abcdef0123456789")).toBe("plotly-cartesian-abcdef0123.min.js");
    expect(sharedName("dist/fonts/a.woff2", "0123456789ff")).toBe("a-0123456789.woff2");
    expect(SHARED_PLOTLY.name.startsWith("plotly-cartesian-")).toBe(true);
  });
});

describe("Plotly from the platform", () => {
  afterEach(() => { vi.restoreAllMocks(); delete (globalThis as { Plotly?: unknown }).Plotly; document.head.innerHTML = ""; });

  it("is not tried under jsdom, so the app's own copy is imported", async () => {
    await expect(loadSharedPlotly()).rejects.toThrow();
    expect(document.head.querySelector("script")).toBeNull();
  });

  const asBrowser = () => vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 Chrome/130");

  it("gives way to the app's copy when the platform answers 404", async () => {
    asBrowser();
    const loading = loadSharedPlotly("/static/vendor/x.js", 5000);
    const script = document.head.querySelector("script")!;
    expect(script.getAttribute("src")).toBe("/static/vendor/x.js");
    script.dispatchEvent(new Event("error"));
    await expect(loading).rejects.toThrow("not served");
    expect(document.head.querySelector("script")).toBeNull();
  });

  it("gives way when the script does not arrive in time", async () => {
    asBrowser();
    await expect(loadSharedPlotly("/static/vendor/x.js", 10)).rejects.toThrow("too long");
  });

  it("uses the platform's copy once it has loaded", async () => {
    asBrowser();
    const loading = loadSharedPlotly("/static/vendor/x.js", 5000);
    const fake = { newPlot: () => undefined };
    (globalThis as { Plotly?: unknown }).Plotly = fake;
    document.head.querySelector("script")!.dispatchEvent(new Event("load"));
    await expect(loading).resolves.toBe(fake);
  });
});
