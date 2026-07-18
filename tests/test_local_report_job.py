"""scripts/local_report_job.py（日次レポート生成ジョブ）の単体テスト。

背景（Fable監査 CONFIRMED BUG #2）:
  2026-07-16 21:30、facts 取得が backend のメモリイベントに起因するタイムアウトで
  失敗し、42店中1店しか日次レポートが生成できなかった。従来の設計は「生成に失敗したら
  必ず空本文 + is_published=False で上書きする」だったため、既に公開されていた
  「前回の良品」まで空本文で消してしまっていた（7/17 にも oita 単店失敗が再発）。

このテストが固定する挙動:
  1) facts 取得のリトライ機構（scripts/experiments/local_llm_spike.py 側。#2 対策）:
     - 一時的な失敗は指数バックオフで再試行し、既存呼び出し元（retries 未指定）は
       1発勝負のまま変化しない。
     - 全試行を使い切った場合のみ sample(fallback) に落ちる（従来どおり）。
  2) carry-over（このファイルのコア修正）:
     - 生成失敗時、直前に公開済みの本文が Supabase に残っていればそれを維持し、
       error_message だけ今回の失敗理由に更新する（_apply_carry_over_or_fail）。
     - 新規店舗・前回も失敗していた場合は、従来どおり空本文 + is_published=False
       + error_message の2状態のまま（引き継ぐものが無いのは仕様どおり）。
     - 成功パスは完全に無変更（carry-over 用の Supabase 読み取りは一切発生しない）。
     - --mode dry-run は Supabase に一切触れない既存の契約を守るため、失敗時も
       carry-over フェッチをスキップする（プレビューは常に空失敗の形になる）。
     - evening_preview / late_update は facts_id が別なので、carry-over も互いの
       Supabase 行を混同しない（edition 分離）。
  3) バッチ開始前の /healthz プリチェック（_maybe_wait_for_degraded_backend）。

Supabase・backend への実アクセスはすべてモック化する（本番 Supabase には一切書き込まない）。
urllib モックは既存の規約（test_score_forecasts_pagination.py 等）を踏襲する。
local_report_job.py は `from urllib.request import Request, urlopen` と直接importして
いるため、モックは `monkeypatch.setattr(lrj, "urlopen", ...)` で当てる（`urllib.request.urlopen`
文字列パッチでは効かない点に注意）。一方 local_llm_spike.py は `import urllib.request` と
モジュールごとimportしているため、`monkeypatch.setattr("urllib.request.urlopen", ...)` で当てる。
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import pytest

import scripts.local_report_job as lrj


class _FakeResp:
    """urlopen() の with 文結果を模す最小フェイク（既存テスト規約と同じ形）。"""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _store_row(slug: str = "shibuya", brand: str = "oriental") -> dict[str, Any]:
    return {
        "slug": slug,
        "store_id": f"ol_{slug}" if brand == "oriental" else slug,
        "store": slug,
        "label": slug,
        "brand": brand,
    }


def _prior_good_row(mdx_content: str = "# prior good report\nbody", target_date: str = "2026-07-17") -> dict[str, Any]:
    return {"mdx_content": mdx_content, "is_published": True, "target_date": target_date}


# --------------------------------------------------------------------------- #
# local_llm_spike._get_json: リトライ + 指数バックオフ（#2 対策のコア）
# --------------------------------------------------------------------------- #
class TestGetJsonRetry:
    def test_default_retries_is_one_no_change_for_existing_callers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """retries を指定しない既存呼び出し元（check_ollama 等）は従来どおり1発勝負。"""
        calls: list[str] = []

        def _fake_urlopen(req, timeout=25):
            calls.append(req.full_url)
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        with pytest.raises(TimeoutError):
            lrj.spk._get_json("http://x/api/y")
        assert len(calls) == 1

    def test_retries_then_succeeds_within_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def _fake_urlopen(req, timeout=25):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise TimeoutError("backend memory event: timed out")
            return _FakeResp(json.dumps({"ok": True}).encode())

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        result = lrj.spk._get_json("http://x/api/y", retries=3)

        assert result == {"ok": True}
        assert len(calls) == 3
        assert len(sleeps) == 2  # between attempt 1->2 and 2->3; none after the final success

    def test_raises_last_exception_after_exhausting_all_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """facts-fetch retry exhaustion path: 全試行が失敗したら最後の例外を送出する。"""
        calls: list[str] = []

        def _fake_urlopen(req, timeout=25):
            calls.append(req.full_url)
            raise TimeoutError(f"timed out attempt {len(calls)}")

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        with pytest.raises(TimeoutError, match="attempt 3"):
            lrj.spk._get_json("http://x/api/y", retries=3)
        assert len(calls) == 3


# --------------------------------------------------------------------------- #
# local_llm_spike.fetch_store_facts: 実際のロバスト性（backend degradation 吸収）
# --------------------------------------------------------------------------- #
class TestFetchStoreFactsRobustness:
    def test_recovers_after_transient_failure_on_one_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"megribi": 0, "forecast": 0}

        def _fake_urlopen(req, timeout=25):
            url = req.full_url
            if "megribi_score" in url:
                calls["megribi"] += 1
                if calls["megribi"] < 2:
                    raise TimeoutError("backend memory event: timed out")
                return _FakeResp(json.dumps({
                    "data": [{"slug": "shibuya", "score": 0.7, "occupancy_rate": 0.5,
                              "female_ratio": 0.4, "total": 30}]
                }).encode())
            if "forecast_today" in url:
                calls["forecast"] += 1
                return _FakeResp(json.dumps({
                    "data": [{"ts": "2026-07-18T22:00:00+09:00", "total_pred": 40}]
                }).encode())
            raise AssertionError(f"unexpected url: {url}")

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        facts = lrj.spk.fetch_store_facts("shibuya")

        assert facts["source"] == "live"
        assert facts["megribi_score"] == 0.7
        assert "megribi_error" not in facts
        assert calls["megribi"] == 2  # 1回目失敗 -> 2回目成功（リトライ予算内で回復）

    def test_falls_back_to_sample_after_exhausting_retries_on_both_endpoints(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONFIRMED BUG #2 の再現: 両エンドポイントが持続的に劣化していると、
        リトライを使い切った上で sample(fallback) に落ちる（従来どおりの安全側の挙動）。"""

        def _fake_urlopen(req, timeout=25):
            raise TimeoutError("backend memory event: timed out")

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        facts = lrj.spk.fetch_store_facts("oita")

        assert facts["source"] == "sample(fallback)"
        assert "timed out" in facts["megribi_error"]
        assert "timed out" in facts["forecast_error"]
        # 2 エンドポイント x (FACTS_FETCH_RETRIES-1) 回ずつ待った実績があること
        assert len(sleeps) == 2 * (lrj.spk.FACTS_FETCH_RETRIES - 1)


