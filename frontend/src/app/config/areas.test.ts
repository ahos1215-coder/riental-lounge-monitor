import { describe, expect, it } from "vitest";

import { STORES } from "./stores";
import {
  AREAS,
  getAreaConfig,
  getAreaConfigForStoreSlug,
  getAreaStores,
} from "./areas";

describe("AREAS", () => {
  const storeSlugSet = new Set(STORES.map((s) => s.slug));

  it("has exactly the 5 expected area ids", () => {
    expect(AREAS.map((a) => a.id).sort()).toEqual(
      ["nagoya", "osaka", "shibuya", "ueno", "yokohama"].sort(),
    );
  });

  it("has no duplicate area ids", () => {
    const ids = AREAS.map((a) => a.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  for (const area of AREAS) {
    it(`${area.id}: every store slug exists in stores.json`, () => {
      for (const slug of area.storeSlugs) {
        expect(storeSlugSet.has(slug)).toBe(true);
      }
    });

    it(`${area.id}: has no duplicate store slugs`, () => {
      expect(new Set(area.storeSlugs).size).toBe(area.storeSlugs.length);
    });

    it(`${area.id}: has at least one store`, () => {
      expect(area.storeSlugs.length).toBeGreaterThan(0);
    });

    it(`${area.id}: keyword contains the display name`, () => {
      expect(area.keyword).toContain(area.displayName);
    });
  }
});

describe("getAreaConfig", () => {
  it("returns the matching config for a known id", () => {
    expect(getAreaConfig("osaka")?.displayName).toBe("大阪");
  });

  it("returns null for an unknown id", () => {
    expect(getAreaConfig("bogus")).toBeNull();
  });

  it("returns null for null/undefined", () => {
    expect(getAreaConfig(null)).toBeNull();
    expect(getAreaConfig(undefined)).toBeNull();
  });
});

describe("getAreaStores", () => {
  it("returns StoreMeta objects in the configured slug order", () => {
    const shibuya = getAreaConfig("shibuya")!;
    const stores = getAreaStores(shibuya);
    expect(stores.map((s) => s.slug)).toEqual(["shibuya", "shibuya_ag", "ay_shibuya"]);
  });

  it("returns the full label/areaLabel from stores.json (not hardcoded)", () => {
    const yokohama = getAreaConfig("yokohama")!;
    const stores = getAreaStores(yokohama);
    for (const s of stores) {
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.areaLabel.length).toBeGreaterThan(0);
    }
  });
});

describe("getAreaConfigForStoreSlug", () => {
  it("finds the area for a store slug that belongs to one", () => {
    expect(getAreaConfigForStoreSlug("ay_ueno")?.id).toBe("ueno");
  });

  it("returns null for a store slug not in any area", () => {
    expect(getAreaConfigForStoreSlug("fukuoka")).toBeNull();
  });

  it("returns null for null/undefined", () => {
    expect(getAreaConfigForStoreSlug(null)).toBeNull();
    expect(getAreaConfigForStoreSlug(undefined)).toBeNull();
  });
});
