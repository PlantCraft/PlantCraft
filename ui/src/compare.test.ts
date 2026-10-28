// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { CodeDiff, ComparePicker, comparedVersions } from "./Compare";
import { lineDiff } from "./diff";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("comparing versions", () => {
  it("reads ?versions= smallest first, at most three", () => {
    expect(comparedVersions("?versions=3,1,3")).toEqual([1, 3]);
    expect(comparedVersions("?versions=4,2,1,3")).toEqual([1, 2, 3]);
    expect(comparedVersions("?versions=x,0")).toEqual([]);
  });

  it("finds the lines that changed", () => {
    expect(lineDiff("a\nb\nc", "a\nc\nd").map((line) => `${line.kind}:${line.text}`)).toEqual(["same:a", "removed:b", "same:c", "added:d"]);
  });

  it("hands over the ticked versions and draws a difference", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const asked: number[][] = [];
    act(() => root.render(createElement("div", null,
      createElement(ComparePicker, { numbers: [1, 2, 3, 4], onCompare: (ticked: number[]) => asked.push(ticked) }),
      createElement(CodeDiff, { lines: lineDiff("x = 1", "x = 2") }))));
    const boxes = [...host.querySelectorAll<HTMLInputElement>("input[type=checkbox]")];
    expect(boxes.map((box) => box.parentElement?.textContent)).toEqual(["Version 4", "Version 3", "Version 2", "Version 1"]);
    act(() => { boxes[0].click(); boxes[2].click(); });
    act(() => host.querySelector<HTMLButtonElement>(".button-primary")!.click());
    expect(asked).toEqual([[2, 4]]);
    expect(host.querySelector(".pc-diff")?.textContent).toBe("− x = 1\n+ x = 2\n");
    act(() => root.unmount());
  });
});