class TestCheckBackendHealth:
    def test_returns_parsed_json_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_urlopen(req, timeout=10):
            assert "/healthz" in req.full_url
            return _FakeResp(json.dumps({"ok": True, "memory": {"rss_mb": 123.4}}).encode())

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        health = lrj.spk.check_backend_health()
        assert health["memory"]["rss_mb"] == 123.4

    def test_returns_empty_dict_when_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_urlopen(req, timeout=10):
            raise TimeoutError("no route to host")

        monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
        assert lrj.spk.check_backend_health() == {}


# --------------------------------------------------------------------------- #
# _fetch_existing_daily_report: carry-over の読み取り元
# --------------------------------------------------------------------------- #
class TestFetchExistingDailyReport:
    def test_queries_correct_facts_id_and_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """carry-over が正しい行（今回書こうとしている facts_id と同じ行）を読むことを確認する。"""
        monkeypatch.setattr(lrj, "_supabase_conf", lambda: ("https://proj.supabase.co", "service-key"))
        captured: dict[str, Any] = {}

        def _fake_urlopen(req, timeout=15):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
            return _FakeResp(json.dumps([_prior_good_row()]).encode())

        monkeypatch.setattr(lrj, "urlopen", _fake_urlopen)

        result = lrj._fetch_existing_daily_report("auto_shibuya_evening_preview")

        assert result["mdx_content"] == "# prior good report\nbody"
        assert result["is_published"] is True

        parsed = urllib.parse.urlparse(captured["url"])
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs["facts_id"] == ["eq.auto_shibuya_evening_preview"]
        assert qs["select"] == ["mdx_content,is_published,target_date"]
        assert qs["limit"] == ["1"]
        assert captured["headers"]["apikey"] == "service-key"

    def test_returns_empty_dict_when_supabase_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj, "_supabase_conf", lambda: None)

        def _must_not_call(req, timeout=15):
            raise AssertionError("must not call Supabase when unconfigured")

        monkeypatch.setattr(lrj, "urlopen", _must_not_call)
        assert lrj._fetch_existing_daily_report("auto_x_evening_preview") == {}

    def test_returns_empty_dict_on_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj, "_supabase_conf", lambda: ("https://proj.supabase.co", "key"))

        def _fake_urlopen(req, timeout=15):
            raise TimeoutError("supabase down")

        monkeypatch.setattr(lrj, "urlopen", _fake_urlopen)
        assert lrj._fetch_existing_daily_report("auto_x_evening_preview") == {}

    def test_returns_empty_dict_when_no_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj, "_supabase_conf", lambda: ("https://proj.supabase.co", "key"))

        def _fake_urlopen(req, timeout=15):
            return _FakeResp(json.dumps([]).encode())

        monkeypatch.setattr(lrj, "urlopen", _fake_urlopen)
        assert lrj._fetch_existing_daily_report("auto_x_evening_preview") == {}


