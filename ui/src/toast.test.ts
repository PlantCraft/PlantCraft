// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { showToast } from "./toast";

afterEach(() => { document.body.innerHTML = ""; vi.useRealTimers(); });

describe("showToast", () => {
  it("shows the text, closes on its own, with its button or Escape", () => {
    vi.useFakeTimers();
    showToast("Saved", { tone: "ok" });
    const item = document.querySelector(".pc-toast-ok");
    expect(item?.textContent).toContain("Saved");
    expect(item?.getAttribute("role")).toBe("status");
    vi.advanceTimersByTime(6_000);
    expect(document.querySelector(".pc-toast")).toBeNull();
    showToast("Could not cancel the run.", { tone: "error" });
    expect(document.querySelector(".pc-toast-error")?.getAttribute("role")).toBe("alert");
    (document.querySelector(".pc-toast-close") as HTMLButtonElement).click();
    expect(document.querySelector(".pc-toast")).toBeNull();
    showToast("x");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(document.querySelector(".pc-toast")).toBeNull();
  });

  it("keeps at most four, as text (never markup)", () => {
    for (let i = 0; i < 6; i += 1) showToast(`<b>${i}</b>`, { ms: 0 });
    const items = document.querySelectorAll(".pc-toast");
    expect(items).toHaveLength(4);
    expect(items[3].querySelector("b")).toBeNull();
    expect(items[3].textContent).toContain("<b>5</b>");
  });
});
