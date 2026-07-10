"""scripts/score_forecasts.py._fetch_actuals のページネーション回帰テスト。

以前は limit=5000 の単発フェッチで、1 夜の行数がそれを超えるとサイレントに
切り捨てられていた（答え合わせが静かに壊れるバグの温床）。
scripts/build_templates.py._fetch_store_rows と同じ ts=gt.<cursor> キーセット方式
(1000行/ページ)に直したので、疑似 2.5 ページ分のデータセットで
「順序が保たれる」「カーソルが進む」「ちゃんと終了する」ことを確認する。

urllib はモック（既存の test_forecast_accuracy_relative.py と同じ規約:
monkeypatch.setattr("urllib.request.urlopen", ...) + req.full_url を見る）。
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import scripts.score_forecasts as sf


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_rows(n: int, start: datetime) -> list[dict]:
    return [
        {"ts": (start + timedelta(seconds=i)).isoformat(), "total": float(i), "men": None, "women": None}
        for i in range(n)
    ]


def _parse_ts_filters(full_url: str) -> dict[str, str]:
    """クエリ文字列の ts=gte.X / ts=gt.X / ts=lte.Y を {op: value} に分解する。"""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
    out: dict[str, str] = {}
    for raw in qs.get("ts", []):
        for op in ("gte.", "gt.", "lte."):
            if raw.startswith(op):
                out[op.rstrip(".")] = raw[len(op):]
                break
    return out


def test_paginates_across_fake_two_and_half_pages(monkeypatch) -> None:
    start = datetime(2026, 7, 10, 19, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    all_rows = _make_rows(2500, start)  # 1000 + 1000 + 500 = 2.5 ページ

    calls: list[str] = []

    def _fake_urlopen(req, timeout=30):
        full_url = req.full_url
        calls.append(full_url)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
        limit = int(qs.get("limit", ["1000"])[0])
        filters = _parse_ts_filters(full_url)
        lo = filters.get("gte") or filters.get("gt")
        assert lo is not None, "each page must carry a lower ts bound"
        assert "lte" in filters, "upper bound (end_iso) must be preserved on every page"
        if "gte" in filters:
            page = [r for r in all_rows if r["ts"] >= lo]
        else:
            page = [r for r in all_rows if r["ts"] > lo]
        page = page[:limit]
        return _FakeResp(json.dumps(page).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    rows = sf._fetch_actuals("http://x", "k", "ol_shibuya", start.isoformat(), end.isoformat())

    # 完全性: 全 2500 行を取り切っている（旧 limit=5000 単発なら 2500 で足りていたはずが、
    # ここでは「1000行/ページを跨いでも欠けない」ことを保証するのが目的）。
    assert len(rows) == 2500

    # 順序保持: ts 昇順のまま。
    ts_list = [r["ts"] for r in rows]
    assert ts_list == sorted(ts_list)
    assert ts_list == [r["ts"] for r in all_rows]

    # 終了: 3ページ目(500行 < limit)で打ち切られ、無限ループしない。
    assert len(calls) == 3

    # カーソルが進む: 2ページ目以降は前ページ最終行の ts を下限にした gt フィルタになる。
    f0 = _parse_ts_filters(calls[0])
    f1 = _parse_ts_filters(calls[1])
    f2 = _parse_ts_filters(calls[2])
    assert "gte" in f0 and f0["gte"] == start.isoformat()
    assert f1.get("gt") == all_rows[999]["ts"]
    assert f2.get("gt") == all_rows[1999]["ts"]
    # 上限(end_iso)は全ページで不変。
    assert f0["lte"] == f1["lte"] == f2["lte"] == end.isoformat()


def test_stops_immediately_on_short_first_page(monkeypatch) -> None:
    """1ページ目が limit 未満なら、2回目のリクエストを投げずに即終了する。"""
    start = datetime(2026, 7, 10, 19, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    rows_data = _make_rows(3, start)
    calls: list[str] = []

    def _fake_urlopen(req, timeout=30):
        calls.append(req.full_url)
        return _FakeResp(json.dumps(rows_data).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    rows = sf._fetch_actuals("http://x", "k", "ol_kashiwa", start.isoformat(), end.isoformat())
    assert len(rows) == 3
    assert len(calls) == 1


def test_absurd_row_count_logs_loud_warning(monkeypatch, capsys) -> None:
    """1店・1夜で FETCH_ABSURD_ROWS を超えたら、暴走クエリ疑いの警告を出す。"""
    start = datetime(2026, 7, 10, 19, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    n = sf.FETCH_ABSURD_ROWS + 500
    all_rows = _make_rows(n, start)

    def _fake_urlopen(req, timeout=30):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        limit = int(qs.get("limit", ["1000"])[0])
        filters = _parse_ts_filters(req.full_url)
        lo = filters.get("gte") or filters.get("gt")
        if "gte" in filters:
            page = [r for r in all_rows if r["ts"] >= lo]
        else:
            page = [r for r in all_rows if r["ts"] > lo]
        return _FakeResp(json.dumps(page[:limit]).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    rows = sf._fetch_actuals("http://x", "k", "ol_runaway", start.isoformat(), end.isoformat())
    assert len(rows) == n
    out = capsys.readouterr().out
    assert "WARN" in out and "ol_runaway" in out
