"""scripts/cleanup_old_models.py（Storage forecast/latest の世代整理）のユニットテスト。

Supabase Storage への実ネットワークアクセスは一切行わない: list/delete はどちらも
`_storage_request` をモンキーパッチして純粋にロジックだけを検証する。

対象:
  - classify(): ファイル名から「日付入り世代」「エイリアス」「metadata.json」
    「未知」を正しく判定できるか
  - referenced_object_names(): metadata.json の store_models からエイリアス/日付入り
    両方の参照ファイル名を漏れなく集められるか
  - build_plan(): 保持ポリシー本体
      * 最新N世代は無条件で保持
      * metadata.json が参照していれば世代が古くても保持（belt-and-braces）
      * 閉店店舗（metadata未参照）のゴミは新しくなければ削除対象になる
      * エイリアス/非日付/未知オブジェクトは世代グルーピングに入らず常に保持
  - assert_plan_safety(): 安全弁（保持対象混入・95%サニティ上限）が実際に発火するか
  - list_all_objects() / delete_objects(): ページング・バッチングの配線
  - is_retryable_status() / backoff_delay(): 純粋関数
"""

from __future__ import annotations

import json

import pytest

from scripts.cleanup_old_models import (
    CleanupConfig,
    ObjectInfo,
    RetentionPlan,
    assert_plan_safety,
    backoff_delay,
    build_plan,
    classify,
    delete_objects,
    is_retryable_status,
    list_all_objects,
    referenced_object_names,
)


def _cfg(**overrides) -> CleanupConfig:
    base = dict(
        supabase_url="https://example.supabase.co",
        supabase_key="dummy-key",
        bucket="ml-models",
        prefix="forecast/latest",
        retention_generations=7,
        list_page_size=100,
        delete_batch_size=100,
        retries=3,
        backoff_max_sec=1.0,
        max_delete_fraction=0.95,
    )
    base.update(overrides)
    return CleanupConfig(**base)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

def test_classify_dated_generation_men():
    c = classify("model_ol_shibuya_20260808_men.txt")
    assert c.kind == "generation"
    assert c.date_tag == "20260808"


def test_classify_dated_generation_women_with_underscored_store_id():
    c = classify("model_ol_osaka_ekimae_20260101_women.txt")
    assert c.kind == "generation"
    assert c.date_tag == "20260101"


def test_classify_dated_generation_closed_store():
    # sapporo_ag / ay_niigata はもう ALL_STORE_IDS に無いが、ファイル名としては
    # 変わらず日付入り世代パターンに一致する（allow-list判定は classify() の仕事ではない）。
    c = classify("model_ol_sapporo_ag_20260305_men.txt")
    assert c.kind == "generation"
    assert c.date_tag == "20260305"


def test_classify_per_store_alias():
    c = classify("model_ol_shibuya_men.txt")
    assert c.kind == "alias"


def test_classify_global_alias():
    assert classify("model_men.txt").kind == "alias"
    assert classify("model_women.txt").kind == "alias"


def test_classify_metadata():
    assert classify("metadata.json").kind == "metadata"


def test_classify_unknown_falls_back_safely():
    assert classify("readme.txt").kind == "unknown"
    assert classify("model_broken.json").kind == "unknown"


# ---------------------------------------------------------------------------
# referenced_object_names()
# ---------------------------------------------------------------------------

def test_referenced_object_names_collects_store_and_global_entries():
    metadata = {
        "model_men": "model_men.txt",
        "model_women": "model_women.txt",
        "store_models": {
            "ol_shibuya": {
                "model_men": "model_ol_shibuya_men.txt",
                "model_women": "model_ol_shibuya_women.txt",
                "dated_model_men": "model_ol_shibuya_20260808_men.txt",
                "dated_model_women": "model_ol_shibuya_20260808_women.txt",
            },
        },
    }
    refs = referenced_object_names(metadata)
    assert refs == {
        "metadata.json",
        "model_men.txt",
        "model_women.txt",
        "model_ol_shibuya_men.txt",
        "model_ol_shibuya_women.txt",
        "model_ol_shibuya_20260808_men.txt",
        "model_ol_shibuya_20260808_women.txt",
    }


