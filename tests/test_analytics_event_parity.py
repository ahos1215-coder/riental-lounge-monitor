"""TS側イベント名SSOTとPython側イベント名一覧のparity検証（2026-08-26 計測レビュー対応・第2ラウンド）。

frontend/src/lib/analytics.ts::ANALYTICS_EVENT_NAMES（TS側の唯一の正本）を正規表現で読み取り、
scripts/analytics_weekly_report.py::KNOWN_CUSTOM_EVENTS から legacy 互換名 "report_read" を
除いたものと完全一致することを固定する。手動複製である2つの一覧が将来ズレたときに、
このテストが最初に落ちる番犬になる。

最終的なSSOT（依頼書冒頭に明記）: TS 12種 = store_view, report_view, favorite_add,
favorite_remove, compare_add_store, range_mode_change, cost_sim_interact, related_store_click,
official_site_click, second_venue_click, official_site_view, second_venue_view。
Python = 上記12種 + "report_read"（report_view への改名前の互換名。Python側だけの許可差分）。

ネットワークアクセスなし。合成データではなく実ソースファイルを読むが、値そのもの
（実測値・実検索語）は一切扱わないため計測レビュー依頼書の禁止事項には抵触しない。
"""

from __future__ import annotations

import re
from pathlib import Path

import scripts.analytics_weekly_report as awr

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_TS_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "analytics.ts"


def _extract_ts_event_names() -> list[str]:
    """frontend/src/lib/analytics.ts の `ANALYTICS_EVENT_NAMES = [...] as const` から
    文字列リテラルの配列内容だけを正規表現で抜き出す（TSをパースしない軽量な読み取り）。
    """
    text = ANALYTICS_TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"ANALYTICS_EVENT_NAMES\s*=\s*\[(.*?)\]\s*as const", text, re.DOTALL)
    assert m is not None, (
        "ANALYTICS_EVENT_NAMES = [...] as const が frontend/src/lib/analytics.ts に見つかりません"
        "（配列の書き方が変わった場合はこのテストの正規表現も直してください）。"
    )
    body = m.group(1)
    return re.findall(r'"([a-zA-Z0-9_]+)"', body)


def test_analytics_ts_file_exists():
    assert ANALYTICS_TS_PATH.is_file(), f"frontend/src/lib/analytics.ts が見つかりません: {ANALYTICS_TS_PATH}"


def test_ts_event_names_have_no_duplicates():
    ts_names = _extract_ts_event_names()
    assert len(ts_names) == len(set(ts_names)), "TS側のANALYTICS_EVENT_NAMESに重複があります。"


def test_ts_event_names_match_python_known_custom_events_minus_legacy():
    """TS配列 == Python一覧 - {"report_read"}（冒頭SSOTの12種で完全一致）。"""
    ts_names = set(_extract_ts_event_names())
    py_names = set(awr.KNOWN_CUSTOM_EVENTS) - {"report_read"}
    missing_in_ts = py_names - ts_names
    extra_in_ts = ts_names - py_names
    assert not missing_in_ts and not extra_in_ts, (
        "TS/PythonのイベントSSOTがズレています。"
        f" Pythonにあり(report_read以外)TSに無い: {sorted(missing_in_ts)} /"
        f" TSにありPythonに無い: {sorted(extra_in_ts)}"
    )


def test_python_known_custom_events_legacy_alias_is_only_report_read():
    """Python側だけに許可された差分は report_read のみ（それ以外の片方だけの名前は許さない）。"""
    ts_names = set(_extract_ts_event_names())
    py_names = set(awr.KNOWN_CUSTOM_EVENTS)
    assert py_names - ts_names == {"report_read"}
