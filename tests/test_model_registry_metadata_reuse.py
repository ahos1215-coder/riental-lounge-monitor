"""番犬: 起動時 preload が metadata.json を42回ダウンロードしていた件の回帰テスト。

2026-09-05〜09、Supabase 無料枠の egress を使い切って全リクエストが HTTP 402 になり、
サイトが3日半「男性0/女性0」を表示し続けた。ここで潰すのは **Flask 起動1回あたりの
最大の無駄**＝同じ metadata.json の重複ダウンロードで、起動時 preload の転送量の37%。
（事故全体の「最大要因」だと断定はしない。この diff が触っていない sweep 経路も同じ
320,848 B を refresh ウィンドウごとに取り直しており、旧既定の 900 秒ではトラフィック次第で
最大 96回/日 ≒ 29.4 MiB/日 と、起動1回ぶんの 12.5 MiB を上回り得た。そちらは
`FORECAST_MODEL_REFRESH_SEC` の既定を 10800 秒へ延ばして別途潰した。）

原因: preload (oriental/__init__.py::_preload_models) は 42 店を順に get_bundle する。
1店目だけが refresh ウィンドウを掴んで sweep 経路へ入り `_next_refresh_unix` を先へ
進めるため、残り41店は単店経路 (`_load_single_unlocked`) に落ちる。旧実装はそこで
店舗ごとに無条件で metadata.json を落としており、**実測 320,848 B を42回（うち41回＝
12.5 MiB が無駄。42回ぶんの合計は 12.85 MiB）** 起動のたびに取っていた。

修正: 同じ refresh ウィンドウ内に取得済みの metadata があれば単店経路はそれを使い回す。
sweep 経路（＝モデル更新を拾う本体）と `refresh_batch`・ロック設計・
schema_version 検証・disk cache fallback は一切変えない。

このファイルが固定するのは以下:
  1. preload 相当の連続呼び出しで metadata.json の取得は1回だけ
  2. refresh_sec を超えた metadata は使い回さない（鮮度の契約は不変）
  3. 手持ちの metadata に載っていない新店は従来どおり取り直して解決する
  4. 使い回した metadata にも schema_version 検証が効く
"""

from __future__ import annotations

import copy
import logging

import pytest

from oriental.ml import model_registry as mr


class _FakeModel:
    pass


def _entry(date_str: str, store: str) -> dict:
    return {
        "model_men": f"model_{store}_{date_str}_men.txt",
        "model_women": f"model_{store}_{date_str}_women.txt",
    }


def _meta(store_ids, date_str: str = "20260908") -> dict:
    return {
        "schema_version": "v7",
        "has_store_models": True,
        "trained_at": "2026-09-08T05:30:00+00:00",
        "store_models": {sid: _entry(date_str, sid) for sid in store_ids},
    }


def _make_registry(tmp_path, *, refresh_sec: int = 900):
    return mr.ForecastModelRegistry(
        supabase_url="https://example.supabase.co",
        service_role_key="test-key",
        bucket="ml-models",
        model_prefix="forecast/latest",
        schema_version="v7",
        cache_dir=tmp_path,
        refresh_sec=refresh_sec,
        request_timeout_sec=5.0,
        download_retry=1,
        logger=logging.getLogger("test"),
    )


def _wire(reg, monkeypatch, holder: dict, downloads: list[str], *, stub_validate: bool = True):
    """ネットワークと LightGBM パースを潰し、ダウンロードされたオブジェクト名を記録する。"""

    monkeypatch.setattr(reg, "_download_to_cache", lambda name, path: downloads.append(name))
    # 実運用と同じく、ダウンロードのたびに新しい dict が出来る（＝使い回しが効いて
    # いなければ必ず download が1回増える）。
    monkeypatch.setattr(reg, "_load_metadata", lambda path: copy.deepcopy(holder["meta"]))
    if stub_validate:
        monkeypatch.setattr(reg, "_validate_metadata", lambda m: None)
    monkeypatch.setattr(
        mr.ForecastModel,
        "from_files",
        classmethod(lambda cls, *, model_men_path, model_women_path: _FakeModel()),
    )