# --------------------------------------------------------------------------- #
# _apply_carry_over_or_fail: 失敗時のコア分岐
# --------------------------------------------------------------------------- #
class TestApplyCarryOverOrFail:
    def _base(self) -> dict[str, Any]:
        return lrj._base_record("shibuya", _store_row(), "evening_preview", "2026-07-18")

    def test_carries_over_prior_published_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        base = self._base()
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: _prior_good_row())

        record = lrj._apply_carry_over_or_fail(base, "facts fetch failed: timed out", allow_fetch=True)

        assert record["mdx_content"] == "# prior good report\nbody"
        assert record["is_published"] is True
        # error_message は「今回」の理由。前回の内容ではない。
        assert record["error_message"] == "facts fetch failed: timed out"
        # メタデータは今回の base のまま（前回の行の target_date 等に引きずられない）。
        assert record["facts_id"] == base["facts_id"]
        assert record["target_date"] == base["target_date"]

    def test_brand_new_store_no_prior_row_writes_empty_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """brand-new store failure still writes empty+error: 引き継ぐものが無ければ2状態目のまま。"""
        base = self._base()
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: {})

        record = lrj._apply_carry_over_or_fail(base, "facts fetch failed: timed out", allow_fetch=True)

        assert record["mdx_content"] == ""
        assert record["is_published"] is False
        assert record["error_message"] == "facts fetch failed: timed out"

    def test_prior_row_never_published_does_not_carry_over(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """前回も失敗行だった（is_published=False）場合は、引き継ぐものが無いのと同じ扱い。"""
        base = self._base()
        monkeypatch.setattr(
            lrj, "_fetch_existing_daily_report",
            lambda facts_id: {"mdx_content": "", "is_published": False, "target_date": "2026-07-17"},
        )

        record = lrj._apply_carry_over_or_fail(base, "ollama generation failed: empty output", allow_fetch=True)

        assert record["mdx_content"] == ""
        assert record["is_published"] is False

    def test_prior_row_published_but_empty_body_is_defensive_no_carry_over(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_published=True なのに本文が空/空白という不整合行は、防御的に carry-over しない。"""
        base = self._base()
        monkeypatch.setattr(
            lrj, "_fetch_existing_daily_report",
            lambda facts_id: {"mdx_content": "   ", "is_published": True, "target_date": "2026-07-17"},
        )

        record = lrj._apply_carry_over_or_fail(base, "reason", allow_fetch=True)

        assert record["mdx_content"] == ""
        assert record["is_published"] is False

    def test_dry_run_never_fetches_existing_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """allow_fetch=False（--mode dry-run 由来）は Supabase に一切触れない既存契約を守る。"""
        base = self._base()

        def _must_not_call(facts_id):
            raise AssertionError("dry-run must not query Supabase for carry-over")

        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", _must_not_call)

        record = lrj._apply_carry_over_or_fail(base, "facts fetch failed: x", allow_fetch=False)

        assert record["mdx_content"] == ""
        assert record["is_published"] is False
        assert record["error_message"] == "facts fetch failed: x"


# --------------------------------------------------------------------------- #
# build_record: 統合（facts fetch / sample fallback / ollama失敗 の3経路すべて）
# --------------------------------------------------------------------------- #
class TestBuildRecordCarryOver:
    def test_success_path_unchanged_and_never_queries_carry_over(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            lrj.spk, "fetch_store_facts",
            lambda slug: {
                "source": "live", "megribi_score": 0.6, "occupancy_rate": 0.5,
                "forecast_peak_total": 30, "forecast_peak_time": "22:30",
            },
        )
        monkeypatch.setattr(lrj.spk, "run_ollama", lambda *a, **k: ("# 見出し\n本文です。", 1.5, ""))

        def _must_not_call(facts_id):
            raise AssertionError("success path must not query carry-over")

        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", _must_not_call)

        record = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )

        assert record["is_published"] is True
        assert record["error_message"] is None
        assert record["mdx_content"]
        assert "title:" in record["mdx_content"]
        assert "facts_id: auto_shibuya_evening_preview" in record["mdx_content"]

    def test_facts_fetch_exception_carries_over_prior_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(slug):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(lrj.spk, "fetch_store_facts", _raise)
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: _prior_good_row())

        record = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )

        assert record["is_published"] is True
        assert record["mdx_content"] == "# prior good report\nbody"
        assert "facts fetch failed" in record["error_message"]

    def test_sample_fallback_carries_over_prior_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            lrj.spk, "fetch_store_facts",
            lambda slug: {"source": "sample(fallback)", "megribi_error": "timed out", "forecast_error": "timed out"},
        )
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: _prior_good_row())

        record = lrj.build_record(
            slug="oita", store_row=_store_row("oita"), edition="late_update",
            target_date="2026-07-18", mode="publish",
        )

        assert record["is_published"] is True
        assert record["mdx_content"] == "# prior good report\nbody"
        assert "sample fallback" in record["error_message"]

    def test_ollama_failure_carries_over_prior_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj.spk, "fetch_store_facts", lambda slug: {"source": "live", "megribi_score": 0.6})
        monkeypatch.setattr(lrj.spk, "run_ollama", lambda *a, **k: ("", 0.2, "HTTP 500: internal error"))
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: _prior_good_row())

        record = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )

        assert record["is_published"] is True
        assert record["mdx_content"] == "# prior good report\nbody"
        assert "ollama generation failed" in record["error_message"]

    def test_brand_new_store_failure_writes_empty_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(slug):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(lrj.spk, "fetch_store_facts", _raise)
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: {})

        record = lrj.build_record(
            slug="brand_new", store_row=_store_row("brand_new"), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )

        assert record["is_published"] is False
        assert record["mdx_content"] == ""
        assert "facts fetch failed" in record["error_message"]

    def test_dry_run_failure_never_touches_supabase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(slug):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(lrj.spk, "fetch_store_facts", _raise)

        def _must_not_call(facts_id):
            raise AssertionError("dry-run must not query Supabase")

        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", _must_not_call)

        record = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="dry-run",
        )

        assert record["is_published"] is False
        assert record["mdx_content"] == ""

    def test_idempotent_rerun_same_day_carries_over_first_runs_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同日内の再実行で、1回目成功・2回目失敗というシナリオでも1回目の内容が生き残る
        （facts_id に日付が入っていないため、同一 store+edition の行は毎回 PATCH で
        上書きされる設計。carry-over が無いとこの再実行だけで良品が消えてしまう）。"""
        monkeypatch.setattr(lrj.spk, "fetch_store_facts", lambda slug: {"source": "live", "megribi_score": 0.5})
        monkeypatch.setattr(lrj.spk, "run_ollama", lambda *a, **k: ("# 今夜の渋谷\n空いています。", 1.0, ""))

        first_run = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )
        assert first_run["is_published"] is True

        # 2回目: ollama が失敗。carry-over 元は「Supabase に既にある行」= 1回目の出力とみなす。
        monkeypatch.setattr(lrj.spk, "run_ollama", lambda *a, **k: ("", 0.1, "HTTP 500"))
        monkeypatch.setattr(
            lrj, "_fetch_existing_daily_report",
            lambda facts_id: {
                "mdx_content": first_run["mdx_content"],
                "is_published": True,
                "target_date": first_run["target_date"],
            },
        )
        second_run = lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )

        assert second_run["is_published"] is True
        assert second_run["mdx_content"] == first_run["mdx_content"]
        assert second_run["error_message"] is not None

    def test_carry_over_only_reads_the_matching_edition_facts_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """evening_preview / late_update は facts_id が別。carry-over が互いの行を
        混同しない（各 edition は自分の facts_id だけを読む）ことを確認する。"""
        seen_facts_ids: list[str] = []

        def _fake_fetch(facts_id: str) -> dict[str, Any]:
            seen_facts_ids.append(facts_id)
            return {}

        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", _fake_fetch)

        def _raise(slug):
            raise RuntimeError("boom")

        monkeypatch.setattr(lrj.spk, "fetch_store_facts", _raise)

        lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="evening_preview",
            target_date="2026-07-18", mode="publish",
        )
        lrj.build_record(
            slug="shibuya", store_row=_store_row(), edition="late_update",
            target_date="2026-07-18", mode="publish",
        )

        assert seen_facts_ids == ["auto_shibuya_evening_preview", "auto_shibuya_late_update"]


