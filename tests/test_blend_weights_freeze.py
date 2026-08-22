"""重み凍結 (2026-08-22, plan/FORECAST_FREEZE_DEBATE_FINDINGS.md F-1/F-3、
統合裁定: plan/FORECAST_FREEZE_DEBATE_2026-08-22.md 末尾【統合裁定】) のテスト。

scripts/score_forecasts.py に追加した以下を検証する（全てモック・ネットワーク無し）:
  - BLEND_WEIGHTS_MODE の解決（既定frozen・許可値2つ・未知値fail-closed）
  - legacy candidate の妥当性検証（非空・既知store_id・0..1有限）
  - frozen モードの状態機械（canonical不変・世代+manifest作成・冪等・改変検知）
  - legacy_daily モード（有効candidateのみpublish・空candidateは回帰させない）
  - shadow（同日upsert・60夜cap）
  - main() 経由での配線（受入条件の核心: 凍結モードでは score が成功しても
    配信ファイルへの PUT が 0 回であること）
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import pytest

import scripts._stores_common as stores_common
import scripts.score_forecasts as sf


# --------------------------------------------------------------------------- #
# テスト用フェイク Storage: {path: bytes} の単純な辞書。sf._storage_get /
# sf._storage_put と同じシグネチャ (bucket, path, [payload,] url, key) を持つ。
# --------------------------------------------------------------------------- #
class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []  # PUT された path を呼び出し順に記録（回数検証用）

    def get(self, bucket, path, url, key):
        return self.objects.get(path)

    def put(self, bucket, path, payload, url, key):
        self.objects[path] = payload
        self.puts.append(path)


def _known_ids() -> set[str]:
    return set(stores_common.slug_to_store_id_map().values())


def _pick_two_known_ids() -> tuple[str, str]:
    ids = sorted(_known_ids())
    return ids[0], ids[1]


def _wire_storage(monkeypatch, storage: FakeStorage) -> None:
    monkeypatch.setattr(sf, "_storage_get", storage.get)
    monkeypatch.setattr(sf, "_storage_put", storage.put)


# --------------------------------------------------------------------------- #
# _resolve_blend_weights_mode
# --------------------------------------------------------------------------- #

def test_mode_unset_defaults_to_frozen():
    assert sf._resolve_blend_weights_mode("") == ("frozen", True)


def test_mode_frozen_explicit_valid():
    assert sf._resolve_blend_weights_mode("frozen") == ("frozen", True)


def test_mode_legacy_daily_valid():
    assert sf._resolve_blend_weights_mode("legacy_daily") == ("legacy_daily", True)


def test_mode_whitespace_padded_still_resolves():
    assert sf._resolve_blend_weights_mode("  frozen  ") == ("frozen", True)


@pytest.mark.parametrize("raw", ["weekly", "true", "1", "Frozen", "FROZEN", "legacy", "typo"])
def test_mode_unknown_values_fail_closed(raw):
    mode, valid = sf._resolve_blend_weights_mode(raw)
    assert valid is False
    assert mode == raw.strip()


# --------------------------------------------------------------------------- #
# _candidate_valid
# --------------------------------------------------------------------------- #

def test_candidate_empty_is_invalid():
    assert sf._candidate_valid({}, _known_ids()) is False


def test_candidate_unknown_store_id_is_invalid():
    assert sf._candidate_valid({"ol_not_a_real_store": 0.5}, _known_ids()) is False


def test_candidate_out_of_range_value_is_invalid():
    sid, _ = _pick_two_known_ids()
    assert sf._candidate_valid({sid: 1.5}, _known_ids()) is False
    assert sf._candidate_valid({sid: -0.1}, _known_ids()) is False


def test_candidate_non_finite_value_is_invalid():
    sid, _ = _pick_two_known_ids()
    assert sf._candidate_valid({sid: float("nan")}, _known_ids()) is False
    assert sf._candidate_valid({sid: float("inf")}, _known_ids()) is False


def test_candidate_unknown_store_master_fails_closed():
    sid, _ = _pick_two_known_ids()
    assert sf._candidate_valid({sid: 0.5}, None) is False


def test_candidate_valid_case():
    sid1, sid2 = _pick_two_known_ids()
    assert sf._candidate_valid({sid1: 0.9, sid2: 0.15}, _known_ids()) is True


# --------------------------------------------------------------------------- #
# _run_frozen_cycle: 状態機械
# --------------------------------------------------------------------------- #

def test_frozen_cycle_bootstrap_no_canonical_is_noop_success(monkeypatch):
    storage = FakeStorage()
    _wire_storage(monkeypatch, storage)
    freeze_id, ok = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok is True
    assert freeze_id is None
    assert storage.puts == []  # 何も書かない


def _seed_canonical(storage: FakeStorage, weights: dict, generated_at: str = "2026-08-20T00:00:00+00:00") -> bytes:
    payload = json.dumps({"generated_at": generated_at, "nights_used": 5, "weights": weights}, ensure_ascii=False).encode("utf-8")
    storage.objects[sf.CANONICAL_BLEND_WEIGHTS_PATH] = payload
    return payload


def test_frozen_cycle_first_activation_creates_generation_and_manifest_without_touching_canonical(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    raw = _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    sha = hashlib.sha256(raw).hexdigest()
    _wire_storage(monkeypatch, storage)

    freeze_id, ok = sf._run_frozen_cycle("b", "http://x", "k")

    assert ok is True
    assert freeze_id == sha
    # canonical 自体への PUT は 0 回（世代/manifestのみ書かれる）
    assert sf.CANONICAL_BLEND_WEIGHTS_PATH not in storage.puts
    gen_path = f"{sf.FREEZE_GENERATIONS_PREFIX}{sha}.json"
    assert gen_path in storage.puts
    assert storage.objects[gen_path] == raw  # 世代は canonical と同一バイト列
    assert sf.FREEZE_MANIFEST_PATH in storage.puts
    manifest = json.loads(storage.objects[sf.FREEZE_MANIFEST_PATH].decode())
    assert manifest == {
        "schema": 1,
        "state": "active",
        "freeze_id": sha,
        "activated_at": manifest["activated_at"],
        "source_generated_at": "2026-08-20T00:00:00+00:00",
        "backup_path": gen_path,
        "store_count": 2,
    }


def test_frozen_cycle_second_run_is_idempotent_no_double_put(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    _wire_storage(monkeypatch, storage)

    freeze_id1, ok1 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok1 is True
    puts_after_first = list(storage.puts)

    freeze_id2, ok2 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok2 is True
    assert freeze_id2 == freeze_id1
    # 2回目は何も PUT しない（冪等）
    assert storage.puts == puts_after_first


def test_frozen_cycle_detects_canonical_changed_while_active_and_refuses_to_write(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    _wire_storage(monkeypatch, storage)

    freeze_id1, ok1 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok1 is True
    puts_after_activation = list(storage.puts)

    # 凍結中に canonical のバイト列が変わった（本来あってはならない異常）。
    _seed_canonical(storage, {sid1: 0.9, sid2: 0.1})

    freeze_id2, ok2 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok2 is False
    assert freeze_id2 == freeze_id1  # manifest の古い freeze_id を返す（上書きしない）
    # 何も新しく書かれていない（canonical にも一切触れない）
    assert storage.puts == puts_after_activation


def test_frozen_cycle_after_inactive_creates_new_generation_not_reusing_old(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    raw1 = _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    sha1 = hashlib.sha256(raw1).hexdigest()
    _wire_storage(monkeypatch, storage)

    freeze_id1, ok1 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok1 is True and freeze_id1 == sha1
    gen_path1 = f"{sf.FREEZE_GENERATIONS_PREFIX}{sha1}.json"
    assert gen_path1 in storage.puts

    # legacy_daily 相当: manifest を inactive にし、canonical の値も変える。
    manifest = json.loads(storage.objects[sf.FREEZE_MANIFEST_PATH].decode())
    manifest["state"] = "inactive"
    storage.objects[sf.FREEZE_MANIFEST_PATH] = json.dumps(manifest, ensure_ascii=False).encode()
    raw2 = _seed_canonical(storage, {sid1: 0.55, sid2: 0.45}, generated_at="2026-08-21T00:00:00+00:00")
    sha2 = hashlib.sha256(raw2).hexdigest()
    assert sha2 != sha1

    freeze_id3, ok3 = sf._run_frozen_cycle("b", "http://x", "k")
    assert ok3 is True
    assert freeze_id3 == sha2
    gen_path2 = f"{sf.FREEZE_GENERATIONS_PREFIX}{sha2}.json"
    assert gen_path2 in storage.puts
    assert gen_path2 != gen_path1
    # 旧世代ファイルは残るが、上書きされていない(古い世代を掴んで再利用していない)。
    assert storage.objects[gen_path1] == raw1
    assert storage.objects[gen_path2] == raw2
    manifest_final = json.loads(storage.objects[sf.FREEZE_MANIFEST_PATH].decode())
    assert manifest_final["freeze_id"] == sha2
    assert manifest_final["state"] == "active"


# --------------------------------------------------------------------------- #
# _run_legacy_daily_cycle
# --------------------------------------------------------------------------- #

def test_legacy_daily_empty_candidate_does_not_touch_canonical_and_fails(monkeypatch):
    storage = FakeStorage()
    _wire_storage(monkeypatch, storage)
    weights_payload = {"generated_at": "x", "nights_used": 0, "nights_excluded_contaminated": [], "weights": {}}

    freeze_id, ok = sf._run_legacy_daily_cycle("b", "http://x", "k", {}, weights_payload)
    assert ok is False
    assert sf.CANONICAL_BLEND_WEIGHTS_PATH not in storage.puts


def test_legacy_daily_valid_candidate_publishes_and_deactivates_active_manifest(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    storage.objects[sf.FREEZE_MANIFEST_PATH] = json.dumps({
        "schema": 1, "state": "active", "freeze_id": "deadbeef",
        "activated_at": "2026-08-01T00:00:00+00:00", "source_generated_at": None,
        "backup_path": f"{sf.FREEZE_GENERATIONS_PREFIX}deadbeef.json", "store_count": 2,
    }).encode()
    _wire_storage(monkeypatch, storage)

    weights = {sid1: 0.8, sid2: 0.2}
    weights_payload = {"generated_at": "x", "nights_used": 7, "nights_excluded_contaminated": [], "weights": weights}

    freeze_id, ok = sf._run_legacy_daily_cycle("b", "http://x", "k", weights, weights_payload)
    assert ok is True
    assert freeze_id is None  # manifest を inactive にしたので、もう active な freeze は無い
    assert sf.CANONICAL_BLEND_WEIGHTS_PATH in storage.puts
    assert json.loads(storage.objects[sf.CANONICAL_BLEND_WEIGHTS_PATH].decode()) == weights_payload
    manifest_after = json.loads(storage.objects[sf.FREEZE_MANIFEST_PATH].decode())
    assert manifest_after["state"] == "inactive"
    assert manifest_after["freeze_id"] == "deadbeef"  # freeze_id 自体は保持（監査用）


# --------------------------------------------------------------------------- #
# _write_blend_shadow: 同日 upsert + 60夜 cap
# --------------------------------------------------------------------------- #

def test_shadow_upserts_same_night_date(monkeypatch):
    storage = FakeStorage()
    _wire_storage(monkeypatch, storage)

    ok1 = sf._write_blend_shadow("b", "http://x", "k", "20260820", {"a": 0.5}, 3, None)
    assert ok1 is True
    ok2 = sf._write_blend_shadow("b", "http://x", "k", "20260820", {"a": 0.7}, 4, "somesha")
    assert ok2 is True

    doc = json.loads(storage.objects[sf.SHADOW_BLEND_WEIGHTS_PATH].decode())
    assert doc["publish_eligible"] is False
    assert doc["source_metric"] == "served_live_mae_legacy"
    assert doc["freeze_id"] == "somesha"
    assert list(doc["nights"].keys()) == ["20260820"]  # 上書き、重複しない
    assert doc["nights"]["20260820"] == {"weights": {"a": 0.7}, "nights_used": 4}


def test_shadow_caps_at_60_nights_keeping_most_recent(monkeypatch):
    storage = FakeStorage()
    _wire_storage(monkeypatch, storage)

    for i in range(65):
        night = f"202601{i:02d}" if i < 32 else f"202602{i - 31:02d}"
        sf._write_blend_shadow("b", "http://x", "k", night, {}, 0, None)

    doc = json.loads(storage.objects[sf.SHADOW_BLEND_WEIGHTS_PATH].decode())
    assert len(doc["nights"]) == 60
    # 最新(数字として最大)の日付キーが残っている
    assert max(doc["nights"].keys()) in doc["nights"]


# --------------------------------------------------------------------------- #
# main() 統合: 受入条件の核心 = 凍結モードでは score が成功しても配信ファイルへの
# PUT が 0 回であること。
# --------------------------------------------------------------------------- #

def _wire_main(monkeypatch, storage: FakeStorage, *, now_total=48.0, prev_total=10.0):
    """1店舗の score run を配線する。snapshot 以外の GET/PUT は storage 経由。"""
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("ACCURACY_FAIL_ON_BASELINE_LOSS", "0")  # baseline勝敗はこのテストの対象外

    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slot = base.replace(hour=23, minute=0, second=0, microsecond=0)
    snapshot = {
        "expected_slugs": ["shibuya"],
        "by_slug": {"shibuya": [{"ts": slot.isoformat(), "total_pred": 50.0}]},
    }
    storage.objects["accuracy/snapshots/" + night_date + ".json"] = json.dumps(snapshot).encode()

    _wire_storage(monkeypatch, storage)
    monkeypatch.setattr(sf, "_alert", lambda msg: None)
    monkeypatch.setattr(sf, "compute_blend_weights", lambda *a, **k: {})

    now_rows = [{"ts": slot.isoformat(), "total": float(now_total)}]
    prev_rows = [{"ts": (slot - timedelta(days=7)).isoformat(), "total": float(prev_total)}]
    calls = {"i": 0}

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        calls["i"] += 1
        return now_rows if calls["i"] == 1 else prev_rows

    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)
    return night_date


def test_main_frozen_default_never_puts_canonical(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    monkeypatch.delenv("BLEND_WEIGHTS_MODE", raising=False)
    night_date = _wire_main(monkeypatch, storage)

    rc = sf.main()

    assert sf.CANONICAL_BLEND_WEIGHTS_PATH not in storage.puts
    assert sf.SHADOW_BLEND_WEIGHTS_PATH in storage.puts
    assert sf.FREEZE_MANIFEST_PATH in storage.puts
    manifest = json.loads(storage.objects[sf.FREEZE_MANIFEST_PATH].decode())
    assert manifest["state"] == "active"
    shadow = json.loads(storage.objects[sf.SHADOW_BLEND_WEIGHTS_PATH].decode())
    assert night_date in shadow["nights"]
    assert rc == 0  # freeze自体は成功、baseline判定はoff-switchで無効化済み


def test_main_unknown_mode_fails_closed_and_never_puts_canonical(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    _seed_canonical(storage, {sid1: 0.6, sid2: 0.4})
    monkeypatch.setenv("BLEND_WEIGHTS_MODE", "weekly")  # 未実装の正常解除先。今回はfail-closed対象
    _wire_main(monkeypatch, storage)

    rc = sf.main()

    assert rc == 1
    assert sf.CANONICAL_BLEND_WEIGHTS_PATH not in storage.puts
    # shadow は未知モードでも書く(できる範囲は行う)。
    assert sf.SHADOW_BLEND_WEIGHTS_PATH in storage.puts


def test_main_legacy_daily_empty_candidate_no_regression(monkeypatch):
    """現行(凍結導入前)は重み0件でも空JSONをcanonicalへ書いていた——回帰させない。"""
    storage = FakeStorage()
    monkeypatch.setenv("BLEND_WEIGHTS_MODE", "legacy_daily")
    _wire_main(monkeypatch, storage)  # compute_blend_weights は {} を返すよう配線済み

    rc = sf.main()

    assert rc == 1
    assert sf.CANONICAL_BLEND_WEIGHTS_PATH not in storage.puts


def test_main_legacy_daily_valid_candidate_publishes(monkeypatch):
    storage = FakeStorage()
    sid1, sid2 = _pick_two_known_ids()
    monkeypatch.setenv("BLEND_WEIGHTS_MODE", "legacy_daily")
    _wire_main(monkeypatch, storage)
    monkeypatch.setattr(sf, "compute_blend_weights", lambda *a, **k: {sid1: 0.7, sid2: 0.3})

    sf.main()

    assert sf.CANONICAL_BLEND_WEIGHTS_PATH in storage.puts
    published = json.loads(storage.objects[sf.CANONICAL_BLEND_WEIGHTS_PATH].decode())
    assert published["weights"] == {sid1: 0.7, sid2: 0.3}
