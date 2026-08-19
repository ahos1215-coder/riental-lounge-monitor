"""stores.json の共有読み込み（scripts/_stores_common.py）の番犬テスト。

B-07: slug -> store_id の変換が2流儀に分かれていた。

  (a) score_forecasts.py / snapshot_forecasts.py: `ay_` 接頭辞ヒューリスティック
      （`slug if slug.startswith("ay_") else f"ol_{slug}"`）
  (b) generate_weekly_insights.py / local_report_job.py: stores.json の store_id 参照

現行42店では両者の結果は全件一致しているが、それは「まだ食い違いを踏んでいない」
だけで、将来 `ay_` 以外の接頭辞や store_id≠ol_+slug の店が入ると精度追跡
(snapshot/score) だけが別の store_id を向く。stores.json を正とする実装へ寄せた上で、

  1. 現行42店で「旧ヒューリスティック == stores.json の store_id」（＝挙動不変）
  2. 意図的に食い違わせた stores.json を与えたとき、必ず stores.json 側が採用される
  3. stores.json が読めないときの各スクリプトのエラー方針（daily/patch は SystemExit、
     weekly は警告＋空 dict で継続）が維持されている

を固定する。1 は「今回の整理で表示・保存先が変わっていない」ことの証明、
2 は「新実装が本当に stores.json を見ている」ことの証明。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import generate_weekly_insights as gwi
from scripts import local_report_job as lrj
from scripts import patch_weekly_store_ids as patch
from scripts import score_forecasts as sf
from scripts import snapshot_forecasts as snap


def _real_rows() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / "frontend" / "src" / "data" / "stores.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _old_heuristic(slug: str) -> str:
    """旧 score_forecasts.py / snapshot_forecasts.py の実装。"""
    return slug if slug.startswith("ay_") else f"ol_{slug}"


# --------------------------------------------------------------------------- #
# 1. 現行42店で挙動不変
# --------------------------------------------------------------------------- #
def test_all_real_stores_agree_with_old_heuristic() -> None:
    rows = _real_rows()
    assert len(rows) == 42, "店舗数が変わったら stores.json / oriental/utils/stores.py を確認"
    for row in rows:
        slug, store_id = row["slug"], row["store_id"]
        assert _old_heuristic(slug) == store_id, f"{slug}: {_old_heuristic(slug)} != {store_id}"


@pytest.mark.parametrize("mod", [sf, snap], ids=["score_forecasts", "snapshot_forecasts"])
def test_store_id_for_matches_stores_json_on_all_real_stores(mod) -> None:
    for row in _real_rows():
        assert mod._store_id_for(row["slug"]) == row["store_id"]


def test_weekly_and_daily_agree_with_snapshot_on_all_real_stores() -> None:
    """4スクリプトが同じ slug に対して同じ store_id を返す（精度追跡と週報のズレ防止）。"""
    store_map = lrj._load_store_map()
    for row in _real_rows():
        slug = row["slug"]
        expected = row["store_id"]
        assert gwi._store_id_for_slug(slug) == expected
        assert lrj._store_id_for(store_map[slug]) == expected
        assert sf._store_id_for(slug) == expected
        assert snap._store_id_for(slug) == expected


# --------------------------------------------------------------------------- #
# 3. stores.json が読めないときのエラー方針（スクリプトごとに異なるまま維持）
# --------------------------------------------------------------------------- #
def test_weekly_missing_stores_json_warns_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """週報は stores.json が無くてもジョブを止めない（空 dict ＋ 警告）。"""
    monkeypatch.setattr(gwi, "STORES_JSON_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(gwi, "_SLUG_TO_STORE_ID_CACHE", None)
    assert gwi._load_slug_to_store_id_map() == {}
    assert "stores.json not found" in capsys.readouterr().err
    monkeypatch.setattr(gwi, "_SLUG_TO_STORE_ID_CACHE", None)


def test_daily_missing_stores_json_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lrj, "STORES_JSON_PATH", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        lrj._load_store_map()


def test_patch_missing_stores_json_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(patch, "STORES_JSON_PATH", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        patch._load_slug_to_store_id_map()


def test_weekly_broken_stores_json_warns_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    broken = tmp_path / "stores.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(gwi, "STORES_JSON_PATH", broken)
    monkeypatch.setattr(gwi, "_SLUG_TO_STORE_ID_CACHE", None)
    assert gwi._load_slug_to_store_id_map() == {}
    assert "failed to load stores.json" in capsys.readouterr().err
    monkeypatch.setattr(gwi, "_SLUG_TO_STORE_ID_CACHE", None)


# --------------------------------------------------------------------------- #
# 2. stores.json が正（ヒューリスティックに引きずられない）
# --------------------------------------------------------------------------- #
def _stores_common_modules():
    """`_stores_common` は「scripts.」付きとベアの2通りで sys.modules に載りうる
    （scripts/ は名前空間パッケージで、各スクリプトはベアインポートする規約）。
    どちらから来ても効くよう、両方を対象にする。"""
    import sys

    return [m for name, m in sys.modules.items() if name.split(".")[-1] == "_stores_common"]


@pytest.fixture
def fake_stores_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """stores.json を差し替えて slug->store_id キャッシュを空にするフィクスチャ。"""

    def _apply(rows: list[dict]) -> None:
        path = tmp_path / "stores.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        for mod in _stores_common_modules():
            monkeypatch.setattr(mod, "STORES_JSON_PATH", path)
            monkeypatch.setattr(mod, "_STORE_ID_CACHE", None)

    yield _apply
    for mod in _stores_common_modules():
        mod._STORE_ID_CACHE = None


@pytest.mark.parametrize("mod", [sf, snap], ids=["score_forecasts", "snapshot_forecasts"])
def test_stores_json_wins_over_ay_prefix_heuristic(mod, fake_stores_json) -> None:
    """ヒューリスティックと食い違う stores.json を与えたら、必ず stores.json が勝つ。

    現行42店で両者が一致しているのは「まだ食い違いを踏んでいない」だけなので、
    新実装が本当に stores.json を見ていることをここで独立に証明する。
    """
    fake_stores_json(
        [
            # ay_ で始まるのに store_id は ol_ 系（旧ヒューリスティックなら "ay_special"）
            {"slug": "ay_special", "store_id": "ol_special"},
            # ay_ で始まらないのに store_id は ay_ 系（旧ヒューリスティックなら "ol_odd"）
            {"slug": "odd", "store_id": "ay_odd"},
        ]
    )
    assert mod._store_id_for("ay_special") == "ol_special"
    assert mod._store_id_for("odd") == "ay_odd"


@pytest.mark.parametrize("mod", [sf, snap], ids=["score_forecasts", "snapshot_forecasts"])
def test_unknown_slug_falls_back_to_heuristic(mod, fake_stores_json) -> None:
    """stores.json に無い slug は従来どおりのヒューリスティック（バッチを落とさない）。"""
    fake_stores_json([{"slug": "shibuya", "store_id": "ol_shibuya"}])
    assert mod._store_id_for("ay_newtown") == "ay_newtown"
    assert mod._store_id_for("newtown") == "ol_newtown"
