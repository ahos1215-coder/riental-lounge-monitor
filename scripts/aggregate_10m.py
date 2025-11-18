from __future__ import annotations

import argparse
import json
from pathlib import Path

from oriental.utils.agg import aggregate_10m


def main():
    ap = argparse.ArgumentParser(description="5分等の履歴を10分平均に集計（夜19-05のみ）")
    ap.add_argument("--in", dest="in_path", required=True, help="入力 JSON（配列）")
    ap.add_argument("--out", dest="out_path", required=True, help="出力 JSON（配列）")
    ap.add_argument("--store", dest="store", default=None, help="store_id（例: nagasaki）")
    ap.add_argument("--tz", dest="tz", default="Asia/Tokyo")
    ap.add_argument("--start-h", dest="start_h", type=int, default=19)
    ap.add_argument("--end-h", dest="end_h", type=int, default=5)
    args = ap.parse_args()

    in_p = Path(args.in_path)
    out_p = Path(args.out_path)

    data = json.loads(in_p.read_text(encoding="utf-8"))
    out = aggregate_10m(
        data,
        tz=args.tz,
        start_h=args.start_h,
        end_h=args.end_h,
        store_id=args.store,
    )

    out_p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(out)} rows -> {out_p}")


if __name__ == "__main__":
    main()
