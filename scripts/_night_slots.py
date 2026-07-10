"""夜間スロットグリッドの共有定数（stdlib のみ・サードパーティ import ゼロ）。

scripts/build_templates.py（テンプレ生成）と scripts/snapshot_forecasts.py（v2 スナップ
ショット）は共に「19:00〜05:00 (JST, -6h 規約) を 15 分刻みで区切った 40 スロット」の
同一グリッドを前提にしており、値は必ず一致していなければならない。

snapshot_forecasts.py は最小依存環境（GHA: stdlib + jpholiday のみ）で実行されるため、
build_templates.py から直接 import すると（そちらは任意で numpy/pandas/lightgbm を
import しうる）意図せず重い依存を引き込むリスクがある。そのため、あえてこの小さな
専用モジュールに切り出して両者から参照する。
"""

from __future__ import annotations

SLOTS = 40  # 19:00〜05:00 を 15 分刻みで 40 スロット (index 0=19:00 .. 39=04:45)
NIGHT_START_HOUR = 19
