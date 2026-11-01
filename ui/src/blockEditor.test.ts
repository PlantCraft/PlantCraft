// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { BlockEditor, type BlockCatalog, type Diagram } from "./BlockEditor";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// React Flow measures its nodes; jsdom has no layout.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= ResizeObserverStub;
(globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly ??= class {
  m22 = 1;
};

const CATALOG: BlockCatalog = {
  libraries: [
    { library: "input", name: "Inputs", description: "Signals." },
    { library: "logic", name: "Logic", description: "Combine verdicts." },
  ],
  blocks: [
    {
      block_id: "input.verdict",
      library: "input",
      name: "Signal verdict",
      summary: "The verdict Signal quality gave a signal.",
      description: "Reads the latest verdict.",
      reading: "Ok, warning or bad.",
      assumptions: [],
      limitations: ["Only as fresh as the last round."],
      references: [],
      inputs: [],
      outputs: [{ port: "result", types: ["result"], type: "result", label: "Verdict", description: "The verdict.", unit: "", required: false, multiple: false, record: false }],
      parameters: [{ name: "role", title: "Role", description: "Which signal.", unit: "", default: "pv", schema: { type: "string" } }],
    },
    {
      block_id: "logic.worst",
      library: "logic",
      name: "Worst of",
      summary: "The most severe of its inputs.",
      description: "Keeps the worst verdict.",
      reading: "Bad when any input is bad.",
      assumptions: [],
      limitations: [],
      references: [],
      inputs: [{ port: "in", types: ["result"], type: "result", label: "In", description: "Verdicts.", unit: "", required: true, multiple: true, record: false }],
      outputs: [{ port: "result", types: ["result"], type: "result", label: "Verdict", description: "The worst.", unit: "", required: false, multiple: false, record: false }],
      parameters: [],
    },
  ],
};

const DIAGRAM: Diagram = {
  version: 2,
  nodes: [
    { id: "pv", block: "input.verdict", parameters: { role: "pv" }, x: 0, y: 0 },
    { id: "worst", block: "logic.worst", label: "PV quality", x: 300, y: 0 },
  ],
  edges: [{ source: "pv", source_port: "result", target: "worst", target_port: "in" }],
};

async function mount(props: Partial<Parameters<typeof BlockEditor>[0]> = {}) {
  const host = document.createElement("div");
  host.style.height = "600px";
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(createElement(BlockEditor, { catalog: CATALOG, diagram: DIAGRAM, ...props }));
  });
  return { host, root };
}

describe("BlockEditor", () => {
  it("read-only, shows only the tools that work there and no banner for a valid diagram (round 9)", async () => {
    const { host, root } = await mount({ check: { valid: true, errors: [], warnings: [], node_errors: {} } });
    const titles = [...host.querySelectorAll<HTMLButtonElement>(".be-tools .be-tool")].map((item) => item.title);
    // Zoom and fit are the canvas's own controls; the toolbar only expands (2026-11-01).
    expect(titles).toEqual(["Give the diagram the whole window"]);
    expect(host.textContent).not.toContain("The diagram is valid");
    expect(host.querySelector(".be-status")).toBeNull();
    await act(async () => root.unmount());
  });

  it("shows the palette by library, the blocks with their own names and the check", async () => {
    const onChange = vi.fn();
    const { host, root } = await mount({
      onChange,
      check: { valid: false, errors: ["Input In of Worst of is not wired."], warnings: [], node_errors: { worst: ["Input In of Worst of is not wired."] } },
      trace: { worst: { result: { type: "result", status: "bad", value: 10, message: "Frozen." } } },
    });
    const text = host.textContent ?? "";
    expect(text).toContain("Inputs");
    expect(text).toContain("Logic");
    expect(text).toContain("Signal verdict");
    expect(text).toContain("PV quality");
    expect(text).toContain("1 problems");
    expect(host.querySelector(".be-node.be-has-issue")).not.toBeNull();
    // A test run shows as a light on the block; its message waits in the hover tip.
    expect(host.querySelector(".be-node .be-light.be-status-bad")).not.toBeNull();
    expect(host.querySelector('.be-node[data-block="logic.worst"] .be-tip')?.textContent).toContain("Frozen.");
    // The wires carry no values until asked.
    expect(host.querySelector(".be-wire-value")).toBeNull();
    // The legend names the wires' kinds and the libraries the blocks come from.
    expect(host.querySelector(".be-legend")?.textContent).toContain("Blocks");
    // Libraries start folded; opening one folds the other.
    expect(host.querySelectorAll(".be-palette-item")).toHaveLength(0);
    const toggles = [...host.querySelectorAll<HTMLButtonElement>(".be-lib-toggle")];
    await act(async () => toggles[0].click());
    expect([...host.querySelectorAll(".be-palette-item")].map((item) => item.querySelector("strong")?.textContent)).toEqual(["Signal verdict"]);
    await act(async () => toggles[1].click());
    expect([...host.querySelectorAll(".be-palette-item")].map((item) => item.querySelector("strong")?.textContent)).toEqual(["Worst of"]);
    expect(toggles[0].getAttribute("aria-expanded")).toBe("false");
    // Clicking a palette entry adds the block.
    const add = [...host.querySelectorAll<HTMLButtonElement>(".be-palette-item")].find((item) => item.textContent?.includes("Worst of"));
    await act(async () => add?.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    const added: Diagram = onChange.mock.calls[0][0];
    expect(added.nodes.map((node) => node.id)).toEqual(["pv", "worst", "worst_2"]);
    await act(async () => root.unmount());
  });

  it("shows the app's tools for the selected block in the inspector", async () => {
    const tools = vi.fn((node: { id: string }) => (node.id === "worst" ? createElement("button", { className: "calibrate" }, "Calibrate") : null));
    const { host, root } = await mount({ onChange: vi.fn(), inspectorTools: tools });
    expect(host.querySelector(".be-inspector-tools")).toBeNull();
    const node = host.querySelector<HTMLElement>('.react-flow__node[data-id="worst"]');
    await act(async () => node?.click());
    expect(host.querySelector(".be-inspector-tools .calibrate")?.textContent).toBe("Calibrate");
    expect(tools).toHaveBeenCalledWith(expect.objectContaining({ id: "worst" }));
    await act(async () => root.unmount());
  });

  it("expands over the whole window and leaves with Esc", async () => {
    const { host, root } = await mount();
    const expand = host.querySelector<HTMLButtonElement>('.be-tools .be-tool[aria-pressed]');
    await act(async () => expand?.click());
    expect(host.querySelector(".be-editor.be-expanded")).not.toBeNull();
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(host.querySelector(".be-editor.be-expanded")).toBeNull();
    await act(async () => root.unmount());
  });

  it("is read-only without onChange: no palette, nothing to undo", async () => {
    const { host, root } = await mount();
    expect(host.querySelector(".be-palette")).toBeNull();
    expect(host.querySelector(".be-readonly")).not.toBeNull();
    await act(async () => root.unmount());
  });
});
