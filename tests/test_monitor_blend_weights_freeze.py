"""blend_weights 凍結監視（scripts/monitor/check_blend_weights_freeze.py）の単体テスト。

2026-08-22 重み凍結（外部レビュー討議 plan/FORECAST_FREEZE_DEBATE_FINDINGS.md F-5/F-6）。

もとになる思想は tests/test_monitor_published_checks.py（importlib で単体モジュール読込）と
tests/test_score_blend_weights.py（storage_get/storage_put 相当の関数を monkeypatch で
差し替え、urllib へは一切アクセスしない）を踏襲する。`evaluate()` / `restore()` は
fetch/put をただの Callable として受け取る純粋関数なので、辞書ベースの fake で完全に検証でき、
main() 経由のテストだけモジュール変数 storage_get/storage_put を monkeypatch して
env 配線・引数解析（--restore）の配線を確認する。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"


def _load(name: str):
    """scripts/monitor/<name>.py を単体モジュールとして読み込む（実行時と同じ形）。"""
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bwf = _load("check_blend_weights_freeze")


NOW = datetime(2026, 8, 22, 6, 10, tzinfo=timezone.utc)


def _bytes(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def _canonical_doc(weights: dict[str, float] | None = None) -> dict:
    return {
        "generated_at": "2026-08-15T06:10:00+00:00",
        "nights_used": 7,
        "nights_excluded_contaminated": [],
        "weights": weights if weights is not None else {"ol_shibuya": 0.6, "ay_ueno": 0.4},
    }


def _manifest_doc(*, state: str, freeze_id: str, activated_at: str) -> dict:
    return {
        "schema": 1,
        "state": state,
        "freeze_id": freeze_id,
        "activated_at": activated_at,
        "source_generated_at": "2026-08-15T06:10:00+00:00",
        "backup_path": f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json",
        "store_count": 2,
    }


def _shadow_doc(generated_at: str) -> dict:
    return {"generated_at": generated_at, "publish_eligible": False, "weights": {"ol_shibuya": 0.55}}


def _fetch_from(store: dict[str, bytes]):
    def fetch(path: str) -> bytes | None:
        return store.get(path)
    return fetch


class Test健全な凍結:
    def test_active_で全部一致していればOK(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        activated_at = (NOW - timedelta(hours=40)).isoformat()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)
        shadow_raw = _bytes(_shadow_doc((NOW - timedelta(hours=5)).isoformat()))

        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
            bwf.SHADOW_PATH: shadow_raw,
        }
        detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert problems == []
        assert "canonical hash: OK" in detail
        assert "generation: OK" in detail
        assert "shadow: OK" in detail


class Test凍結未発動:
    def test_manifestが無ければexit0扱いで問題なし(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        store = {bwf.CANONICAL_PATH: canonical_raw}
        detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert problems == []
        assert "凍結は未発動です" in detail

    def test_state_inactiveも問題なし(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        manifest = _manifest_doc(state="inactive", freeze_id=freeze_id, activated_at=NOW.isoformat())
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
        }
        detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert problems == []
        assert "state=inactive" in detail

    def test_未知のstateはfail_closed(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        manifest = _manifest_doc(state="weekly", freeze_id=freeze_id, activated_at=NOW.isoformat())
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
        }
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert problems and "未知の値" in problems[0]


class Testhash不一致:
    def test_canonicalが凍結後に書き換わっていれば検知する(self) -> None:
        original_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(original_raw).hexdigest()
        tampered_raw = _bytes(_canonical_doc({"ol_shibuya": 0.99, "ay_ueno": 0.01}))
        activated_at = (NOW - timedelta(hours=40)).isoformat()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)

        store = {
            bwf.CANONICAL_PATH: tampered_raw,  # 配信ファイルが凍結後に上書きされた
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": original_raw,
            bwf.SHADOW_PATH: _bytes(_shadow_doc((NOW - timedelta(hours=1)).isoformat())),
        }
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("canonical の hash が freeze_id と不一致" in p for p in problems)

    def test_バックアップ世代自体が壊れていても検知する(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        activated_at = (NOW - timedelta(hours=40)).isoformat()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": b'{"weights": {"corrupted": true}}',
            bwf.SHADOW_PATH: _bytes(_shadow_doc((NOW - timedelta(hours=1)).isoformat())),
        }
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("バックアップ世代の hash が freeze_id と不一致" in p for p in problems)


class Testshadow陳腐化:
    def test_発動から30時間未満は猶予されて問題にならない(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        activated_at = (NOW - timedelta(hours=5)).isoformat()  # まだ猶予中
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
            # shadow は意図的に置かない（score がまだ1回も回っていない）
        }
        detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert problems == []
        assert "猶予中" in detail

    def test_30時間超で48時間より古いshadowは失敗(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        activated_at = (NOW - timedelta(hours=40)).isoformat()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)
        stale_shadow = _bytes(_shadow_doc((NOW - timedelta(hours=49)).isoformat()))
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
            bwf.SHADOW_PATH: stale_shadow,
        }
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("shadow が古すぎます" in p for p in problems)

    def test_30時間超でshadowが無ければ失敗(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        activated_at = (NOW - timedelta(hours=40)).isoformat()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=activated_at)
        store = {
            bwf.CANONICAL_PATH: canonical_raw,
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
        }
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("score ジョブが動いていない疑い" in p for p in problems)


class Testcanonical欠損:
    def test_canonicalが無ければ失敗(self) -> None:
        store: dict[str, bytes] = {}
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("canonical が見つかりません" in p for p in problems)

    def test_canonicalのweightsが範囲外なら失敗(self) -> None:
        bad = _bytes(_canonical_doc({"ol_shibuya": 1.5}))
        store = {bwf.CANONICAL_PATH: bad}
        _detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        assert any("有限値/0..1範囲外" in p for p in problems)

    def test_canonicalが壊れていてもmanifestが無ければ未発動ログは出る(self) -> None:
        store: dict[str, bytes] = {}
        detail, problems = bwf.evaluate(_fetch_from(store), NOW)
        # canonical 欠損は独立した問題として残るが、manifest 側は未発動ログのみ。
        assert problems != []
        assert "凍結は未発動です" in detail


class Test復元:
    def test_検証OKなら書き込んでread_backまで確認する(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=NOW.isoformat())
        store = {
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
        }
        written: dict[str, bytes] = {}

        def fetch(path: str) -> bytes | None:
            if path == bwf.CANONICAL_PATH:
                return written.get(bwf.CANONICAL_PATH, store.get(path))
            return store.get(path)

        def put(path: str, data: bytes) -> None:
            written[path] = data

        detail, code = bwf.restore(fetch, put, NOW)
        assert code == 0
        assert written[bwf.CANONICAL_PATH] == canonical_raw
        assert "復元完了" in detail

    def test_hash不一致なら何も書き込まずexit1(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        manifest = _manifest_doc(state="active", freeze_id=freeze_id, activated_at=NOW.isoformat())
        tampered_generation = _bytes(_canonical_doc({"ol_shibuya": 0.1, "ay_ueno": 0.9}))
        store = {
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": tampered_generation,  # freeze_id と不一致
        }
        put_calls: list[tuple[str, bytes]] = []

        def fetch(path: str) -> bytes | None:
            return store.get(path)

        def put(path: str, data: bytes) -> None:
            put_calls.append((path, data))

        detail, code = bwf.restore(fetch, put, NOW)
        assert code == 1
        assert put_calls == []
        assert "hash が freeze_id と不一致" in detail

    def test_manifestがinactiveなら復元しない(self) -> None:
        canonical_raw = _bytes(_canonical_doc())
        freeze_id = hashlib.sha256(canonical_raw).hexdigest()
        manifest = _manifest_doc(state="inactive", freeze_id=freeze_id, activated_at=NOW.isoformat())
        store = {
            bwf.MANIFEST_PATH: _bytes(manifest),
            f"{bwf.GENERATIONS_PREFIX}{freeze_id}.json": canonical_raw,
        }
        put_calls: list[tuple[str, bytes]] = []
        detail, code = bwf.restore(
            lambda p: store.get(p), lambda p, d: put_calls.append((p, d)), NOW
        )
        assert code == 1
        assert put_calls == []
        assert "state が active ではありません" in detail

    def test_manifestが無ければ復元しない(self) -> None:
        put_calls: list[tuple[str, bytes]] = []
        detail, code = bwf.restore(
            lambda p: None, lambda p, d: put_calls.append((p, d)), NOW
        )
        assert code == 1
        assert put_calls == []
        assert "manifest が見つかりません" in detail


class Testmain配線:
    def test_env未設定ならSupabaseに触れず1で終わる(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.setattr(sys, "argv", ["check_blend_weights_freeze.py"])
        assert bwf.main() == 1
        assert "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定" in capsys.readouterr().out

    def test_restoreフラグがrestoreを呼ぶ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "http://x")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setattr(sys, "argv", ["check_blend_weights_freeze.py", "--restore"])

        calls = {"restore": 0, "evaluate": 0}

        def fake_restore(fetch, put, now):
            calls["restore"] += 1
            return "restore called", 0

        def fake_evaluate(fetch, now):
            calls["evaluate"] += 1
            return "evaluate called", []

        monkeypatch.setattr(bwf, "restore", fake_restore)
        monkeypatch.setattr(bwf, "evaluate", fake_evaluate)
        monkeypatch.setattr(bwf, "storage_get", lambda *a, **k: None)
        monkeypatch.setattr(bwf, "storage_put", lambda *a, **k: None)

        assert bwf.main() == 0
        assert calls == {"restore": 1, "evaluate": 0}

    def test_フラグ無しはevaluateを呼ぶ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "http://x")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setattr(sys, "argv", ["check_blend_weights_freeze.py"])

        calls = {"restore": 0, "evaluate": 0}

        def fake_restore(fetch, put, now):
            calls["restore"] += 1
            return "restore called", 0

        def fake_evaluate(fetch, now):
            calls["evaluate"] += 1
            return "evaluate called", []

        monkeypatch.setattr(bwf, "restore", fake_restore)
        monkeypatch.setattr(bwf, "evaluate", fake_evaluate)
        monkeypatch.setattr(bwf, "storage_get", lambda *a, **k: None)
        monkeypatch.setattr(bwf, "storage_put", lambda *a, **k: None)

        assert bwf.main() == 0
        assert calls == {"restore": 0, "evaluate": 1}

    def test_ストレージ照会が例外を投げたらfail_closedで1(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setenv("SUPABASE_URL", "http://x")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        monkeypatch.setattr(sys, "argv", ["check_blend_weights_freeze.py"])

        def boom(*a, **k):
            raise RuntimeError("storage down")

        monkeypatch.setattr(bwf, "storage_get", boom)
        assert bwf.main() == 1
        assert "Storage 照会に失敗しました" in capsys.readouterr().out
