import { describe, expect, it } from "vitest";
import { parseQuery } from "./search-parser";

describe("parseQuery", () => {
  it("keeps natural-language text", () => {
    expect(parseQuery("birthday cake")).toEqual({ text: "birthday cake" });
  });

  it("extracts structured filters", () => {
    expect(parseQuery("beach who:Sam place:Lisbon before:2020")).toEqual({
      text: "beach",
      who: "Sam",
      place: "Lisbon",
      before: "2020",
    });
  });
});
