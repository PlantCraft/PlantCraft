import { describe, expect, it } from "vitest";
import { draftBody, draftOf, feedKey, feedShown, localInput, seriesMove } from "./CalendarPage";
import { dueText, placeOf, reorder } from "./TodoPage";
import { checkLines, lineBudget } from "./Desk";
import { mentionsIn, notePlace } from "./NotesPage";
import { addDays, isoDay, upcoming, type AppFeed, type CalendarEvent, type Todo } from "./deskApi";
import { chatsOf, clockZones, kanbanCards, layOutDay, monthWeeks, offsetText, sameAsUtc, shortAgo, zoneCity } from "./DeskWidgets";

const event = (id: string, start: string, end?: string): CalendarEvent => ({ id, title: id, start, end, all_day: start.length === 10, kind: "action", editable: false });

describe("Desk's coming days", () => {
  it("groups events by day from today, and leaves out the past and what is beyond the window", () => {
    const groups = upcoming([event("b", "2026-10-24"), event("a", "2026-10-23T09:00:00"), event("old", "2026-10-20"), event("far", "2026-11-20")], "2026-10-23", 7);
    expect(groups.map((group) => group.day)).toEqual(["2026-10-23", "2026-10-24"]);
    expect(groups[0].events.map((item) => item.id)).toEqual(["a"]);
  });

  it("shows a several-day event that began before today on today", () => {
    const groups = upcoming([event("trip", "2026-10-21", "2026-10-25")], "2026-10-23", 3);
    expect(groups).toEqual([{ day: "2026-10-23", events: [expect.objectContaining({ id: "trip" })] }]);
  });

  it("counts days in the browser's own calendar", () => {
    expect(isoDay(addDays(new Date(2026, 9, 31, 12), 1))).toBe("2026-11-01");
  });
});

