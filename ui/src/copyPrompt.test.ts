// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopyPrompt, copiedText } from "./CopyPrompt";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const PROMPT = { title: "Method: Error", text: "# Method: Error\n\nExplain it.", omitted: [] as string[] };

function mount(props: Parameters<typeof CopyPrompt>[0]) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => root.render(createElement(CopyPrompt, props)));
  return { host, root };
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("copy as prompt", () => {
  it("says what was left out for length", () => {
    expect(copiedText(PROMPT)).toBe("Prompt copied: paste it into your AI assistant.");
    expect(copiedText({ ...PROMPT, omitted: ["Help page"] })).toContain("Left out for length: Help page.");
  });

  it("copies the built text and says so", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const build = vi.fn(async () => PROMPT);
    const { host, root } = mount({ build });
    act(() => host.querySelector<HTMLButtonElement>(".pc-prompt-button")!.click());
    await settle();
    expect(build).toHaveBeenCalledWith(undefined);
    expect(writeText).toHaveBeenCalledWith(PROMPT.text);
    expect(host.querySelector(".pc-prompt-toast")?.textContent).toContain("Prompt copied");
    act(() => root.unmount());
  });

  it("asks which question with two or more presets", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: async () => undefined } });
    const build = vi.fn(async () => PROMPT);
    const { host, root } = mount({ build, questions: [{ id: "explain", label: "Explain" }, { id: "adapt", label: "Adapt" }] });
    act(() => host.querySelector<HTMLButtonElement>(".pc-prompt-button")!.click());
    const options = host.querySelectorAll<HTMLButtonElement>(".pc-prompt-option");
    expect(options).toHaveLength(2);
    act(() => options[1].click());
    await settle();
    expect(build).toHaveBeenCalledWith("adapt");
    act(() => root.unmount());
  });

  it("shows the text selected when there is no clipboard", async () => {
    vi.stubGlobal("navigator", {});
    const { host, root } = mount({ build: async () => PROMPT });
    act(() => host.querySelector<HTMLButtonElement>(".pc-prompt-button")!.click());
    await settle();
    const area = host.querySelector<HTMLTextAreaElement>(".pc-prompt-text");
    expect(area?.value).toBe(PROMPT.text);
    expect(host.querySelector("[role=dialog]")?.getAttribute("aria-label")).toBe("Method: Error");
    act(() => root.unmount());
  });
});
