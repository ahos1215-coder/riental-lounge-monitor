"""scripts/_night_slots.py（夜間40スロットグリッド共有定数）のテスト。

scripts/build_templates.py の SLOTS/NIGHT_START_HOUR と scripts/snapshot_forecasts.py の
V2_SLOTS は元々それぞれ独立したリテラル値コピーだった。同一グリッドに一本化した後も
旧リテラル値 (40, 19) と一致することをロックする。

snapshot_forecasts.py は最小依存環境 (GHA: stdlib + jpholiday のみ) で動くため、
flask/pandas/lightgbm が無い状態でも import できることも併せて確認する
(scripts/build_templates.py 経由の import だと重い依存を引き込みかねないため、
scripts/_night_slots.py はゼロ・サードパーティ依存になっている)。
"""

from __future__ import annotations

import importlib
import sys

import pytest

import scripts._night_slots as night_slots
import scripts.build_templates as bt
import scripts.snapshot_forecasts as snap


# 旧リテラル値（build_templates.py: SLOTS=40, NIGHT_START_HOUR=19 /
# snapshot_forecasts.py: V2_SLOTS=40）。
OLD_SLOTS_LITERAL = 40
OLD_NIGHT_START_HOUR_LITERAL = 19


def test_night_slots_module_matches_old_literals() -> None:
    assert night_slots.SLOTS == OLD_SLOTS_LITERAL
    assert night_slots.NIGHT_START_HOUR == OLD_NIGHT_START_HOUR_LITERAL


def test_build_templates_slots_match_shared_module() -> None:
    assert bt.SLOTS == night_slots.SLOTS == OLD_SLOTS_LITERAL
    assert bt.NIGHT_START_HOUR == night_slots.NIGHT_START_HOUR == OLD_NIGHT_START_HOUR_LITERAL


def test_snapshot_forecasts_v2_slots_match_shared_module() -> None:
    assert snap.V2_SLOTS == night_slots.SLOTS == OLD_SLOTS_LITERAL


def test_build_templates_and_snapshot_forecasts_agree() -> None:
    """一本化前は2箇所の独立したリテラルだった。値が食い違えば v2 の
    テンプレ生成とスナップショットのスロット数がズレて壊れるので、ここで固定する。"""
    assert bt.SLOTS == snap.V2_SLOTS


class _BlockThirdPartyImports:
    """CI-minimal (GHA: stdlib + jpholiday のみ) をシミュレートする meta_path finder。
    flask/pandas/lightgbm/numpy への import を ModuleNotFoundError にする
    (find_spec ベース。find_module/load_module は Python 3.12 で削除済み)。"""

    BLOCKED = {"flask", "pandas", "lightgbm", "numpy"}

    def find_spec(self, fullname, path, target=None):
        root = fullname.split(".")[0]
        if root in self.BLOCKED:
            raise ModuleNotFoundError(f"blocked in CI-minimal simulation: {fullname}")
        return None


def test_snapshot_forecasts_still_importable_without_third_party_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """snapshot_forecasts.py が GHA の最小依存環境 (stdlib + jpholiday のみ) でも
    import できることを、flask/pandas/lightgbm/numpy を meta_path でブロックして確認する。
    scripts/_night_slots.py がゼロ・サードパーティ依存であることのゲート。

    他のテストが先に oriental.ml (flask/pandas 込み) を import 済みだと、sys.modules の
    キャッシュヒットで meta_path のブロックを素通りしてしまい fallback 分岐を検証
    できない。そのため oriental.*・flask・pandas・numpy・lightgbm・
    scripts.snapshot_forecasts のキャッシュを monkeypatch.delitem で一時的に落として
    ("blocked" root 名で始まる/一致するものすべて) 強制的に作り直しさせる。
    monkeypatch なので、このテスト終了時に sys.modules / sys.meta_path は自動的に
    元の状態へ復元される（他テストへの影響なし）。
    """
    blocked_roots = {"oriental", "flask", "pandas", "numpy", "lightgbm"}
    reload_targets = {"scripts.snapshot_forecasts", "_night_slots"}
    for mod_name in list(sys.modules):
        root = mod_name.split(".")[0]
        if root in blocked_roots or mod_name in reload_targets:
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    finder = _BlockThirdPartyImports()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])

    reloaded = importlib.import_module("scripts.snapshot_forecasts")
    assert reloaded.V2_SLOTS == OLD_SLOTS_LITERAL
    # 実際に flask-free fallback 分岐 (importlib 直読み) を通ったことも確認する。
    assert reloaded.classify_night.__module__ == "_night_type_standalone"
