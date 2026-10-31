import { describe, expect, it } from "vitest";
import { ATTACHMENT_PREFIX, readPrefill, takeAttachment } from "./actionPrefill";

function memory(items: Record<string, string>) {
  return { getItem: (key: string) => items[key] ?? null, removeItem: (key: string) => { delete items[key]; }, items };
}
const PNG = "data:image/png;base64,iVBORw0KGgo=";

describe("action prefill", () => {
  it("reads the title, references, text and the image an app left", () => {
    const store = memory({ [`${ATTACHMENT_PREFIX}k1`]: JSON.stringify({ name: "FIC-101 chart.png", data: PNG }) });
    const found = readPrefill("?new=1&title=FIC-101%3A+Stiction&ref=asset%3AFIC-101&ref=loop_result%3AFIC-101%402026-10-31T12%3A00%3A00Z&text=Health+42&attach=k1", store);
    expect(found).toEqual({ title: "FIC-101: Stiction", refs: ["asset:FIC-101", "loop_result:FIC-101@2026-10-31T12:00:00Z"], text: "Health 42", attachment: { name: "FIC-101 chart.png", data: PNG } });
    // Read once: a reload does not attach it again.
    expect(store.items).toEqual({});
  });

  it("refuses anything but a PNG, JPEG or WebP data URL, and odd keys", () => {
    const svg = memory({ [`${ATTACHMENT_PREFIX}k`]: JSON.stringify({ name: "x", data: "data:image/svg+xml;base64,PHN2Zz4=" }) });
    expect(takeAttachment("k", svg)).toBeNull();
    expect(takeAttachment("../x", memory({}))).toBeNull();
    expect(takeAttachment("k", memory({ [`${ATTACHMENT_PREFIX}k`]: "not json" }))).toBeNull();
    expect(readPrefill("?title=x", memory({}))).toBeNull();
  });
});
