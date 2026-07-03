# -*- coding: utf-8 -*-
"""commentary_quality_gate の単体テスト。

2026-07-03 の全44店監査で実際に見つかったケースを再現する:
  - shinsaibashi (HIGH, 懐疑検証済み): 「平均74.9%以上」だが金曜の実平均は28.2% → block
  - ay_shibuya (CRITICAL): 本文が定型文のみで実質空 → block
  - shibuya (LOW, 監査で pass 判定): 水曜のレンジが実測を10.5pt外すだけ → 許容(pass)
  - nagasaki (pass): 数値がほぼ完全一致 → pass
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from commentary_quality_gate import check_weekly_commentary  # noqa: E402


def _daily(day: str, avg: float, peak: float) -> dict:
    return {"day_label_ja": day, "avg_occupancy": avg / 100, "peak_occupancy": peak / 100}


def test_shinsaibashi_like_floor_claim_is_blocked():
    daily_summary = [
        _daily("金", 28.2, 64.3),
        _daily("土", 74.9, 100.0),
    ]
    commentary = {
        "last_week_summary": (
            "先週は土曜の深夜を中心に非常に高い混雑が見られました。\n"
            "- 金曜・土曜: 平均 74.9% 以上の高稼働\n"
            "- 日曜: 平均 20% と比較的落ち着いた状況でした"
        ),
        "next_week_forecast": (
            "来週も週末を中心に高い混雑が予想されます。\n"
            "- 金曜・土曜: 深夜帯に高稼働の見込みです\n"
            "- 平日: 落ち着いた推移が予想されます"
        ),
    }
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is False
    assert any("numeric mismatch" in r for r in reasons)


def test_empty_stub_is_blocked():
    daily_summary = [_daily("金", 73.8, 100.0), _daily("土", 69.0, 100.0)]
    commentary = {"last_week_summary": "", "next_week_forecast": ""}
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is False
    assert len(reasons) >= 2


def test_none_commentary_is_blocked():
    ok, reasons = check_weekly_commentary(None, [])
    assert ok is False
    assert reasons == ["commentary is empty"]


def test_forbidden_word_is_blocked():
    daily_summary = [_daily("金", 50.0, 90.0)]
    commentary = {
        "last_week_summary": "先週は金曜のキャストが人気で賑わいました。\n- 金曜: 平均50%前後の稼働でした",
        "next_week_forecast": "来週も同様の傾向が予想されます。\n- 金曜: 平均50%前後を見込みます",
    }
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is False
    assert any("forbidden word" in r for r in reasons)


def test_shibuya_like_minor_range_slip_is_tolerated():
    # 実例: 水曜(部分日, avg 5.5%)を「16%前後」と表現 (10.5pt差、監査ではLOW=許容範囲)
    daily_summary = [
        _daily("水", 5.5, 16.5),
        _daily("木", 24.6, 48.3),
        _daily("金", 67.5, 100.0),
        _daily("土", 67.9, 100.0),
    ]
    commentary = {
        "last_week_summary": (
            "先週は週末にかけて混雑が顕著でした。\n"
            "- 金曜・土曜は平均 65-70% 台で、ピーク時には満席となる時間帯が見られました\n"
            "- 水曜は平均16%前後と、比較的落ち着いた状況でした"
        ),
        "next_week_forecast": (
            "来週も週末の混雑が継続すると予想されます。\n"
            "- 金曜・土曜は、平均60%以上の見込みです\n"
            "- 水曜は落ち着いた推移が予想されます"
        ),
    }
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is True, reasons


def test_nagasaki_like_accurate_report_passes():
    daily_summary = [
        _daily("木", 21.1, 34.6),
        _daily("金", 60.0, 100.0),
        _daily("土", 65.0, 100.0),
        _daily("日", 20.0, 40.0),
    ]
    commentary = {
        "last_week_summary": (
            "先週は週末を中心に混雑が見られました。\n"
            "- 金曜・土曜: 平均60%台、ピーク時は満席に近い状態でした\n"
            "- 木曜: 平均21%と平日の中では高めの稼働でした"
        ),
        "next_week_forecast": (
            "来週も同様の傾向が予想されます。\n"
            "- 金曜・土曜: 深夜帯に満席近い状態が見込まれます\n"
            "- 日曜: 平均20%前後で推移する見込みです"
        ),
    }
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is True, reasons


def test_too_short_section_is_blocked():
    daily_summary = [_daily("金", 50.0, 90.0)]
    commentary = {"last_week_summary": "先週は普通でした。", "next_week_forecast": "来週も普通の見込みです。"}
    ok, reasons = check_weekly_commentary(commentary, daily_summary)
    assert ok is False
    assert any("too short" in r or "no bullet" in r for r in reasons)
