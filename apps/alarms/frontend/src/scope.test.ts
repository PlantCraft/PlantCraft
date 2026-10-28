import { describe, expect, it } from "vitest";
import { inScope, whoLabel } from "./people";
import type { Alarm, Directory } from "./types";

const directory: Directory = {
  people: [{ username: "ana", name: "Ana Lima" }],
  groups: [{ id: "u-100", name: "U-100 operations", members: ["ana"] }],
  disciplines: [], priorities: [],
};

describe("my alarms", () => {
  it("keeps the alarms marked mine, or all of them", () => {
    const alarms = [{ alarm_id: "a", mine: true }, { alarm_id: "b", mine: false }, { alarm_id: "c" }] as Alarm[];
    expect(inScope(alarms, "mine").map((alarm) => alarm.alarm_id)).toEqual(["a"]);
    expect(inScope(alarms, "all")).toHaveLength(3);
  });
  it("names owners and recipients", () => {
    expect(whoLabel("user:ana", directory)).toBe("Ana Lima");
    expect(whoLabel("group:u-100", directory)).toBe("U-100 operations (group)");
    expect(whoLabel("user:ghost", directory)).toBe("ghost");
    expect(whoLabel(null, directory)).toBe("–");
  });
});
