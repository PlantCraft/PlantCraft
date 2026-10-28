// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { MultiSelect, multiSelectSummary } from "./MultiSelect";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const OPTIONS = [{ id: "alarm", label: "Alarm", count: 3 }, { id: "warning", label: "Attention", count: 5 }, { id: "ok", label: "OK", count: 40 }];

describe("multi select", () => {
  it("names what is chosen", () => {
    expect(multiSelectSummary(OPTIONS, [])).toBe("All");
    expect(multiSelectSummary(OPTIONS, ["alarm", "ok"])).toBe("Alarm, OK");
    expect(multiSelectSummary(OPTIONS, ["alarm", "warning", "ok"])).toBe("All");
    expect(multiSelectSummary([...OPTIONS, { id: "x", label: "X" }], ["alarm", "warning", "ok"])).toBe("3 of 4");
  });

  it("toggles values from its list and clears them", () => {
    const host = document.createElement("div");
    document.body.append(host);
    let value: string[] = ["alarm"];
    const root = createRoot(host);
    const draw = () => root.render(createElement(MultiSelect, { label: "Status", options: OPTIONS, value, onChange: (next: string[]) => { value = next; draw(); } }));
    act(draw);
    expect(host.textContent).toContain("Status");
    expect(host.textContent).toContain("Alarm");
    act(() => host.querySelector<HTMLButtonElement>(".pc-multi-button")!.click());
    const options = host.querySelectorAll<HTMLButtonElement>(".pc-multi-option");
    expect(options).toHaveLength(3);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    expect(host.textContent).toContain("40");
    act(() => options[1].click());
    expect(value).toEqual(["alarm", "warning"]);
    act(() => host.querySelector<HTMLButtonElement>(".pc-multi-clear")!.click());
    expect(value).toEqual([]);
    act(() => root.unmount());
  });
});