def test_referenced_object_names_tolerates_missing_or_malformed_entries():
    metadata = {"store_models": {"ol_x": {"model_men": None}, "ol_y": "not-a-dict"}}
    refs = referenced_object_names(metadata)
    assert refs == {"metadata.json"}


# ---------------------------------------------------------------------------
# build_plan(): the core retention-selection logic
# ---------------------------------------------------------------------------

def _dated(store: str, date: str, sex: str, size: int = 100) -> ObjectInfo:
    return ObjectInfo(name=f"model_{store}_{date}_{sex}.txt", size_bytes=size)


def test_build_plan_keeps_newest_n_generations_deletes_the_rest():
    # 10 世代分（男女2ファイルずつ）を1店舗で用意し、retention=7 なら
    # 新しい7世代を保持・古い3世代(合計6ファイル)を削除する。
    dates = [f"202608{d:02d}" for d in range(1, 11)]  # 20260801..20260810
    objects = []
    for d in dates:
        objects.append(_dated("ol_shibuya", d, "men"))
        objects.append(_dated("ol_shibuya", d, "women"))
    metadata = {"store_models": {}}  # このstoreは参照していない（純粋にnewest-N判定を見る）
    cfg = _cfg(retention_generations=7)

    plan = build_plan(objects, metadata, cfg)

    assert plan.keep_dates == set(dates[-7:])  # 20260804..20260810
    deleted_dates = {name.split("_")[3] for name in plan.delete_names}
    assert deleted_dates == set(dates[:3])  # 20260801..20260803
    assert len(plan.delete_names) == 6
    assert plan.kept_generation_objects == 14


def test_build_plan_keeps_metadata_referenced_even_if_generation_is_old():
    # ol_broken は 60日前で最後に成功した学習が止まっている（gate/stale繰り返しskip）。
    # newest-7世代の外だが、metadata.json はまだその古い世代を指している => 消してはいけない。
    old_date = "20260101"
    recent_dates = [f"202608{d:02d}" for d in range(1, 9)]  # 8世代、newest7の外に old_date のみ落ちる
    objects = [_dated("ol_broken", old_date, "men"), _dated("ol_broken", old_date, "women")]
    for d in recent_dates:
        objects.append(_dated("ol_active", d, "men"))
        objects.append(_dated("ol_active", d, "women"))

    metadata = {
        "store_models": {
            "ol_broken": {
                "dated_model_men": f"model_ol_broken_{old_date}_men.txt",
                "dated_model_women": f"model_ol_broken_{old_date}_women.txt",
            },
        },
    }
    cfg = _cfg(retention_generations=7)
    plan = build_plan(objects, metadata, cfg)

    assert old_date not in plan.keep_dates  # 世代としては保持対象の外
    assert f"forecast/latest/model_ol_broken_{old_date}_men.txt" not in plan.delete_names
    assert f"forecast/latest/model_ol_broken_{old_date}_women.txt" not in plan.delete_names


def test_build_plan_deletes_closed_store_garbage():
    # sapporo_ag は ALL_STORE_IDS から除外済み => metadata.json の store_models に
    # もう存在しない。古い世代なら削除対象になるべき（特別扱い不要、一般ロジックのまま）。
    # newest-7 の外に押し出すため、他店舗の最近8世代をフィラーとして混ぜる
    # （sapporo_ag は2026-07-11閉店後に二度と学習されないので、これ以降の世代には
    # 一切登場しない＝実運用と同じ状況）。
    old_date = "20260305"
    objects = [_dated("ol_sapporo_ag", old_date, "men"), _dated("ol_sapporo_ag", old_date, "women")]
    for d in (f"202608{d:02d}" for d in range(1, 8)):  # exactly 7 recent generations, active store only
        objects.append(_dated("ol_active", d, "men"))
    metadata = {"store_models": {}}  # 閉店店舗は既に filter 済みで存在しない
    cfg = _cfg(retention_generations=7)

    plan = build_plan(objects, metadata, cfg)

    assert old_date not in plan.keep_dates
    assert f"forecast/latest/model_ol_sapporo_ag_{old_date}_men.txt" in plan.delete_names
    assert f"forecast/latest/model_ol_sapporo_ag_{old_date}_women.txt" in plan.delete_names
    assert plan.delete_size_bytes == 200


