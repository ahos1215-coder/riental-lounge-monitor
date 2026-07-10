import { describe, expect, it } from "vitest";

import { jstWeekLabel } from "./opengraph-image";

describe("jstWeekLabel", () => {
  it("月曜早朝 JST（旧 UTC バグ帯）でも当週の月曜を返す", () => {
    // 2026-07-13(月) 03:00 JST = 2026-07-12 18:00 UTC。
    // 旧 UTC 実装はこの時間帯で前週「2026年7月6日週」を誤表示していた。
    const t = new Date("2026-07-13T03:00:00+09:00");
    expect(jstWeekLabel(t)).toBe("2026年7月13日週");
  });

  it("月曜 00:05 JST も当日（その週の月曜）を指す", () => {
    const t = new Date("2026-07-13T00:05:00+09:00");
    expect(jstWeekLabel(t)).toBe("2026年7月13日週");
  });

  it("日曜深夜 JST は前の月曜始まりの週のまま", () => {
    // 2026-07-12(日) 23:00 JST → 週の月曜は 2026-07-06。
    const t = new Date("2026-07-12T23:00:00+09:00");
    expect(jstWeekLabel(t)).toBe("2026年7月6日週");
  });

  it("週中（水曜）でも同じ月曜を指す", () => {
    const t = new Date("2026-07-15T12:00:00+09:00"); // 水曜
    expect(jstWeekLabel(t)).toBe("2026年7月13日週");
  });

  it("月またぎの週も JST 基準で正しい", () => {
    // 2026-06-01 は月曜。5/31(日) 23:00 JST は前週 5/25 始まり。
    expect(jstWeekLabel(new Date("2026-06-01T09:00:00+09:00"))).toBe("2026年6月1日週");
    expect(jstWeekLabel(new Date("2026-05-31T23:00:00+09:00"))).toBe("2026年5月25日週");
  });
});
