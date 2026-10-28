import { describe, expect, it } from "vitest";
import { NAV } from "./pages";

describe("the frame's pages", () => {
  it("Overview first; Dashboards holds the list, each dashboard and the asset deep link; Diagrams, Reports, then Trends (the quick look) their own", () => {
    const [overview, dashboards, diagrams, reports, trends] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/", "/dashboards", "/diagrams", "/reports", "/trends"]);
    for (const path of ["/diagrams", "/diagrams/abc", "/diagrams/new"]) expect(diagrams.match?.(path)).toBe(true);
    expect(dashboards.match?.("/diagrams")).toBe(false);
    expect(overview.match?.("/")).toBe(true);
    expect(overview.match?.("/d/abc")).toBe(false);
    for (const path of ["/dashboards", "/d/abc", "/assets/fic-101"]) expect(dashboards.match?.(path)).toBe(true);
    expect(dashboards.match?.("/")).toBe(false);
    expect(dashboards.match?.("/help")).toBe(false);
    expect(dashboards.match?.("/trends")).toBe(false);
    for (const path of ["/trends", "/trends/abc"]) expect(trends.match?.(path)).toBe(true);
    for (const path of ["/reports", "/reports/abc"]) expect(reports.match?.(path)).toBe(true);
    expect(dashboards.match?.("/reports")).toBe(false);
  });
});
