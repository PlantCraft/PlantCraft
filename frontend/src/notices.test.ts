// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import type { Notice } from "./collabApi";
import { filterNotices } from "./Notifications";
import { followNotice, hrefPath, onNoticePage } from "./NoticeFollowUp";

const notice = (key: string, state: Notice["state"], starred = false) => ({ key, state, starred, category: "action", title: key, detail: "", from: "Ana" }) as Notice;

describe("notifications marked by the person", () => {
  const items = [notice("a", "unread", true), notice("b", "read"), notice("c", "archived", true), notice("d", "archived")];
  it("lists done ones only under Done, and favorites done or not under Favorites", () => {
    expect(filterNotices(items, "all", "").map((item) => item.key)).toEqual(["a", "b"]);
    expect(filterNotices(items, "archived", "").map((item) => item.key)).toEqual(["c", "d"]);
    expect(filterNotices(items, "starred", "").map((item) => item.key)).toEqual(["a", "c"]);
  });
  it("knows the page a notification opened, and the pages inside it", () => {
    expect(hrefPath("/actions/12?tab=history#x")).toBe("/actions/12");
    expect(onNoticePage("/actions/12", { path: "/actions/12" })).toBe(true);
    expect(onNoticePage("/actions/12/edit", { path: "/actions/12" })).toBe(true);
    expect(onNoticePage("/actions/123", { path: "/actions/12" })).toBe(false);
  });
  it("remembers the notification opened, not one already done", () => {
    followNotice({ key: "k", title: "T", href: "/actions/3", state: "read" });
    expect(JSON.parse(window.sessionStorage.getItem("processcraft:notice-follow-up") ?? "null")).toEqual({ key: "k", title: "T", path: "/actions/3" });
    window.sessionStorage.clear();
    followNotice({ key: "k", title: "T", href: "/actions/3", state: "archived" });
    expect(window.sessionStorage.getItem("processcraft:notice-follow-up")).toBeNull();
  });
});
