"""F1 番犬: 不完全なスナップショットを正規パスへ昇格させない（validate-before-promote）。

背景（外部レビュー 2026-08-21 / docs/FAILURE_MAP.md 順位3）:
旧実装は予測 API が全滅・一部失敗しても「取れた店だけの by_slug」をその夜の**正規パス**
`accuracy/snapshots/<date>.json` へ保存していた。空でも保存してから exit 1、部分欠落なら
exit 0。翌朝の score_forecasts.py は `expected = len(by_slug)`＝そのスナップショット自身の
件数を分母にするため、
  - 空 → expected==0 で coverage 検査が無効化（30日以上気づかなかった実績あり）
  - 部分欠落 → 欠けた店が分母から消え、監視は緑
という自己参照が成立していた。

修正後の契約:
  - 期待 slug 集合が全部揃った夜だけ正規パスへ書く
  - 欠けた夜は `accuracy/snapshots/_partial/<date>.json` へ退避し、非ゼロ終了
  - payload には常に expected_slugs / missing_slugs / captured_at_utc を含む
  - score 側の分母は snapshot の expected_slugs（無い古いファイルは全店舗集合）

ネットワーク・Supabase には一切アクセスしない（_get_json / _storage_put を差し替える）。
スクリプト自体は実行せず、main() を import して呼ぶ。
"""

from __future__ import annotations

import json

import pytest

import scripts.score_forecasts as sf
import scripts.snapshot_forecasts as snap

SLUGS = ["shibuya", "umeda", "ay_ueno"]


def _points(n: int = 2) -> list[dict]:
    return [
        {"ts": f"2026-08-21T19:{15 * i:02d}:00+09:00", "total_pred": 10.0 + i,
         "men_pred": 6.0, "women_pred": 4.0}
        for i in range(n)
    ]


@pytest.fixture
def captured_puts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """_storage_put を捕まえ、(path, payload) の一覧にする。"""
    puts: list[tuple[str, dict]] = []

    def _put(bucket, path, body, url, key, **kw):  # noqa: ANN001
        puts.append((path, json.loads(body.decode("utf-8"))))

    monkeypatch.setattr(snap, "_storage_put", _put)
    monkeypatch.setattr(snap, "_load_env", lambda *a, **k: None)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.delenv("SNAPSHOT_ALLOWED_MISSING", raising=False)
    monkeypatch.setattr(snap, "_all_store_slugs", lambda: list(SLUGS))
    monkeypatch.setattr(snap, "_compute_v2", lambda *a, **k: {s: None for s in SLUGS})
    return puts


def _wire_backend(monkeypatch: pytest.MonkeyPatch, ok_slugs: dict[str, list]) -> None:
    """/api/forecast_today_multi の応答を固定する（ok_slugs に無い店は ok=False）。"""

    def _get_json(url: str, retries: int = 3):  # noqa: ANN001, ARG001
        return {
            "by_slug": {
                s: ({"ok": True, "data": pts} if pts else {"ok": False, "error": "no_model"})
                for s, pts in ok_slugs.items()
            }
        }

    monkeypatch.setattr(snap, "_get_json", _get_json)


