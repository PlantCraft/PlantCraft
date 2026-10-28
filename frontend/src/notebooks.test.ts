import { describe, expect, it } from "vitest";
import { computerSnippet, notebookLink, ownKit, ownPythonCommands, requestFromQuery } from "./Notebooks";

describe("notebooks", () => {
  it("reads signals, a period and a step from the address", () => {
    expect(requestFromQuery("?signals=a:FIC-101.PV,a:FIC-101.SP&start=-7d&end=now&step=60&origin=Historian")).toEqual({
      kind: "series", signals: ["a:FIC-101.PV", "a:FIC-101.SP"], start: "-7d", end: "now", step: 60, origin: "Historian",
    });
    expect(requestFromQuery("?signal=x&signal=y")).toMatchObject({ kind: "series", signals: ["x", "y"], start: "-24h", end: "now", step: undefined });
  });

  it("reads an asset, or nothing", () => {
    expect(requestFromQuery("?asset=FIC-101&name=Feed")).toEqual({ kind: "asset", asset_id: "FIC-101", name: "Feed" });
    expect(requestFromQuery("")).toBeNull();
    expect(requestFromQuery("?signals=,")).toBeNull();
  });

  it("links back to itself and connects a computer", () => {
    const link = notebookLink(["a:b"], "2026-10-01T00:00:00Z", "now", "the export");
    expect(requestFromQuery(link.slice(link.indexOf("?")))).toMatchObject({ signals: ["a:b"], origin: "the export" });
    expect(computerSnippet("https://pc.local", "pcat_x.y", "plantcraft_notebook-0.1.0-py3-none-any.whl")).toContain('pc.connect("https://pc.local", token="pcat_x.y")');
  });

  it("installs the package in an environment of its own (PEP 668), on every system", () => {
    const file = "plantcraft_notebook-0.1.0-py3-none-any.whl";
    const mac = ownPythonCommands(file, "MacIntel").split("\n");
    expect(mac).toEqual(["python3 -m venv ~/plantcraft-env", "source ~/plantcraft-env/bin/activate", `pip install jupyterlab matplotlib ~/Downloads/${file}`, "jupyter lab"]);
    const windows = ownPythonCommands(file, "Win32");
    expect(windows).toContain("py -m venv plantcraft-env");
    expect(windows).toContain(`"%USERPROFILE%\\Downloads\\${file}"`);
  });
});

describe("Python in the browser", () => {
  it("checks the engine and the biggest packages, and counts in megabytes", async () => {
    const { probes, megabytes } = await import("./notebookInstall");
    const files = ["/l/v/b/static/pyodide/pyodide.asm.wasm", "/l/v/b/static/pyodide/pandas-2.2.3-cp312-cp312-pyodide_2024_0_wasm32.whl", "/l/v/b/lab/index.js", "/l/v/b/static/pyodide/scipy-1.14.1-cp312-cp312-pyodide_2024_0_wasm32.whl"];
    expect(probes(files)).toEqual([files[0], files[1], files[3]]);
    expect(megabytes(129_400_000)).toBe("129 MB");
  });

  it("is not installed until this build was installed here", async () => {
    const { installed, forget } = await import("./notebookInstall");
    forget();
    expect(await installed({ build: "abc", bytes: 1, files: [] })).toBe(false);
  });

  it("offers the kit of the computer the page runs on", () => {
    const kit = (id: string) => ({ id, system: id, arch: "x64", bytes: 1, sha256: "", url: `/k/${id}.zip` });
    const kits = [kit("linux-x64"), kit("macos-arm64"), kit("windows-x64")];
    expect(ownKit(kits, "Win32")?.id).toBe("windows-x64");
    expect(ownKit(kits, "MacIntel")?.id).toBe("macos-arm64");
    expect(ownKit(kits, "Linux x86_64")?.id).toBe("linux-x64");
    expect(ownKit(kits, "iPhone")).toBeUndefined();
  });
});
