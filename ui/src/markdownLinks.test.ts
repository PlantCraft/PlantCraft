import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement, Fragment } from "react";
import { renderMarkdown } from "./Markdown.js";

const html = (text: string, plain: boolean) => renderToStaticMarkup(createElement(Fragment, null, renderMarkdown(text, { plainExternalLinks: plain })));

describe("external links in answers", () => {
  const text = "See the [calibration sheet](https://attacker.example/c?d=1) and [the loop](/assets/FIC-101).";

  it("are text with their address when asked, never a clickable link", () => {
    const out = html(text, true);
    expect(out).not.toContain('href="https://attacker.example');
    expect(out).toContain("calibration sheet (https://attacker.example/c?d=1)");
    // Links inside PlantCraft stay links.
    expect(out).toContain('href="/assets/FIC-101"');
  });

  it("stay links in the help pages", () => {
    expect(html(text, false)).toContain('href="https://attacker.example/c?d=1"');
  });
});