# --------------------------------------------------------------------------- #
# _failure_record: ロック取得タイムアウト等、build_record の外の失敗経路
# --------------------------------------------------------------------------- #
class TestFailureRecordCarryOver:
    def test_carries_over_when_prior_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: _prior_good_row())

        record = lrj._failure_record(
            "shibuya", _store_row(), "evening_preview", "2026-07-18",
            "lock/gen error: timeout", mode="publish",
        )

        assert record["is_published"] is True
        assert record["mdx_content"] == "# prior good report\nbody"
        assert record["error_message"] == "lock/gen error: timeout"

    def test_brand_new_store_writes_empty_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", lambda facts_id: {})

        record = lrj._failure_record(
            "brand_new", _store_row("brand_new"), "evening_preview", "2026-07-18",
            "lock/gen error: timeout", mode="publish",
        )

        assert record["is_published"] is False
        assert record["mdx_content"] == ""

    def test_dry_run_mode_skips_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _must_not_call(facts_id):
            raise AssertionError("dry-run must not query Supabase")

        monkeypatch.setattr(lrj, "_fetch_existing_daily_report", _must_not_call)

        record = lrj._failure_record(
            "shibuya", _store_row(), "evening_preview", "2026-07-18",
            "lock/gen error: timeout", mode="dry-run",
        )

        assert record["is_published"] is False
        assert record["mdx_content"] == ""