def test_preload_downloads_metadata_once_for_all_stores(tmp_path, monkeypatch):
    """preload 相当（42店を順に get_bundle）で metadata.json の取得は1回だけ。"""
    stores = [f"ol_{i:02d}" for i in range(42)]
    holder = {"meta": _meta(stores)}
    downloads: list[str] = []
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, holder, downloads)

    # oriental/__init__.py::_preload_models と同じ順次呼び出し。
    for sid in stores:
        reg.get_bundle(store_id=sid)

    assert downloads.count("metadata.json") == 1, (
        "同一 refresh ウィンドウ内なら metadata.json は1回しか落とさない"
        "（修正前は42回＝実測 320,848 B。うち41回 ≒ 12.5 MiB が無駄）"
    )
    assert len(downloads) == 1 + 2 * len(stores), "モデル本体は従来どおり店舗ごとに2本"
    assert len(reg._bundles) == len(stores), "42店すべてがロードされている"


def test_stale_metadata_is_not_reused_beyond_refresh_window(tmp_path, monkeypatch):
    """`refresh_sec` を超えた metadata は使い回さない（鮮度の契約は変えない）。"""
    stores = ["ol_a", "ol_b", "ol_c"]
    holder = {"meta": _meta(stores)}
    downloads: list[str] = []
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, holder, downloads)

    reg.get_bundle(store_id="ol_a")  # sweep（ウィンドウを掴む）
    reg.get_bundle(store_id="ol_b")  # 単店・使い回し
    assert downloads.count("metadata.json") == 1

    # sweep ウィンドウは未到来のまま、metadata の取得時刻だけ古くする。
    reg._metadata_fetched_at_unix -= reg.refresh_sec + 1
    reg.get_bundle(store_id="ol_c")

    assert downloads.count("metadata.json") == 2, "古すぎる metadata は使い回さず取り直す"


def test_sweep_still_refetches_metadata_every_window(tmp_path, monkeypatch):
    """sweep 経路（モデル更新を拾う本体）は従来どおり毎ウィンドウ取得する。"""
    stores = ["ol_a", "ol_b"]
    holder = {"meta": _meta(stores)}
    downloads: list[str] = []
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, holder, downloads)

    reg.get_bundle(store_id="ol_a")
    reg.get_bundle(store_id="ol_b")
    assert downloads.count("metadata.json") == 1

    reg._next_refresh_unix = 0.0  # ウィンドウ到来
    reg.get_bundle(store_id="ol_a")
    assert downloads.count("metadata.json") == 2

    # 05:30 の再学習が sweep でちゃんと伝播すること（使い回しで見落とさない）。
    holder["meta"]["store_models"]["ol_b"] = _entry("20260909", "ol_b")
    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_a")
    assert reg.get_bundle(store_id="ol_b").model_names == (
        "model_ol_b_20260909_men.txt",
        "model_ol_b_20260909_women.txt",
    )


def test_store_missing_from_cached_metadata_forces_refetch(tmp_path, monkeypatch):
    """手持ちの metadata に載っていない新店は取り直して解決する（旧挙動を維持）。

    使い回しだけで打ち切ると、新店の初回ロードが最長1ウィンドウ
    （`FORECAST_MODEL_REFRESH_SEC`、既定3時間）"store model not found" で
    失敗し続けることになる。
    """
    holder = {"meta": _meta(["ol_a"])}
    downloads: list[str] = []
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, holder, downloads)

    reg.get_bundle(store_id="ol_a")
    assert downloads.count("metadata.json") == 1

    holder["meta"]["store_models"]["ol_new"] = _entry("20260908", "ol_new")
    bundle = reg.get_bundle(store_id="ol_new")  # ウィンドウ未到来のまま単店ロード

    assert downloads.count("metadata.json") == 2, "解決できない店舗のときだけ取り直す"
    assert bundle.model_names == (
        "model_ol_new_20260908_men.txt",
        "model_ol_new_20260908_women.txt",
    )


def test_reused_metadata_is_still_schema_validated(tmp_path, monkeypatch):
    """使い回した metadata にも schema_version 検証が効く（検証を素通りさせない）。"""
    from oriental.ml.preprocess import FEATURE_COLUMNS

    stores = ["ol_a", "ol_b"]
    meta = _meta(stores)
    meta["feature_columns"] = list(FEATURE_COLUMNS)
    holder = {"meta": meta}
    downloads: list[str] = []
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, holder, downloads, stub_validate=False)  # 本物の検証を使う

    reg.get_bundle(store_id="ol_a")

    # Render 側の FORECAST_MODEL_SCHEMA_VERSION だけ先に上がった状況を模擬。
    reg.schema_version = "v8"
    with pytest.raises(mr.ModelSchemaMismatchError):
        reg.get_bundle(store_id="ol_b")
