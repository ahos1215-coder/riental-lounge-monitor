"""収集ハートビートのブランド別判定（evaluate_brands）の単体テスト。

背景: 2026-10-29 04:55 JST を最後にオリエンタル37店の logs が1行も入らなくなったが、相席屋5店の
新しい行が「logs 全体の最新1行」を満たし続けたため、全体チェックは緑のまま、店舗別チェックの閾値(3日)にも
かからず、約2夜のあいだ誰にも通知されなかった。ブランド別に同じ判定を掛けて、この種の欠測を当夜のうちに拾う。
Supabase へは一切アクセスしない（純関数）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"
JST = timezone(timedelta(hours=9))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}_brands", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hb = _load("check_collection_heartbeat")


def _jst(y, mo, d, h, mi=0, s=0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=JST).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_夜間_片方のブランドだけ止まっていれば_そのブランドだけ問題になる():
    now = _jst(2026, 10, 30, 21, 0)
    lines, problems = hb.evaluate_brands(
        {
            "oriental": _iso(_jst(2026, 10, 29, 4, 55)),  # 1日以上前
            "aisekiya": _iso(now - timedelta(minutes=2)),  # 新鮮
        },
        now,
        30,
    )
    assert len(problems) == 1 and problems[0].startswith("oriental:")
    assert any("ブランド=aisekiya" in l and "OK" in l for l in lines)


def test_昼間_昨夜が完走していなければ_そのブランドだけ問題になる():
    now = _jst(2026, 10, 31, 10, 0)
    _lines, problems = hb.evaluate_brands(
        {
            "oriental": _iso(_jst(2026, 10, 29, 4, 55)),  # 一昨夜で止まっている
            "aisekiya": _iso(_jst(2026, 10, 31, 4, 55)),  # 昨夜は完走
        },
        now,
        30,
    )
    assert [p.split(":")[0] for p in problems] == ["oriental"]


def test_両ブランドとも新鮮なら問題なし():
    now = _jst(2026, 10, 30, 21, 0)
    fresh = _iso(now - timedelta(minutes=3))
    _lines, problems = hb.evaluate_brands({"oriental": fresh, "aisekiya": fresh}, now, 30)
    assert problems == []


def test_ブランドの行が1行も無ければ問題():
    now = _jst(2026, 10, 30, 21, 0)
    _lines, problems = hb.evaluate_brands({"oriental": None}, now, 30)
    assert problems == ["oriental: 収集行なし"]


def test_夜窓開始の猶予は全体チェックと同じ_19時5分は前夜のままでも通る():
    now = _jst(2026, 10, 30, 19, 5)
    prev_night_end = _iso(_jst(2026, 10, 30, 4, 55))
    _lines, problems = hb.evaluate_brands({"oriental": prev_night_end}, now, 30)
    assert problems == []
