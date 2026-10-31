// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { askText, confirmAction, Dialog } from "./Dialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await Promise.resolve(); });
const key = (target: Element, name: string, shiftKey = false) => target.dispatchEvent(new KeyboardEvent("keydown", { key: name, shiftKey, bubbles: true }));

describe("dialog", () => {
  it("names itself by its title, focuses its first field, keeps Tab inside and closes on Escape", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let closed = 0;
    const footer = createElement("button", { type: "button", className: "last" }, "Save");
    act(() => root.render(createElement(Dialog, { title: "Rename", onClose: () => { closed += 1; }, footer }, createElement("input", { className: "name" }))));
    const box = host.querySelector('[role="dialog"]')!;
    expect(box.getAttribute("aria-modal")).toBe("true");
    expect(document.getElementById(box.getAttribute("aria-labelledby")!)!.textContent).toBe("Rename");
    expect(document.activeElement?.className).toBe("name");
    host.querySelector<HTMLElement>(".last")!.focus();
    key(document.activeElement!, "Tab");
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Close");
    key(document.activeElement!, "Tab", true);
    expect(document.activeElement?.className).toBe("last");
    const backdrop = host.querySelector(".dialog-backdrop")!;
    backdrop.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(closed).toBe(1);
    act(() => { host.querySelector("input")!.dispatchEvent(new Event("input", { bubbles: true })); });
    backdrop.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(closed).toBe(1);
    key(box, "Escape");
    expect(closed).toBe(2);
    act(() => root.unmount());
    expect(document.activeElement).toBe(opener);
    opener.remove();
    host.remove();
  });

  it("is a form when it has onSubmit, and Enter submits it", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let sent = 0;
    const footer = createElement("button", { className: "button button-primary" }, "Save");
    act(() => root.render(createElement(Dialog, { title: "New loop", onClose: () => undefined, onSubmit: () => { sent += 1; }, footer }, createElement("input", { name: "id" }))));
    const form = host.querySelector("form.dialog")!;
    expect(form.getAttribute("role")).toBe("dialog");
    act(() => host.querySelector<HTMLButtonElement>(".button-primary")!.click());
    expect(sent).toBe(1);
    act(() => root.unmount());
    host.remove();
  });

  it("confirmAction answers true on the button that goes ahead and false on Cancel or Escape", async () => {
    const yes = confirmAction("Delete pump P-101?\n\nIts history stays.", { title: "Delete", confirm: "Delete", danger: true });
    await flush();
    const box = document.querySelector('[role="alertdialog"]')!;
    expect(box.textContent).toContain("Delete pump P-101?");
    expect(box.querySelectorAll(".pc-confirm-text")).toHaveLength(2);
    const go = box.querySelector<HTMLButtonElement>(".pc-confirm-yes")!;
    expect(go.className).toContain("button-danger");
    expect(document.activeElement).toBe(go);
    act(() => go.click());
    expect(await yes).toBe(true);
    await flush();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();

    const cancel = confirmAction("Close without saving?");
    await flush();
    act(() => [...document.querySelectorAll<HTMLButtonElement>(".pc-confirm-host button")].find((item) => item.textContent === "Cancel")!.click());
    expect(await cancel).toBe(false);

    const escape = confirmAction("Revoke the link?");
    await flush();
    act(() => { key(document.querySelector('[role="alertdialog"]')!, "Escape"); });
    expect(await escape).toBe(false);
    await flush();
    expect(document.querySelector(".pc-confirm-host")).toBeNull();
  });

  it("askText answers the trimmed text, null on Cancel or Escape, and stays off while the field is empty", async () => {
    const setValue = (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    const named = askText("Name of the copy", { value: "Plant (copy)", confirm: "Copy" });
    await flush();
    const field = document.querySelector<HTMLInputElement>(".pc-ask-field")!;
    expect(document.activeElement).toBe(field);
    expect(field.value).toBe("Plant (copy)");
    expect(document.querySelector('[role="dialog"] h2')!.textContent).toBe("Name of the copy");
    const go = document.querySelector<HTMLButtonElement>(".pc-ask-yes")!;
    act(() => setValue(field, "   "));
    expect(go.disabled).toBe(true);
    act(() => setValue(field, "  Plant B  "));
    expect(go.disabled).toBe(false);
    act(() => go.click());
    expect(await named).toBe("Plant B");
    await flush();
    expect(document.querySelector(".pc-confirm-host")).toBeNull();

    const hours = askText("How many hours back?", { title: "Backfill", value: "48", type: "number" });
    await flush();
    const box = document.querySelector('[role="dialog"]')!;
    expect(box.querySelector("h2")!.textContent).toBe("Backfill");
    expect(box.textContent).toContain("How many hours back?");
    act(() => setValue(document.querySelector<HTMLInputElement>(".pc-ask-field")!, "-2"));
    expect(document.querySelector<HTMLButtonElement>(".pc-ask-yes")!.disabled).toBe(true);
    act(() => [...document.querySelectorAll<HTMLButtonElement>(".pc-confirm-host button")].find((item) => item.textContent === "Cancel")!.click());
    expect(await hours).toBeNull();

    const escape = askText("Name of the trend");
    await flush();
    act(() => { key(document.querySelector('[role="dialog"]')!, "Escape"); });
    expect(await escape).toBeNull();
    await flush();
    expect(document.querySelector(".pc-confirm-host")).toBeNull();
  });
});