class Test正規パスへの昇格ガード:
    def test_全店揃えば正規パスへ書き成功で終わる(self, monkeypatch, captured_puts) -> None:
        _wire_backend(monkeypatch, {s: _points() for s in SLUGS})

        assert snap.main() == 0

        assert len(captured_puts) == 1
        path, payload = captured_puts[0]
        assert path.startswith(f"{snap.SNAPSHOT_DIR}/") and "_partial" not in path
        assert payload["missing_slugs"] == []
        assert sorted(payload["expected_slugs"]) == sorted(SLUGS)
        assert payload["captured_at_utc"]
        assert sorted(payload["by_slug"]) == sorted(SLUGS)

    def test_1店欠けたら正規パスに書かれず非ゼロ終了(self, monkeypatch, captured_puts, capsys) -> None:
        ok = {s: _points() for s in SLUGS}
        ok["umeda"] = []  # backend が ok=False を返した店
        _wire_backend(monkeypatch, ok)

        assert snap.main() == 1

        paths = [p for p, _ in captured_puts]
        assert len(paths) == 1
        assert paths[0].startswith(f"{snap.PARTIAL_DIR}/"), paths
        _path, payload = captured_puts[0]
        assert payload["missing_slugs"] == ["umeda"]
        assert sorted(payload["expected_slugs"]) == sorted(SLUGS)
        assert "umeda" in capsys.readouterr().out

    def test_空なら正規パスに書かれない(self, monkeypatch, captured_puts, capsys) -> None:
        _wire_backend(monkeypatch, {s: [] for s in SLUGS})

        assert snap.main() == 1

        assert all("_partial" in p for p, _ in captured_puts)
        assert captured_puts[0][1]["by_slug"] == {}
        assert sorted(captured_puts[0][1]["missing_slugs"]) == sorted(SLUGS)
        assert "no forecasts captured at all" in capsys.readouterr().out

    def test_点列が空リストの店も欠落として扱う(self) -> None:
        assert snap._missing_slugs(SLUGS, {"shibuya": _points(), "umeda": [], "ay_ueno": _points()}) == ["umeda"]

    def test_ALLOWED_MISSINGで期待集合から外した店は昇格を妨げない(
        self, monkeypatch, captured_puts
    ) -> None:
        monkeypatch.setenv("SNAPSHOT_ALLOWED_MISSING", "umeda")
        ok = {s: _points() for s in SLUGS}
        ok["umeda"] = []
        _wire_backend(monkeypatch, ok)

        assert snap.main() == 0

        path, payload = captured_puts[0]
        assert "_partial" not in path
        assert payload["missing_slugs"] == []
        assert "umeda" not in payload["expected_slugs"]

    def test_全店を除外したら正規パスへ昇格せず非ゼロ終了する(
        self, monkeypatch, captured_puts, capsys
    ) -> None:
        """F1 追補: 逃がし弁(SNAPSHOT_ALLOWED_MISSING)に全店を並べると expected=[] になり、
        旧実装の `complete = not missing` は「欠けている店が無い」と誤判定して中身が
        空の payload を正規パスへ昇格させていた。expected が空なら complete にしない。
        """
        monkeypatch.setenv("SNAPSHOT_ALLOWED_MISSING", ",".join(SLUGS))
        _wire_backend(monkeypatch, {s: _points() for s in SLUGS})

        assert snap.main() == 1

        paths = [p for p, _ in captured_puts]
        assert len(paths) == 1
        assert paths[0].startswith(f"{snap.PARTIAL_DIR}/"), paths
        _path, payload = captured_puts[0]
        assert payload["expected_slugs"] == []
        assert payload["missing_slugs"] == []  # 空集合同士なので「欠けている店」は無い
        out = capsys.readouterr().out
        assert "expected slug set is empty" in out

    def test_除外数が全店の1_4超なら警告する(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("SNAPSHOT_ALLOWED_MISSING", "umeda,ay_ueno")  # 3店中2店=1/4超
        assert snap._expected_slugs(list(SLUGS)) == ["shibuya"]
        assert "excludes 2/3" in capsys.readouterr().out

    def test_未知のslugを除外指定したら警告する(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("SNAPSHOT_ALLOWED_MISSING", "not_a_real_slug")
        assert snap._expected_slugs(list(SLUGS)) == list(SLUGS)
        out = capsys.readouterr().out
        assert "unknown slug" in out
        assert "not_a_real_slug" in out


class Testscore側のcoverage分母:
    def test_expected_slugsから算出する_by_slug件数ではない(self) -> None:
        snapshot = {"expected_slugs": SLUGS, "by_slug": {"shibuya": _points()}}
        assert sf._expected_count(snapshot, snapshot["by_slug"]) == 3

    def test_重複したexpected_slugsは1店として数える(self) -> None:
        snapshot = {"expected_slugs": ["shibuya", "shibuya", "umeda"], "by_slug": {}}
        assert sf._expected_count(snapshot, {}) == 2

    def test_expected_slugsが無い古いsnapshotでも落ちない(self, capsys) -> None:
        from scripts._stores_common import all_slugs

        snapshot = {"by_slug": {"shibuya": _points()}}
        assert sf._expected_count(snapshot, snapshot["by_slug"]) == len(all_slugs())
        assert "pre-F1 file" in capsys.readouterr().out

    def test_店舗マスタが読めない異常時だけ旧挙動へ退避する(self, monkeypatch) -> None:
        def _boom():
            raise RuntimeError("stores.json unreadable")

        monkeypatch.setattr(sf, "all_slugs", _boom)
        snapshot = {"by_slug": {"shibuya": _points(), "umeda": _points()}}
        assert sf._expected_count(snapshot, snapshot["by_slug"]) == 2
