"""V9 番犬: 週報 carry-over で本文の年齢がリセットされないこと。

背景（外部レビュー 2026-08-21 V9）:
`generate_weekly_insights.py` は毎回の実行時刻を `payload["generated_at"]` に入れる。
carry-over 分岐（本文生成が失敗/ゲート却下されたとき）は本文だけを前回からコピーし、
`generated_at` は今回の実行時刻のまま保存していた。次回の鮮度判定
(`_fetch_existing_weekly_commentary`) は `insight_json.generated_at` を最優先で読むため、
**本文の実年齢が毎週0に戻り**、`WEEKLY_COMMENTARY_MAX_AGE_DAYS`(=21日) の上限に
永久に到達しないバグがあった。

修正後の契約:
  - `insight_json.commentary_generated_at` は本文が**新規生成に成功したときだけ**更新する。
  - carry-over のときは前回の `commentary_generated_at` をそのまま引き継ぐ。
  - 鮮度判定の参照順は `commentary_generated_at -> generated_at -> updated_at -> created_at`
    （後方互換: 修正前の行には `commentary_generated_at` が無いのでフォールバックする）。
  - `insight_json.commentary_carry_over_count` は連続 carry-over 回数を可視化する
    （閾値による自動警告はまだ入れない。「見えるようにする」段階）。

このテストは Supabase REST の応答形（`{"insight_json": ..., "updated_at": ..., "created_at":
...}` の配列）を模した urlopen スタブで `_fetch_existing_weekly_commentary` の実物を通し、
複数週にまたがる carry-over 連鎖で年齢が正しく積み上がることを固定する。
ネットワークには一切出ない。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import scripts.generate_weekly_insights as gwi

# scripts/commentary_quality_gate.py の公開前ゲート（各セクション40字以上・箇条書き
# 1行以上・NG語なし・数値主張との照合）を通す固定文。数値(%)主張を含めないことで
# daily_summary との数値照合チェックを素通りさせている（このテストの主目的は
# carry-over の年齢積み上げであって、コメンタリー品質ゲート自体の検証ではないため）。
_VALID_COMMENTARY = {
    "last_week_summary": (
        "先週は全体的に落ち着いた入りが多く、大きな混雑のピークは見られませんでした。\n"
        "- 平日は概ね静かな稼働で推移しました"
    ),
    "next_week_forecast": (
        "来週も同様の落ち着いた入りが予想され、大きな変動は見込まれません。\n"
        "- 週末にかけてやや賑わう可能性があります"
    ),
}


# ---------------------------------------------------------------------------
# _fetch_existing_weekly_commentary: 参照優先順位の単体テスト
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def _stub_urlopen(rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """gwi.urlopen を差し替え、Supabase REST の応答（行の配列）を返すようにする。"""

    def _fake_urlopen(req, timeout=15):  # noqa: ANN001, ARG001
        return _FakeResponse(json.dumps(rows).encode("utf-8"))

    monkeypatch.setattr(gwi, "urlopen", _fake_urlopen)
    monkeypatch.setattr(gwi, "_supabase_conf", lambda: ("https://example.supabase.co", "k"))


class Test参照優先順位:
    def test_commentary_generated_atを最優先で読む(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """generated_at（今回の実行時刻）より commentary_generated_at（本文の実生成時刻）
        を優先する。これが逆だと carry-over のたびに年齢が0に戻るバグが再発する。"""
        _stub_urlopen(
            [{
                "insight_json": {
                    "ai_commentary": "先週の話",
                    "commentary_generated_at": "2026-08-01T00:00:00+00:00",
                    "generated_at": "2026-08-21T00:00:00+00:00",  # 今回の実行時刻（新しい）
                },
                "updated_at": "2026-08-21T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
            }],
            monkeypatch,
        )
        out = gwi._fetch_existing_weekly_commentary("shibuya")
        assert out["_existing_generated_at"] == "2026-08-01T00:00:00+00:00"

    def test_旧行はgenerated_atにフォールバックする(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """commentary_generated_at が無い旧行（この修正より前に書かれた行）は
        従来どおり generated_at にフォールバックする（後方互換）。"""
        _stub_urlopen(
            [{
                "insight_json": {
                    "ai_commentary": "旧フォーマットの話",
                    "generated_at": "2026-08-14T00:00:00+00:00",
                },
                "updated_at": "2026-08-14T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
            }],
            monkeypatch,
        )
        out = gwi._fetch_existing_weekly_commentary("shibuya")
        assert out["_existing_generated_at"] == "2026-08-14T00:00:00+00:00"

    def test_carry_over_countを引き継ぐ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_urlopen(
            [{
                "insight_json": {
                    "ai_commentary": "話",
                    "commentary_generated_at": "2026-08-01T00:00:00+00:00",
                    "commentary_carry_over_count": 2,
                },
                "updated_at": "2026-08-14T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
            }],
            monkeypatch,
        )
        out = gwi._fetch_existing_weekly_commentary("shibuya")
        assert out["_existing_carry_over_count"] == 2

    def test_carry_over_countが無い旧行は取得しない(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_urlopen(
            [{
                "insight_json": {"ai_commentary": "話", "generated_at": "2026-08-14T00:00:00+00:00"},
                "updated_at": "2026-08-14T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
            }],
            monkeypatch,
        )
        out = gwi._fetch_existing_weekly_commentary("shibuya")
        assert "_existing_carry_over_count" not in out


# ---------------------------------------------------------------------------
# 複数週にまたがる carry-over 連鎖: 年齢が正しく積み上がることを固定する
# ---------------------------------------------------------------------------


class TestマルチウィークCarryOver連鎖:
    """_process_store を3週連続で実行するシミュレーション:

      week1: 本文の新規生成に成功 -> commentary_generated_at = week1実行時刻, count=0
      week2: 新規生成が失敗 -> carry-over。commentary_generated_at は week1 のまま、count=1
      week3: 新規生成が失敗 -> carry-over。commentary_generated_at は依然 week1 のまま、count=2

    week3 時点で commentary_generated_at から測った年齢が「約14日」(week1→week3) に
    なっていることを確認する。旧実装のバグでは、carry-over のたびに generated_at
    (=そのジョブの実行時刻) が鮮度判定の基準にされてしまい、年齢は常に約0日だった。
    """

    def _run_week(
        self,
        *,
        store: str,
        base_dir,
        now: datetime,
        commentary: dict[str, str] | None,
        fake_table: dict[str, dict],
        monkeypatch: pytest.MonkeyPatch,
    ) -> dict:
        # _load_rows: 「今夜」に近いデータが1本あれば鮮度チェック(_weekly_skip_reason)は通る。
        row_ts = (now - timedelta(hours=1)).isoformat()
        monkeypatch.setattr(
            gwi, "_load_rows", lambda *a, **k: [{"ts": row_ts, "men": 3, "women": 3, "total": 6}]
        )
        monkeypatch.setattr(gwi, "_generate_ai_commentary", lambda **k: commentary)

        # Supabase 相当のフェイクテーブル(store -> insight_json)。
        def _fake_fetch(store_: str) -> dict:
            ij = fake_table.get(store_)
            if not ij:
                return {}
            out: dict[str, Any] = {}
            for k in ("last_week_summary", "next_week_forecast", "ai_commentary"):
                v = ij.get(k)
                if isinstance(v, str) and v.strip():
                    out[k] = v
            existing = ij.get("commentary_generated_at") or ij.get("generated_at")
            if existing:
                out["_existing_generated_at"] = existing
            cnt = ij.get("commentary_carry_over_count")
            if isinstance(cnt, int) and not isinstance(cnt, bool):
                out["_existing_carry_over_count"] = cnt
            return out

        def _fake_upsert(*, store: str, date_label: str, generated_at: str, payload: dict, source: str = "") -> None:  # noqa: ANN001
            fake_table[store] = payload

        monkeypatch.setattr(gwi, "_fetch_existing_weekly_commentary", _fake_fetch)
        monkeypatch.setattr(gwi, "_upsert_weekly_report_to_supabase", _fake_upsert)

        ctx = gwi.WeeklyRunContext(
            base_url="https://example.invalid",
            base_dir=base_dir,
            limit=5000,
            threshold=gwi.DEFAULT_OCCUPANCY_THRESHOLD,
            min_duration_minutes=gwi.DEFAULT_MIN_DURATION_MINUTES,
            ideal=gwi.DEFAULT_IDEAL,
            gender_weight=gwi.DEFAULT_GENDER_WEIGHT,
            timeout_seconds=5,
            retries=1,
            sync_to_supabase=True,
            stale_days=gwi.DEFAULT_WEEKLY_STALE_DAYS,
            min_night_samples=1,
            active_map={},
            now=now,
            date_label=now.strftime("%Y-%m-%d"),
            generated_at=gwi._iso(now),
        )
        gwi._process_store(store, ctx)
        return fake_table[store]

    def test_年齢が積み上がる(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = "shibuya"
        fake_table: dict[str, dict] = {}
        week1_now = datetime(2026, 8, 5, 6, 30, tzinfo=timezone.utc)

        week1 = self._run_week(
            store=store, base_dir=tmp_path, now=week1_now,
            commentary=_VALID_COMMENTARY,
            fake_table=fake_table, monkeypatch=monkeypatch,
        )
        assert week1["commentary_generated_at"] == gwi._iso(week1_now)
        assert week1["commentary_carry_over_count"] == 0

        week2_now = week1_now + timedelta(days=7)
        week2 = self._run_week(
            store=store, base_dir=tmp_path, now=week2_now,
            commentary=None,  # 新規生成が失敗 -> carry-over
            fake_table=fake_table, monkeypatch=monkeypatch,
        )
        # 修正前のバグ: ここで commentary_generated_at が week2_now に上書きされていた。
        assert week2["commentary_generated_at"] == gwi._iso(week1_now)
        assert week2["commentary_carry_over_count"] == 1
        assert week2["generated_at"] == gwi._iso(week2_now)  # ジョブ実行時刻の方は毎回更新される

        week3_now = week2_now + timedelta(days=7)
        week3 = self._run_week(
            store=store, base_dir=tmp_path, now=week3_now,
            commentary=None,  # 3週連続で失敗 -> さらに carry-over
            fake_table=fake_table, monkeypatch=monkeypatch,
        )
        assert week3["commentary_generated_at"] == gwi._iso(week1_now)
        assert week3["commentary_carry_over_count"] == 2

        # 本題: week1 からの実年齢が正しく積み上がっている(約14日)こと。
        age_days = gwi._commentary_age_days(week3["commentary_generated_at"], now=week3_now)
        assert age_days is not None
        assert 13.9 <= age_days <= 14.1

    def test_21日を超えたら本文なしで公開しcommentary_generated_atは進めない(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = "umeda"
        fake_table: dict[str, dict] = {}
        week1_now = datetime(2026, 6, 1, 6, 30, tzinfo=timezone.utc)
        self._run_week(
            store=store, base_dir=tmp_path, now=week1_now,
            commentary=_VALID_COMMENTARY,
            fake_table=fake_table, monkeypatch=monkeypatch,
        )

        # WEEKLY_COMMENTARY_MAX_AGE_DAYS(=21日)を超えて新規生成が失敗し続けた場合。
        stale_now = week1_now + timedelta(days=30)
        stale = self._run_week(
            store=store, base_dir=tmp_path, now=stale_now,
            commentary=None,
            fake_table=fake_table, monkeypatch=monkeypatch,
        )
        # carry-over を止めて本文なしで公開する(既存の挙動)。commentary_generated_at /
        # carry_over_count はどちらも「引き継ぐべき本文が無い」ので更新されない。
        assert "last_week_summary" not in stale
        assert "commentary_generated_at" not in stale
        assert "commentary_carry_over_count" not in stale
