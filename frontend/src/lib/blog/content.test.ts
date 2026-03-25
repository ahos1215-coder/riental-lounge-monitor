import { describe, expect, it } from "vitest";

import { formatYmdToSlash, isCategoryId } from "./content";

describe("isCategoryId", () => {
  it("returns true for defined category slugs", () => {
    expect(isCategoryId("guide")).toBe(true);
    expect(isCategoryId("prediction")).toBe(true);
  });

  it("returns false for all and unknown", () => {
    expect(isCategoryId("all")).toBe(false);
    expect(isCategoryId("unknown")).toBe(false);
  });
});

describe("formatYmdToSlash", () => {
  it("formats YYYY-MM-DD to slashes", () => {
    expect(formatYmdToSlash("2026-03-25")).toBe("2026/03/25");
  });
});
