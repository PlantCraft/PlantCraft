import { describe, expect, it } from "vitest";
import { recipientLabel, recipientPeople } from "./RecipientPicker.js";

const people = [{ username: "ana", name: "Ana Lima" }, { username: "rui", name: "Rui Alves" }];
const groups = [{ id: "unit-100", name: "Unit 100 operations", kind: "area", members: ["ana", "eva"] }];

describe("recipients", () => {
  it("names people and groups, and the reference when nobody matches", () => {
    expect(recipientLabel("user:ana", people, groups)).toBe("Ana Lima");
    expect(recipientLabel("group:unit-100", people, groups)).toBe("Unit 100 operations (group)");
    expect(recipientLabel("group:gone", people, groups)).toBe("gone");
  });
  it("reaches each person once, through their groups too", () => {
    expect(recipientPeople(["user:ana", "group:unit-100", "user:rui"], groups)).toEqual(["ana", "eva", "rui"]);
  });
});
