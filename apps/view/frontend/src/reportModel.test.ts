import { describe, expect, it } from "vitest";
import { cadenceLabel, deliveredLabel, EMPTY_SCHEDULE, insertSection, moveSection, newSection, newSectionId, outlineOf, periodRange, replaceSection, reportDraftOf, runState, runStatusLabel, sectionName, textCell } from "./reportModel";
import type { ReportRun, Section } from "./types";

const run = (over: Partial<ReportRun>): ReportRun => ({
  run_id: "r1", report_id: "a", report_name: "A", trigger: "schedule", status: "done", requested_by: null,
  started_at: "", finished_at: null, period_start: "", period_end: "", period: "24h", sections: 3, problems: 0,
  summary: "", error: "", recipients: [], delivered: 4, pdf_bytes: 2048, ...over,
});

describe("reports", () => {
  it("say when they are sent, as the server does", () => {
    expect(cadenceLabel({ ...EMPTY_SCHEDULE, every: "day", at: "06:00" })).toBe("Every day at 06:00");
    expect(cadenceLabel({ ...EMPTY_SCHEDULE, every: "week", weekday: "fri", at: "17:00" })).toBe("Every Friday at 17:00");
    expect(cadenceLabel({ ...EMPTY_SCHEDULE, every: "month", day: 3, at: "07:30" })).toBe("Every month on day 3 at 07:30");
    expect(cadenceLabel(EMPTY_SCHEDULE)).toBe("Not scheduled");
  });

  it("give new sections fresh ids and cards fresh card ids", () => {
    const first = newSection("card", []);
    const second = newSection("card", [first]);
    expect(first.section_id).not.toBe(second.section_id);
    expect(first.card?.card_id).not.toBe(second.card?.card_id);
    expect(newSection("events", []).events).toEqual({ kinds: [], limit: 20 });
    expect(newSectionId([{ ...first, section_id: "s2" }])).toBe("s3");
  });

  it("move, replace and name sections", () => {
    const a: Section = { ...newSection("text", []), section_id: "a", title: "Intro" };
    const b: Section = { ...newSection("break", []), section_id: "b" };
    expect(moveSection([a, b], "b", -1).map((item) => item.section_id)).toEqual(["b", "a"]);
    expect(moveSection([a, b], "a", -1)).toEqual([a, b]);
    expect(replaceSection([a, b], { ...a, title: "Day" })[0].title).toBe("Day");
    expect(replaceSection([a], b)).toHaveLength(2);
    expect(sectionName({ ...a, title: "", text: "## The day\nmore" })).toBe("The day");
    expect(sectionName(b)).toBe("Page break");
  });

  it("cover the period back from its end", () => {
    const end = new Date("2026-10-26T09:00:00Z");
    expect(periodRange("7d", end).start.toISOString()).toBe("2026-10-19T09:00:00.000Z");
  });

  it("say how a run went", () => {
    expect(runState(run({}))).toBe("ok");
    expect(runState(run({ problems: 2 }))).toBe("warning");
    expect(runStatusLabel(run({ problems: 2 }))).toBe("2 sections not read");
    expect(runState(run({ status: "failed" }))).toBe("alarm");
    expect(deliveredLabel(run({}))).toBe("4 people");
    expect(deliveredLabel(run({ trigger: "download" }))).toBe("Nobody (download)");
    expect(runStatusLabel(run({ trigger: "download" }))).toBe("Made");
  });

  it("copy a saved report into a draft", () => {
    const draft = reportDraftOf({ name: "Daily", schedule: { ...EMPTY_SCHEDULE, every: "day" } });
    expect(draft.period).toBe("24h");
    expect(draft.schedule.at).toBe("06:00");
    expect(draft.sections).toEqual([]);
  });

  it("list the headings of the text cells as the outline, outside code", () => {
    const a: Section = { ...newSection("text", []), section_id: "a", text: "# Day\n\nText\n\n## **Feed**\n```\n# not a heading\n```\n#### Low" };
    const b: Section = { ...newSection("card", [a]), section_id: "b" };
    const c: Section = { ...newSection("text", []), section_id: "c", text: "### Next" };
    expect(outlineOf([a, b, c])).toEqual([
      { sectionId: "a", level: 1, text: "Day", nth: 0 },
      { sectionId: "a", level: 2, text: "Feed", nth: 1 },
      { sectionId: "a", level: 4, text: "Low", nth: 2 },
      { sectionId: "c", level: 3, text: "Next", nth: 0 },
    ]);
  });

  it("put a new cell where it was asked for, and read old text sections as one cell", () => {
    const a: Section = { ...newSection("break", []), section_id: "a" };
    const b: Section = { ...newSection("break", []), section_id: "b" };
    const c: Section = { ...newSection("break", []), section_id: "c" };
    expect(insertSection([a, b], c, 1).map((item) => item.section_id)).toEqual(["a", "c", "b"]);
    expect(insertSection([a, b], c, null).map((item) => item.section_id)).toEqual(["a", "b", "c"]);
    const old: Section = { ...newSection("text", []), title: "Summary", text: "The day." };
    expect(textCell(old)).toMatchObject({ title: "", text: "# Summary\n\nThe day." });
    expect(reportDraftOf({ sections: [old] }).sections[0].text).toBe("# Summary\n\nThe day.");
  });
});
