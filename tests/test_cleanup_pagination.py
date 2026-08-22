"""scripts/cleanup_old_logs.py の find_downsample_candidates() ページングのテスト
（2026-08-22 総合レビュー対応。検証記録は memory/general-review-2026-08-22.md）。

背景: 旧実装は `limit=50000` の一発 GET だったが、PostgREST はサーバー側上限
（db-max-rows、既定1000）で応答行数を頭打ちにするため、実際には cutoff より
古い最古1000行しか見えていなかった（scripts/backup_logs.py が2026-07-06に踏んだ
同型事故——107万行中1000行しか取れていなかった——の教訓が未反映のまま）。
本テストは keyset ページング（id.asc + id=gt.<cursor>）が

  1. 複数ページを辿ること（1ページ超のデータを全部見られること）
  2. ページ境界をまたいでも同一スロットの重複を正しく検出できること
  3. LOGS_DOWNSAMPLE_MAX_SCAN_ROWS の上限で確実に止まること（無限ループしない）
  4. dry-run（--execute なし）では削除リクエストを一切発行しないこと

を回帰確認する。Supabase への実ネットワークアクセスは一切行わない
（`_rest_get` / `_rest_request` をモンキーパッチして完全に差し替える）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import scripts.cleanup_old_logs as cleanup


def _row(row_id: int, store_id: str, ts: str) -> dict:
    return {"id": str(row_id), "store_id": store_id, "ts": ts}


class _FakePages:
    """`_rest_get("logs", params)` を差し替えるフェイク。

    `id=gt.<cursor>` の有無でどのページを返すかを判定し、実際の keyset
    ページングと同じ「cursor から先の行だけを返す」挙動を模倣する。
    """

    def __init__(self, rows: list[dict], page_size: int):
        # 呼び出し前に id 昇順で確定させておく（本物の PostgREST の order=id.asc と同じ)
        self.rows = sorted(rows, key=lambda r: int(r["id"]))
        self.page_size = page_size
        self.calls: list[dict] = []

    def __call__(self, path: str, params: dict) -> list[dict]:
        assert path == "logs"
        self.calls.append(dict(params))
        cursor_param = params.get("id")
        if cursor_param is None:
            start_idx = 0
        else:
            assert cursor_param.startswith("gt.")
            cursor = int(cursor_param[len("gt."):])
            start_idx = next(
                (i for i, r in enumerate(self.rows) if int(r["id"]) > cursor),
                len(self.rows),
            )
        limit = int(params["limit"])
        return self.rows[start_idx:start_idx + limit]


def test_paginates_across_multiple_pages(monkeypatch):
    """1ページ(page_size)を大きく超えるデータでも、全ページを辿って読み切る。"""
    # 250行 x page_size=100 -> 3ページに分かれる。各行を30分刻みでちょうど1つずつ
    # 別スロットに割り当て、ダウンサンプリング候補が出ない設計にすることで、
    # まず「何行読めたか」だけを見る。
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        _row(i, "ol_gangnam", (base + timedelta(minutes=30 * i)).isoformat())
        for i in range(1, 251)
    ]
    fake = _FakePages(rows, page_size=100)
    monkeypatch.setattr(cleanup, "_rest_get", fake)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_SCAN_PAGE", 100)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_MAX_SCAN_ROWS", 10_000)

    result = cleanup.find_downsample_candidates("2025-01-01T00:00:00+00:00")

    # 3ページ (100+100+50) + 終了判定用の空ページ1回 = 4回。旧実装(1回のGETで頭打ち)
    # なら100行しか読めておらず、この回数には到達しない。
    assert len(fake.calls) == 4
    # 各行が別スロットなので重複候補は0件（ページング自体の正しさの確認）
    assert result == []


def test_detects_duplicate_slot_split_across_page_boundary(monkeypatch):
    """同じ30分スロットの2行がページ境界をまたいでいても重複として検出できる。"""
    # page_size=2: id=1,2 が1ページ目、id=3 が2ページ目。id=1 と id=3 は
    # 同じ store_id + 同じ30分スロット(00:05 と 00:10 は同一スロット)。
    rows = [
        _row(1, "ol_gangnam", "2024-01-01T00:05:00+00:00"),
        _row(2, "ol_shibuya", "2024-01-01T01:00:00+00:00"),
        _row(3, "ol_gangnam", "2024-01-01T00:10:00+00:00"),
    ]
    fake = _FakePages(rows, page_size=2)
    monkeypatch.setattr(cleanup, "_rest_get", fake)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_SCAN_PAGE", 2)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_MAX_SCAN_ROWS", 10_000)

    result = cleanup.find_downsample_candidates("2025-01-01T00:00:00+00:00")

    # 2ページ(id=1,2 / id=3) + 終了判定用の空ページ1回 = 3回
    assert len(fake.calls) == 3
    # ts が早い id=1 を残し、id=3 が削除候補になる
    assert [r["id"] for r in result] == ["3"]


def test_stops_at_scan_cap_without_infinite_loop(monkeypatch):
    """走査上限(DOWNSAMPLE_MAX_SCAN_ROWS)に達したら、データがまだ残っていても止まる。"""
    # 十分多い行数（上限より多い）を用意し、キャップで打ち切られることを確認する。
    rows = [
        _row(i, "ol_gangnam", f"2024-01-01T00:{i % 60:02d}:00+00:00")
        for i in range(1, 1001)
    ]
    fake = _FakePages(rows, page_size=100)
    monkeypatch.setattr(cleanup, "_rest_get", fake)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_SCAN_PAGE", 100)
    monkeypatch.setattr(cleanup, "DOWNSAMPLE_MAX_SCAN_ROWS", 250)  # 1000行より小さい上限

    cleanup.find_downsample_candidates("2025-01-01T00:00:00+00:00")

    # 250行の上限に達した時点(3ページ目=300行読んだ時点でチェックしすぐ止まる)で
    # ループが終わっていること = 全10ページを回っていないこと
    assert len(fake.calls) < 10
    # 呼ばれた分の合計行数が「打ち切り後も無限に増え続けていない」こと
    total_read = sum(min(100, len(rows) - i * 100) for i in range(len(fake.calls)))
    assert total_read < len(rows)


def test_dry_run_delete_by_ids_issues_no_network_call(monkeypatch):
    """dry-run (dry_run=True) では delete_by_ids が実際の削除リクエストを発行しない。"""
    calls: list[str] = []

    def _boom(*args, **kwargs):
        calls.append("called")
        raise AssertionError("dry-run must not perform network requests")

    monkeypatch.setattr(cleanup, "_rest_request", _boom)

    deleted = cleanup.delete_by_ids(["a", "b", "c"], dry_run=True)

    assert deleted == 3
    assert calls == []  # ネットワーク相当の関数は一度も呼ばれていない


def test_dry_run_emergency_delete_does_not_call_delete_by_ids(monkeypatch):
    """dry-run では emergency_delete_oldest() も delete_by_ids へ到達しない
    （safe_excess の算出だけ行い、実削除には進まない）。"""
    calls: list[str] = []
    monkeypatch.setattr(cleanup, "delete_by_ids", lambda ids, dry_run: calls.append(ids))
    monkeypatch.setattr(cleanup, "_rest_get", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("dry-run must not fetch delete candidates either")
    ))

    deleted = cleanup.emergency_delete_oldest(
        current_count=4_000_000,
        max_rows=3_000_000,
        dry_run=True,
        protect_cutoff_iso="2025-01-01T00:00:00+00:00",
        protected_count=100_000,
    )

    assert deleted > 0  # dry-run でも「何件消すつもりか」は返す
    assert calls == []  # しかし実削除には一切進まない
