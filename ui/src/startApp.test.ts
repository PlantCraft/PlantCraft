// @vitest-environment jsdom
import { act, createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STATUS_TONES } from "./brandTheme";
import { fillText } from "./files";
import { configureUi, t } from "./i18n";
import { startApp } from "./startApp";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => { document.body.innerHTML = ""; configureUi({ t: fillText }); });

describe("startApp", () => {
  it("draws the app in #root with the app's t and status tones", () => {
    document.body.innerHTML = '<div id="root"></div>';
    window.localStorage.setItem("plantcraft-ui:theme", "dark");
    const translate = vi.fn((text: string) => `[${text}]`);
    act(() => startApp(() => createElement("p", null, "Hello"), { t: translate, statusTones: { "run-stuck": "serious" } }));
    expect(document.querySelector("#root p")?.textContent).toBe("Hello");
    expect(t("Close")).toBe("[Close]");
    expect(STATUS_TONES["run-stuck"]).toBe("serious");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("says which element is missing", () => {
    expect(() => startApp(() => null, { root: "#app" })).toThrow("no #app");
  });
});
