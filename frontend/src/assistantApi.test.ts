import { describe, expect, it } from "vitest";
import { chatGroups, chatMention, chatSections, mergeMessages, settledUpTo, type Chat, type ChatMessage } from "./assistantApi";

const message = (id: number, state: ChatMessage["state"] = "done"): ChatMessage => ({
  message_id: id, chat_id: 1, role: id % 2 ? "user" : "assistant", text: `m${id}`, state, steps: [], charts: [], refs: [], meta: {}, created_at: "", updated_at: "",
});

describe("assistant chats", () => {
  it("keeps messages in order and replaces a newer copy", () => {
    const merged = mergeMessages([message(1), message(2, "working")], [message(2), message(3)]);
    expect(merged.map((item) => [item.message_id, item.state])).toEqual([[1, "done"], [2, "done"], [3, "done"]]);
  });
  it("polls after the last message that will not change", () => {
    expect(settledUpTo([message(1), message(2, "working"), message(3)])).toBe(1);
    expect(settledUpTo([message(1), message(2)])).toBe(2);
    expect(settledUpTo([])).toBe(0);
  });
  it("groups chats by when they were last used", () => {
    const now = new Date("2026-10-23T15:00:00");
    const chat = (id: number, at: string) => ({ chat_id: id, updated_at: at }) as Chat;
    const groups = chatGroups([chat(1, "2026-10-23T09:00:00"), chat(2, "2026-10-20T09:00:00"), chat(3, "2026-09-01T09:00:00")], now);
    expect(groups.map((group) => [group.key, group.chats.map((item) => item.chat_id)])).toEqual([["today", [1]], ["week", [2]], ["older", [3]]]);
  });
  it("lists the person's groups first, by name, then the rest by when they were used", () => {
    const now = new Date("2026-10-23T15:00:00");
    const chat = (id: number, folder = "") => ({ chat_id: id, folder, updated_at: "2026-10-23T09:00:00" }) as Chat;
    const sections = chatSections([chat(1, "Pumps"), chat(2), chat(3, "Alarms"), chat(4, "Pumps")], now);
    expect(sections.map((section) => [section.key, section.chats.map((item) => item.chat_id)])).toEqual([["folder:Alarms", [3]], ["folder:Pumps", [1, 4]], ["today", [2]]]);
  });
  it("puts the favorites first, wherever they are kept", () => {
    const now = new Date("2026-10-23T15:00:00");
    const chat = (id: number, folder = "", starred = false) => ({ chat_id: id, folder, starred, updated_at: "2026-10-23T09:00:00" }) as Chat;
    const sections = chatSections([chat(1, "Pumps", true), chat(2), chat(3, "", true)], now);
    expect(sections.map((section) => [section.key, section.chats.map((item) => item.chat_id)])).toEqual([["starred", [1, 3]], ["today", [2]]]);
  });
  it("makes a chat's reference for an action or a message", () => {
    expect(chatMention({ chat_id: 12, title: "Why [FIC-101]\nsticks" })).toBe("#[Why  FIC-101  sticks](chat:12)");
  });
});
