import { describe, expect, it } from "vitest";
import { NAV } from "./pages";
import { splitName } from "./send";

describe("the frame's pages", () => {
  it("Overview comes first; the library holds each document, each folder and the asset deep link", () => {
    const [overview, documents, diagrams, map, search] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/", "/documents", "/diagrams", "/plant-map", "/search"]);
    expect(diagrams.match?.("/diagrams/abc/2")).toBe(true);
    expect(map.match?.("/plant-map")).toBe(true);
    expect(overview.match?.("/")).toBe(true);
    expect(overview.match?.("/documents")).toBe(false);
    for (const path of ["/documents", "/documents/abc", "/assets/FIC-1001", "/folders/x"]) expect(documents.match?.(path)).toBe(true);
    expect(documents.match?.("/")).toBe(false);
    expect(documents.match?.("/help")).toBe(false);
    expect(search.match?.("/search")).toBe(true);
  });
});

describe("a file's name", () => {
  it("gives the number and title when it starts with a document number", () => {
    expect(splitName("DOC-U200-OM-001 Hydrotreating unit operating manual.pdf")).toEqual({ number: "DOC-U200-OM-001", title: "Hydrotreating unit operating manual" });
    expect(splitName("INC-2026-007 PIC-1002 separator pressure oscillation.pdf")).toEqual({ number: "INC-2026-007", title: "PIC-1002 separator pressure oscillation" });
    expect(splitName("notes from the field.docx")).toEqual({ number: "", title: "notes from the field" });
  });
});