def test_build_plan_never_deletes_aliases_or_metadata_or_unknown():
    old_date = "20260101"
    objects = [
        _dated("ol_shibuya", old_date, "men"),
        ObjectInfo(name="model_ol_shibuya_men.txt", size_bytes=50),
        ObjectInfo(name="model_men.txt", size_bytes=50),
        ObjectInfo(name="model_women.txt", size_bytes=50),
        ObjectInfo(name="metadata.json", size_bytes=10),
        ObjectInfo(name="unexpected_file.bin", size_bytes=10),
    ]
    # newest-7 の外に押し出すため、他店舗の最近7世代をフィラーとして混ぜる
    for d in (f"202608{d:02d}" for d in range(1, 8)):
        objects.append(_dated("ol_active", d, "men"))
    metadata = {"store_models": {}}
    cfg = _cfg(retention_generations=7)

    plan = build_plan(objects, metadata, cfg)

    # 唯一の削除候補は古い日付入りファイル1件のみ（エイリアス/metadata/未知は無傷）
    assert plan.delete_names == ["forecast/latest/model_ol_shibuya_20260101_men.txt"]
    assert plan.alias_count == 4  # per-store alias + model_men.txt + model_women.txt + metadata.json
    assert "unexpected_file.bin" in plan.unknown_names


def test_build_plan_empty_objects_is_a_noop():
    plan = build_plan([], {"store_models": {}}, _cfg())
    assert plan.delete_names == []
    assert plan.total_objects == 0


# ---------------------------------------------------------------------------
# assert_plan_safety(): the last-resort guardrails
# ---------------------------------------------------------------------------

def test_assert_plan_safety_passes_for_a_correct_plan():
    objects = [_dated("ol_shibuya", "20260101", "men")]
    plan = build_plan(objects, {"store_models": {}}, _cfg())
    # sanity: only 1 generation exists, retention=7 keeps it -> nothing to delete
    assert plan.delete_names == []
    assert_plan_safety(plan, _cfg())  # must not raise


def test_assert_plan_safety_raises_when_kept_generation_is_wrongly_in_delete_set():
    obj = _dated("ol_shibuya", "20260808", "men")
    cfg = _cfg()
    plan = RetentionPlan(
        total_objects=1,
        total_size_bytes=100,
        generations={"20260808": [obj]},
        keep_dates={"20260808"},
        delete_names=["forecast/latest/model_ol_shibuya_20260808_men.txt"],  # BUG: kept generation deleted
        delete_size_bytes=100,
        kept_generation_objects=0,
        alias_count=0,
        unknown_names=[],
        referenced=set(),
    )
    with pytest.raises(AssertionError, match="KEPT generation"):
        assert_plan_safety(plan, cfg)


def test_assert_plan_safety_raises_when_referenced_object_is_wrongly_in_delete_set():
    cfg = _cfg()
    plan = RetentionPlan(
        total_objects=1,
        total_size_bytes=100,
        generations={},
        keep_dates=set(),
        delete_names=["forecast/latest/model_ol_shibuya_men.txt"],  # BUG: referenced alias deleted
        delete_size_bytes=100,
        kept_generation_objects=0,
        alias_count=1,
        unknown_names=[],
        referenced={"model_ol_shibuya_men.txt"},
    )
    with pytest.raises(AssertionError, match="referenced by metadata.json"):
        assert_plan_safety(plan, cfg)


def test_assert_plan_safety_aborts_when_delete_fraction_exceeds_sanity_cap():
    cfg = _cfg(max_delete_fraction=0.5)
    plan = RetentionPlan(
        total_objects=10,
        total_size_bytes=1000,
        generations={},
        keep_dates=set(),
        delete_names=[f"forecast/latest/junk_{i}.txt" for i in range(9)],  # 90% > 50% cap
        delete_size_bytes=900,
        kept_generation_objects=1,
        alias_count=0,
        unknown_names=[],
        referenced=set(),
    )
    with pytest.raises(SystemExit, match="sanity cap"):
        assert_plan_safety(plan, cfg)


