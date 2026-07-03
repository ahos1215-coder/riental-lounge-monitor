# -*- coding: utf-8 -*-
"""週次 AI コメンタリー（last_week_summary / next_week_forecast）の公開前ゲート。

追加の LLM 呼び出しはしない（正規表現ベース・決定的・無料・テスト可能）。

2026-07-03 の全44店監査で見つかった実例に基づく設計:
  - shinsaibashi（HIGH, 監査で懐疑検証済み）:
      「金曜・土曜: 平均 74.9% 以上の高稼働」と書いたが、実際の金曜の平均は 28.2%
      （46.7pt 乖離）。"平均" を伴う数値主張は avg_pct のみと照合し、緩い許容差を
      超えたら block する。
  - ay_shibuya（CRITICAL）: 本文が定型文のみで実質空（数値言及ゼロ）。
      → 最小文字数・最小箇条書き数チェックで検出。

方針: 正規表現マッチには誤検知の余地があるため、許容差 (HARD_BLOCK_PP) は寛容にし、
「丸め・多少ゆるいレンジ」(監査で LOW〜MEDIUM 相当) は素通しし、shinsaibashi 級の
明白な誤り (HIGH〜CRITICAL 相当) だけを block する。block されたコメンタリーは
呼び出し側で None 扱いにし、既存の「前回コメンタリーを引き継ぐ」フォールバックに委ねる
（新しい失敗状態を増やさない）。
"""

from __future__ import annotations

import re
from typing import Any

FORBIDDEN_WORDS = ("キャバクラ", "キャスト", "指名", "同伴", "シャンパン", "ホステス")

MIN_SECTION_CHARS = 40
MIN_BULLETS = 1
HARD_BLOCK_PP = 25.0  # この pt 差を超えたら block（丸めは許容し、明白な誤りだけ弾く）

_DAY_CHARS = "月火水木金土日"
_DAY_TOKEN_RE = re.compile(r"([月火水木金土日])曜?日?")

_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]?\s*[-~〜]\s*(\d+(?:\.\d+)?)\s*[%％]")
_FLOOR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]\s*以上")
_APPROX_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]\s*(?:前後|程度)")
_DECADE_RE = re.compile(r"(\d)0\s*[%％]\s*台")
_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")

_AVG_HINT_RE = re.compile(r"平均")
_PEAK_HINT_RE = re.compile(r"ピーク|満席")


def _extract_days(line_head: str) -> list[str]:
    """箇条書き行の「数値が出るまでの先頭部分」から曜日トークンを抽出する。
    (行全体を見ると無関係な漢字を誤検出しうるため、先頭の曜日列挙部分に限定する)"""
    return [m.group(1) for m in _DAY_TOKEN_RE.finditer(line_head)]


def _day_head(line: str) -> str:
    """行内で最初に数字が現れる位置までを「曜日列挙部分」とみなして切り出す。"""
    m = re.search(r"\d", line)
    return line[: m.start()] if m else line


def _claim_from_line(line: str) -> tuple[str, float, float] | None:
    """行から (種別, 下限, 上限) の数値主張を1つ抽出する。無ければ None。
    種別: "avg" | "peak" | "any" (平均/ピークの言及が無い場合)"""
    m = _RANGE_RE.search(line)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
    else:
        m = _FLOOR_RE.search(line)
        if m:
            lo, hi = float(m.group(1)), 100.0
        else:
            m = _DECADE_RE.search(line)
            if m:
                base = int(m.group(1)) * 10
                lo, hi = float(base), float(base + 10)
            else:
                m = _APPROX_RE.search(line) or _SINGLE_RE.search(line)
                if not m:
                    return None
                v = float(m.group(1))
                lo, hi = v, v
    if _AVG_HINT_RE.search(line):
        kind = "avg"
    elif _PEAK_HINT_RE.search(line):
        kind = "peak"
    else:
        kind = "any"
    return kind, lo, hi


def _ground_truth_by_day(daily_summary: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    """day_label_ja -> {"avg": [...], "peak": [...]} (0-100 スケール)。
    0-4時ロールアップにより同じ曜日ラベルが複数エントリになり得るため list で持つ。"""
    gt: dict[str, dict[str, list[float]]] = {}
    for d in daily_summary or []:
        day = d.get("day_label_ja")
        if not day:
            continue
        bucket = gt.setdefault(day, {"avg": [], "peak": []})
        bucket["avg"].append((d.get("avg_occupancy") or 0) * 100)
        bucket["peak"].append((d.get("peak_occupancy") or 0) * 100)
    return gt


def _worst_gap_for_line(line: str, gt: dict[str, dict[str, list[float]]]) -> float:
    """行の数値主張と ground truth の最大乖離(pt)を返す。主張/曜日が無ければ 0。"""
    claim = _claim_from_line(line)
    if claim is None:
        return 0.0
    kind, lo, hi = claim
    days = _extract_days(_day_head(line))
    if not days:
        return 0.0

    worst = 0.0
    for day in days:
        bucket = gt.get(day)
        if not bucket:
            continue
        if kind == "avg":
            values = bucket["avg"]
        elif kind == "peak":
            values = bucket["peak"]
        else:
            values = bucket["avg"] + bucket["peak"]
        if not values:
            continue
        # 主張レンジ [lo,hi] と実測値集合の「最も好意的な」重なりを見る:
        # 実測値のどれか1つでも [lo,hi] に近ければ OK とし、全滅した場合のみ
        # 最寄りの実測値との差を gap とする。
        best_dist = min(
            0.0 if lo <= v <= hi else min(abs(v - lo), abs(v - hi))
            for v in values
        )
        worst = max(worst, best_dist)
    return worst


def check_weekly_commentary(
    commentary: dict[str, str] | None,
    daily_summary: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """公開前チェック。(合格か, 理由のリスト) を返す。理由が空なら合格。"""
    if not commentary:
        return False, ["commentary is empty"]

    reasons: list[str] = []
    gt = _ground_truth_by_day(daily_summary)

    for key in ("last_week_summary", "next_week_forecast"):
        text = (commentary.get(key) or "").strip()
        if len(text) < MIN_SECTION_CHARS:
            reasons.append(f"{key}: too short ({len(text)} chars)")
            continue
        bullets = [ln for ln in text.split("\n") if ln.strip().startswith("- ")]
        if len(bullets) < MIN_BULLETS:
            reasons.append(f"{key}: no bullet list found")
        for word in FORBIDDEN_WORDS:
            if word in text:
                reasons.append(f"{key}: forbidden word '{word}'")
        for line in bullets:
            gap = _worst_gap_for_line(line, gt)
            if gap > HARD_BLOCK_PP:
                reasons.append(f"{key}: numeric mismatch ~{gap:.1f}pt in line: {line.strip()[:60]}")

    return (len(reasons) == 0), reasons