# --------------------------------------------------------------------------- #
# _maybe_wait_for_degraded_backend: バッチ開始前の /healthz プリチェック
# --------------------------------------------------------------------------- #
class TestMaybeWaitForDegradedBackend:
    def test_waits_when_memory_degraded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_REPORT_HEALTH_PRECHECK", raising=False)
        monkeypatch.delenv("LOCAL_REPORT_MEMORY_WARN_MB", raising=False)
        monkeypatch.delenv("LOCAL_REPORT_HEALTH_WAIT_SEC", raising=False)
        monkeypatch.setattr(lrj.spk, "check_backend_health", lambda: {"memory": {"rss_mb": 500.0}})
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        lrj._maybe_wait_for_degraded_backend()

        assert sleeps == [lrj.DEFAULT_HEALTH_PRECHECK_WAIT_SEC]

    def test_skips_wait_when_memory_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_REPORT_HEALTH_PRECHECK", raising=False)
        monkeypatch.delenv("LOCAL_REPORT_MEMORY_WARN_MB", raising=False)
        monkeypatch.setattr(lrj.spk, "check_backend_health", lambda: {"memory": {"rss_mb": 100.0}})
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        lrj._maybe_wait_for_degraded_backend()

        assert sleeps == []

    def test_handles_unreachable_backend_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_REPORT_HEALTH_PRECHECK", raising=False)
        monkeypatch.setattr(lrj.spk, "check_backend_health", lambda: {})
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        lrj._maybe_wait_for_degraded_backend()  # must not raise

        assert sleeps == []

    def test_disabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_REPORT_HEALTH_PRECHECK", "0")

        def _must_not_call():
            raise AssertionError("must not call check_backend_health when disabled")

        monkeypatch.setattr(lrj.spk, "check_backend_health", _must_not_call)

        lrj._maybe_wait_for_degraded_backend()  # must not raise

    def test_respects_env_overrides_for_threshold_and_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_REPORT_HEALTH_PRECHECK", raising=False)
        monkeypatch.setenv("LOCAL_REPORT_MEMORY_WARN_MB", "50")
        monkeypatch.setenv("LOCAL_REPORT_HEALTH_WAIT_SEC", "5")
        monkeypatch.setattr(lrj.spk, "check_backend_health", lambda: {"memory": {"rss_mb": 100.0}})
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        lrj._maybe_wait_for_degraded_backend()

        assert sleeps == [5.0]