def test_assert_plan_safety_allows_exactly_at_cap():
    cfg = _cfg(max_delete_fraction=0.5)
    plan = RetentionPlan(
        total_objects=10,
        total_size_bytes=1000,
        generations={},
        keep_dates=set(),
        delete_names=[f"forecast/latest/junk_{i}.txt" for i in range(5)],  # exactly 50%
        delete_size_bytes=500,
        kept_generation_objects=5,
        alias_count=0,
        unknown_names=[],
        referenced=set(),
    )
    assert_plan_safety(plan, cfg)  # must not raise (boundary is not-over, not >=)


# ---------------------------------------------------------------------------
# CleanupConfig.validate()
# ---------------------------------------------------------------------------

def test_cfg_validate_requires_retention_at_least_one():
    with pytest.raises(SystemExit):
        _cfg(retention_generations=0).validate()


def test_cfg_validate_clamps_page_size_over_100():
    cfg = _cfg(list_page_size=500)
    cfg.validate()
    assert cfg.list_page_size == 100


def test_cfg_validate_requires_credentials():
    with pytest.raises(SystemExit):
        _cfg(supabase_url="").validate()


# ---------------------------------------------------------------------------
# is_retryable_status() / backoff_delay(): pure functions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [(429, True), (500, True), (502, True), (544, True), (400, False), (404, False), (200, False)])
def test_is_retryable_status(code, expected):
    assert is_retryable_status(code) is expected


def test_backoff_delay_grows_then_caps():
    assert backoff_delay(1, cap=100.0) == 2.0
    assert backoff_delay(3, cap=100.0) == 8.0
    assert backoff_delay(10, cap=5.0) == 5.0


# ---------------------------------------------------------------------------
# list_all_objects() / delete_objects(): pagination and batching, HTTP mocked out
# ---------------------------------------------------------------------------

def test_list_all_objects_paginates_until_a_short_page(monkeypatch):
    pages = [
        [{"name": f"model_ol_x_2026080{i}_men.txt", "id": f"id{i}", "metadata": {"size": 10}} for i in range(100)],
        [{"name": "model_ol_x_20260899_men.txt", "id": "idlast", "metadata": {"size": 20}}],
    ]
    calls = []

    def fake_request(req, *, cfg, what):
        calls.append(what)
        return json.dumps(pages.pop(0)).encode("utf-8")

    monkeypatch.setattr("scripts.cleanup_old_models._storage_request", fake_request)
    cfg = _cfg(list_page_size=100)

    objects = list_all_objects(cfg)

    assert len(objects) == 101
    assert "offset=0" in calls[0]
    assert "offset=100" in calls[1]
    assert len(calls) == 2  # stops once a page shorter than page_size is seen


def test_list_all_objects_skips_folder_placeholder_entries(monkeypatch):
    page = [
        {"name": "a-folder", "id": None, "metadata": None},
        {"name": "model_ol_x_20260808_men.txt", "id": "id1", "metadata": {"size": 5}},
    ]

    def fake_request(req, *, cfg, what):
        return json.dumps(page).encode("utf-8")

    monkeypatch.setattr("scripts.cleanup_old_models._storage_request", fake_request)
    cfg = _cfg(list_page_size=100)

    objects = list_all_objects(cfg)

    assert len(objects) == 1
    assert objects[0].name == "model_ol_x_20260808_men.txt"


def test_delete_objects_batches_by_delete_batch_size(monkeypatch):
    seen_bodies = []

    def fake_request(req, *, cfg, what):
        seen_bodies.append(json.loads(req.data))
        return b"[]"

    monkeypatch.setattr("scripts.cleanup_old_models._storage_request", fake_request)
    cfg = _cfg(delete_batch_size=3)
    names = [f"forecast/latest/junk_{i}.txt" for i in range(7)]  # 3 + 3 + 1

    deleted = delete_objects(names, cfg)

    assert deleted == 7
    assert [len(b["prefixes"]) for b in seen_bodies] == [3, 3, 1]
    assert seen_bodies[0]["prefixes"] == names[0:3]
    assert seen_bodies[-1]["prefixes"] == names[6:7]


def test_delete_objects_noop_for_empty_list(monkeypatch):
    def fake_request(req, *, cfg, what):
        raise AssertionError("should never be called for an empty delete list")

    monkeypatch.setattr("scripts.cleanup_old_models._storage_request", fake_request)
    assert delete_objects([], _cfg()) == 0