describe("Desk's visual widgets", () => {
  it("lays out a month Monday first, in whole weeks", () => {
    const weeks = monthWeeks(2026, 9);
    expect(weeks[0]).toEqual([null, null, null, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
    expect(weeks).toHaveLength(5);
    expect(weeks.at(-1)?.slice(0, 6)).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"]);
  });

  it("puts overlapping events side by side on the day's timeline", () => {
    const timed = (id: string, start: string, end: string): CalendarEvent => ({ id, title: id, start: `2026-10-24T${start}:00Z`, end: `2026-10-24T${end}:00Z`, all_day: false, kind: "external", editable: false });
    const placed = layOutDay([timed("a", "09:00", "10:00"), timed("b", "09:30", "10:30"), timed("c", "11:00", "11:30")], 8 * 60, 14 * 60, 30);
    expect(placed.map(({ event, top, column, columns }) => [event.id, top, column, columns])).toEqual([["a", 30, 0, 2], ["b", 45, 1, 2], ["c", 90, 0, 1]]);
  });

  it("names a clock by its city and its distance from here", () => {
    expect(zoneCity("America/Sao_Paulo")).toBe("São Paulo");
    expect(offsetText(180)).toBe("+3 h");
    expect(offsetText(-90)).toBe("−1 h 30");
    expect(offsetText(0)).toBe("");
    expect(clockZones({ zones: ["Asia/Tokyo", 3] })).toEqual(["Asia/Tokyo"]);
    expect(new Set(clockZones({})).size).toBe(clockZones({}).length);
    // A message older than a week shows its day, which fits the row's corner.
    const now = Date.parse("2026-10-25T22:00:00Z");
    expect(shortAgo("2026-10-25T21:55:00Z", now)).toBe("5 min ago");
    expect(shortAgo("2026-10-15T09:00:00Z", now)).not.toMatch(/2026|:/);
    // A server on "Etc/UTC" shows one UTC clock, not two.
    expect(sameAsUtc("Etc/UTC") && sameAsUtc("UTC") && sameAsUtc("GMT")).toBe(true);
    expect(sameAsUtc("America/Sao_Paulo") || sameAsUtc("Europe/London")).toBe(false);
  });

  it("counts chats with people only, unread first", () => {
    const chat = (id: number, unread: number, kind: "person" | "system", at: string) => ({ conversation_id: id, title: "", display_title: String(id), is_group: false, has_specialist: false, unread, busy: [], members: [{ username: "me", display_name: "Me", role: "", kind: "person" as const, busy: false }, { username: "x", display_name: "X", role: "", kind, busy: false }], last_message: null, created_at: at, updated_at: at });
    expect(chatsOf([chat(1, 0, "person", "2026-10-24T10:00"), chat(2, 3, "system", "2026-10-24T11:00"), chat(3, 1, "person", "2026-10-23T09:00")], "me").map((item) => item.conversation_id)).toEqual([3, 1]);
  });

  it("fits whole lines and cards in each height", () => {
    expect([2, 3].map(kanbanCards)).toEqual([2, 4]);
    expect([2, 3].map(checkLines)).toEqual([1, 5]);
    expect([2, 3].map(lineBudget)).toEqual([4, 8]);
  });
});

describe("Desk's calendar events", () => {
  it("moves a whole repeat by as much as one of its times moved", () => {
    const series = { start: new Date(2026, 9, 26, 9, 0).toISOString(), end: new Date(2026, 9, 26, 9, 30).toISOString(), allDay: false };
    // The Wednesday time dragged from 09:00 to 10:00 the next day: the series moves a day and an hour.
    const move = seriesMove(series, { start: new Date(2026, 9, 28, 9, 0), end: new Date(2026, 9, 28, 9, 30) }, { start: new Date(2026, 9, 29, 10, 0), end: new Date(2026, 9, 29, 10, 30), allDay: false });
    expect(move).toEqual({ start: new Date(2026, 9, 27, 10, 0).toISOString(), end: new Date(2026, 9, 27, 10, 30).toISOString() });
    // Stretched by 30 minutes: only the end moves.
    const longer = seriesMove(series, { start: new Date(2026, 9, 28, 9, 0), end: new Date(2026, 9, 28, 9, 30) }, { start: new Date(2026, 9, 28, 9, 0), end: new Date(2026, 9, 28, 10, 0), allDay: false });
    expect(longer).toEqual({ start: series.start, end: new Date(2026, 9, 26, 10, 0).toISOString() });
    // Into the all-day row: the series' day moves by as many days, the end goes back to the default.
    const whole = seriesMove(series, { start: new Date(2026, 9, 28, 9, 0), end: null }, { start: new Date(2026, 9, 30), end: null, allDay: true });
    expect(whole).toEqual({ all_day: true, start: "2026-10-28", end: null });
    const days = seriesMove({ start: "2026-10-26", end: "2026-10-28", allDay: true }, { start: new Date(2026, 9, 26), end: new Date(2026, 9, 28) }, { start: new Date(2026, 9, 27), end: new Date(2026, 9, 29), allDay: true });
    expect(days).toEqual({ start: "2026-10-27", end: "2026-10-29" });
  });

  it("shows an all-day event's last day and stores the day after", () => {
    const draft = draftOf({ title: "Turnaround", start: "2026-11-02", end: "2026-11-07", all_day: true, repeat: "", until: null, notes: "" });
    expect([draft.start, draft.end]).toEqual(["2026-11-02", "2026-11-06"]);
    expect(draftBody(draft)).toMatchObject({ start: "2026-11-02", end: "2026-11-07", all_day: true, until: null });
    const timed = draftOf({ title: "Handover", start: new Date(2026, 9, 26, 7, 0).toISOString(), end: new Date(2026, 9, 26, 7, 30).toISOString(), all_day: false, repeat: "weekdays", until: "2026-12-31" });
    expect(timed.start).toBe(localInput(new Date(2026, 9, 26, 7, 0)));
    expect(draftBody(timed)).toMatchObject({ start: new Date(2026, 9, 26, 7, 0).toISOString(), repeat: "weekdays", until: "2026-12-31" });
  });
});

describe("Desk's to-dos", () => {
  it("opens the place a link names", () => {
    expect(placeOf("?list=3&item=12")).toEqual({ view: "list", list: 3, item: 12 });
    expect(placeOf("?view=planned")).toEqual({ view: "planned", list: null, item: null });
    expect(placeOf("?view=nonsense")).toEqual({ view: "today", list: null, item: null });
  });

  it("says when a to-do is due", () => {
    expect(dueText("2026-10-24", "2026-10-24")).toEqual({ text: "Today", late: false });
    expect(dueText("2026-10-25", "2026-10-24")).toEqual({ text: "Tomorrow", late: false });
    expect(dueText("2026-10-22", "2026-10-24")?.late).toBe(true);
    expect(dueText(null, "2026-10-24")).toBeNull();
  });

  it("sends only the positions a move changes", () => {
    const item = (todo_id: number, position: number) => ({ todo_id, position }) as Todo;
    const items = [item(1, 0), item(2, 10), item(3, 20)];
    expect(reorder(items, 3, 0)).toEqual([{ todo_id: 3, position: 0 }, { todo_id: 1, position: 10 }, { todo_id: 2, position: 20 }]);
    expect(reorder(items, 1, 1)).toEqual([{ todo_id: 2, position: 0 }, { todo_id: 1, position: 10 }]);
    expect(reorder(items, 2, 1)).toEqual([]);
  });
});

describe("Desk's notes", () => {
  it("reads a note or a calendar event's note from the address", () => {
    expect(notePlace("?note=4")).toEqual({ note: 4, event: null, title: "" });
    expect(notePlace("?event=event%3A12&title=Shift+handover")).toEqual({ note: null, event: "event:12", title: "Shift handover" });
  });
  it("finds the # mentions of one line, once each", () => {
    const mention = (id: string) => ({ type: "mention", attrs: { id, label: id } });
    const line = { type: "paragraph", content: [{ type: "text" }, mention("asset:FIC-101"), { type: "text" }, mention("action:3"), mention("asset:FIC-101")] };
    expect(mentionsIn(line)).toEqual(["asset:FIC-101", "action:3"]);
    expect(mentionsIn(null)).toEqual([]);
  });
});

describe("the apps' calendar feeds", () => {
  const feed = (visible: boolean): AppFeed => ({ id: "linkcraft:reviews", app: "linkcraft", app_name: "Link", title: "Reviews", description: "", visible });
  it("shows a visible feed until its chip is switched off, and one that starts off once switched on", () => {
    expect(feedShown(feed(true), [])).toBe(true);
    expect(feedShown(feed(true), [feedKey(feed(true))])).toBe(false);
    expect(feedShown(feed(false), [])).toBe(false);
    expect(feedShown(feed(false), [feedKey(feed(false))])).toBe(true);
    // A chip switched for the visible feed says nothing about the same feed declared off later.
    expect(feedShown(feed(false), [feedKey(feed(true))])).toBe(false);
  });
});
