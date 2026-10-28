// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { actionQuery, type ResolvedRef, type Specialist } from "./collabApi";
import { isLocalHref, plainMentions } from "./collab";
import { withMention } from "./Actions";
import { messageParts, writerNote } from "./Messages";
import { modelState } from "./Specialists";
import { connectionState } from "./LanguageModel";

const asset: ResolvedRef = { ref: "asset:FIC-101", kind: "asset", id: "FIC-101", kind_label: "Asset", title: "Feed flow", href: "/assets/FIC-101", exists: true };
const signal: ResolvedRef = { ref: "signal:opc:FT-101.PV", kind: "signal", id: "opc:FT-101.PV", kind_label: "Signal", title: "FT-101.PV", href: "/link/signals/opc%3AFT-101.PV", exists: true };

describe("actions list query", () => {
  it("repeats the status and leaves out what is empty", () => {
    expect(actionQuery({})).toBe("");
    expect(actionQuery({ status: ["open", "in_progress"], mine: true, q: " valve " })).toBe("?status=open&status=in_progress&q=valve&mine=true");
  });
});

describe("message text", () => {
  it("turns #refs and plain ids into chips and keeps bold", () => {
    const parts = messageParts("Check #asset:FIC-101 and **now** look at #signal:opc:FT-101.PV; FIC-101 again", [asset, signal]);
    expect(parts.filter((part) => part.kind === "ref").map((part) => part.text)).toEqual(["FIC-101", "opc:FT-101.PV", "FIC-101"]);
    expect(parts.find((part) => part.kind === "bold")?.text).toBe("now");
    expect(parts.map((part) => part.text).join("")).toBe("Check FIC-101 and now look at opc:FT-101.PV; FIC-101 again");
  });
  it("does not take a number in the text for an action's id", () => {
    const action: ResolvedRef = { ref: "action:1", kind: "action", id: "1", kind_label: "Action", title: "Inspect the valve", href: "/actions/1", exists: true };
    const parts = messageParts("mean absolute error of 1.1 and 1 more; see #action:1", [action]);
    expect(parts.filter((part) => part.kind === "ref").map((part) => part.text)).toEqual(["Inspect the valve"]);
    expect(messageParts("FIC-101.PV is a signal of FIC-101", [asset]).filter((part) => part.kind === "ref").map((part) => part.text)).toEqual(["FIC-101"]);
  });
  it("shows a labelled mention by its label, and the label alone when it does not resolve", () => {
    const doc: ResolvedRef = { ref: "doc:7", kind: "doc", id: "7", kind_label: "Document", title: "Valve test", href: "/doc/documents/7", exists: true };
    const parts = messageParts("Follow #[PRO-U200-012](doc:7) and #[the chat](chat:9); **now**", [doc]);
    expect(parts.filter((part) => part.kind === "ref").map((part) => part.text)).toEqual(["PRO-U200-012"]);
    expect(parts.map((part) => part.text).join("")).toBe("Follow PRO-U200-012 and the chat; now");
  });
  it("leaves text without references alone", () => {
    expect(messageParts("plain (a+b) text", [])).toEqual([{ kind: "text", text: "plain (a+b) text" }]);
  });
  it("says how a specialist wrote", () => {
    expect(writerNote({ writer: "script" })).toBe("Scripted answer, no language model");
    expect(writerNote({ writer: "claude-x" })).toContain("claude-x");
    expect(writerNote(null)).toBe("");
  });
  it("opens PlantCraft's pages in the app and other apps' pages in full", () => {
    expect(isLocalHref("/assets/FIC-101")).toBe(true);
    expect(isLocalHref("/actions/3")).toBe(true);
    expect(isLocalHref("/link/runs/abc")).toBe(false);
  });
});

describe("specialist model state", () => {
  const base: Specialist = { username: "loops", display_name: "Loops", subject: "", instructions: "", apps: [], active: true, model: { source: "off", enabled: false, ready: false, provider: "anthropic", provider_id: "", name: "", endpoint: "", api_key_set: false, api_key_hint: null }, answers: 0, last_answer_at: null, updated_at: null, updated_by: null };
  const data = { model_allowed: true, defaults: { provider: "anthropic", model: "default-model" }, providers: [{ id: "anthropic", label: "Claude (Anthropic)" }] };
  const connection = { enabled: true, ready: true, allowed: true, provider: "openai", name: "llama3.1:70b", endpoint: "http://llm:11434/v1", api_key_set: false, api_key_hint: null, updated_at: null, updated_by: null };
  it("is off with scripted answers unless a model is on and allowed", () => {
    expect(modelState(base, data)).toBe("Off — scripted answers");
    expect(modelState({ ...base, model: { ...base.model, source: "own", enabled: true } }, data)).toBe("Claude (Anthropic) · default-model");
    expect(modelState({ ...base, model: { ...base.model, source: "own", name: "m2" } }, { ...data, model_allowed: false })).toBe("Off — scripted answers");
  });
  it("names the installation's model, or says it is not set up", () => {
    const installation = { ...base, model: { ...base.model, source: "installation" as const } };
    expect(modelState(installation, { ...data, connection })).toBe("The installation's model · llama3.1:70b");
    expect(modelState(installation, { ...data, connection: { ...connection, ready: false } })).toBe("The installation's model (not set up) — scripted answers");
    expect(connectionState(connection)).toBe("llama3.1:70b at http://llm:11434/v1");
    expect(connectionState({ ...connection, allowed: false })).toContain("whoever installed it");
    expect(connectionState({ ...connection, enabled: false })).toBe("Off: no default model yet");
  });
});

describe("mentions in actions", () => {
  it("reads references as plain words in previews", () => {
    expect(plainMentions("Check #asset:FIC-101 with #user:ana.lima.")).toBe("Check FIC-101 with ana.lima.");
    expect(plainMentions("See #[Feed pump](asset:P-1001) now")).toBe("See Feed pump now");
  });
  it("adds a mention at the end of a text", () => {
    expect(withMention("", "asset:P-1")).toBe("#asset:P-1 ");
    expect(withMention("Ask", "user:ana")).toBe("Ask #user:ana ");
  });
  it("shows a person by name, never by a bare username in the text", () => {
    const ana = { ref: "user:ana", kind: "user", id: "ana", kind_label: "Person", title: "Ana Lima", href: "/people/ana", exists: true };
    const parts = messageParts("ana asked #user:ana", [ana]);
    expect(parts.filter((part) => part.kind === "ref").map((part) => part.text)).toEqual(["Ana Lima"]);
  });
});
