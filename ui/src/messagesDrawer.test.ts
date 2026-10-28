import { describe, expect, it } from "vitest";
import { embeddedMessagesUrl, isEmbedded } from "./MessagesDrawer";

describe("Messages panel", () => {
  it("opens PlantCraft's Messages page embedded, at a conversation or at its start", () => {
    expect(embeddedMessagesUrl("/messages", "")).toBe("/messages?embed=1");
    expect(embeddedMessagesUrl("/pc/messages", "12")).toBe("/pc/messages/12?embed=1");
    expect(embeddedMessagesUrl("/messages/", "a b")).toBe("/messages/a%20b?embed=1");
  });

  it("knows when a page is inside the panel", () => {
    expect(isEmbedded("?embed=1")).toBe(true);
    expect(isEmbedded("?embed=0")).toBe(false);
    expect(isEmbedded("")).toBe(false);
  });
});
