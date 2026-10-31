import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];
vi.mock("./api", () => ({
  api: new Proxy({}, {
    get: (_target, name: string) => () => { calls.push(name); return new Promise(() => undefined); },
  }),
}));

import { RuleEditor } from "./RuleEditor";
import type { Me } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const reader = { username: "visitor", name: "Visitor", level: "viewer", access: "read", role: "viewer", can_edit: false, is_admin: false } as Me;

describe("rule editor", () => {
  afterEach(() => { calls.length = 0; document.body.innerHTML = ""; });

  it("a reader gets the read-only notice and asks nothing an editor's lists need (no 403 in the console)", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => { root.render(<RuleEditor me={reader} ruleId="fic-101-high" />); });
    expect(host.textContent).toContain("read-only");
    expect(calls.filter((name) => name !== "directory")).toEqual([]);
    await act(async () => root.unmount());
  });
});
