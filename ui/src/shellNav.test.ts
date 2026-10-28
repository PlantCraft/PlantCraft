// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SuiteShell, type ShellNavItem } from "./SuiteShell";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("the sidebar's entries under a page", () => {
  it("lists them under their page, marks the open one and follows them in place", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })));
    const navigate = vi.fn();
    const nav: ShellNavItem[] = [
      { to: "/", label: "Overview", icon: null },
      { to: "/projects", label: "Projects", icon: null, children: [
        { to: "/projects/p1", label: "Boiler drum" },
        { to: "/projects/p2", label: "Tank farm" },
        { to: "/projects", label: "View all", match: (path) => path === "/projects" },
      ] },
    ];
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(createElement(SuiteShell, {
      app: "modelcraft", nav, path: "/projects/p2/edit", href: (to: string) => `/model${to}`, navigate,
      user: null, onSignOut: () => undefined, children: null,
    })));
    const list = host.querySelector(".pcs-nav-children");
    expect(list?.getAttribute("aria-label")).toBe("Projects");
    const links = [...host.querySelectorAll<HTMLAnchorElement>(".pcs-nav-child")];
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Boiler drum", "/model/projects/p1"], ["Tank farm", "/model/projects/p2"], ["View all", "/model/projects"],
    ]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, "page", null]);
    await act(async () => { links[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })); });
    expect(navigate).toHaveBeenCalledWith("/projects/p1");
    await act(async () => root.unmount());
  });
});
