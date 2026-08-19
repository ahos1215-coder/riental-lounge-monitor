"""ローカル Ollama 呼び出しの共通化（B-05）の番犬。

守りたいこと:
  1) 週次レポートのコメンタリー生成が Ollama へ送るリクエストボディが、
     共通化の前後で1バイトも意味が変わらないこと。特に `format`（JSON スキーマ強制）は
     トップレベルのキーであり、`options` に混ぜると Ollama に無視されて
     「小型モデルがキーを誤字る」事故が静かに復活する。
  2) 日次・週次・実験スクリプトが同じ MODEL 定数を見ていること
     （2026-07-08 の 12b→e4b 変更で2系統を別々に直した過去がある）。

実 Ollama / 実 GPU ロックには一切触らない（urlopen と gpu_lock はモック）。
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

import scripts.generate_weekly_insights as gwi


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@pytest.fixture()
def fake_gpu_lock(monkeypatch: pytest.MonkeyPatch):
    """本物の共有GPUロックを絶対に掴まないよう、偽 gpu_lock を差し込む。"""
    import contextlib

    module = types.ModuleType("gpu_lock")
    module.acquire = lambda **_kwargs: contextlib.nullcontext()  # type: ignore[attr-defined]
    module.gpu_free_mb = lambda: 9999  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpu_lock", module)
    return module


def _capture_weekly_body(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """_ollama_commentary_call が組み立てたリクエストボディを1回分だけ捕まえる。"""
    captured: dict[str, Any] = {}

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({"message": {"content": '{"a": 1}'}}).encode())

    # 共通化の前後どちらでも同じフェイクが効くよう、両方の束縛を差し替える
    # （現行は generate_weekly_insights の from-import 束縛、共通化後は
    #  scripts/_ollama_common.py 側の urllib.request.urlopen を通る）。
    monkeypatch.setattr(gwi, "urlopen", _fake_urlopen, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    text = gwi._ollama_commentary_call("SYS-INSTRUCTION", "USER-PROMPT")
    assert text == '{"a": 1}'
    return captured


EXPECTED_WEEKLY_BODY: dict[str, Any] = {
    "model": "gemma4:e4b",
    "messages": [
        {"role": "system", "content": "SYS-INSTRUCTION"},
        {"role": "user", "content": "USER-PROMPT"},
    ],
    "stream": False,
    "keep_alive": "10m",
    "think": False,
    "format": {
        "type": "object",
        "properties": {
            "last_week_summary": {"type": "string"},
            "next_week_forecast": {"type": "string"},
        },
        "required": ["last_week_summary", "next_week_forecast"],
    },
    "options": {"num_ctx": 8192, "num_gpu": 999, "temperature": 0.7},
}


def test_週次コメンタリーのリクエストボディが従来と同一(
    monkeypatch: pytest.MonkeyPatch, fake_gpu_lock: object
) -> None:
    captured = _capture_weekly_body(monkeypatch)
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["timeout"] == 360
    assert captured["body"] == EXPECTED_WEEKLY_BODY


def test_週次コメンタリーのformatはトップレベルでoptionsに混ざらない(
    monkeypatch: pytest.MonkeyPatch, fake_gpu_lock: object
) -> None:
    body = _capture_weekly_body(monkeypatch)["body"]
    assert set(body["format"]["required"]) == {"last_week_summary", "next_week_forecast"}
    assert "format" not in body["options"]


def test_週次コメンタリーは空応答でNoneを返す(
    monkeypatch: pytest.MonkeyPatch, fake_gpu_lock: object
) -> None:
    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        return _FakeResp(json.dumps({"message": {"content": "   "}}).encode())

    monkeypatch.setattr(gwi, "urlopen", _fake_urlopen, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    assert gwi._ollama_commentary_call("s", "u") is None


def test_週次コメンタリーは失敗時に1回だけ再試行してNoneを返す(
    monkeypatch: pytest.MonkeyPatch, fake_gpu_lock: object
) -> None:
    calls: list[str] = []

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        calls.append(req.full_url)
        raise TimeoutError("boom")

    monkeypatch.setattr(gwi, "urlopen", _fake_urlopen, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    assert gwi._ollama_commentary_call("s", "u") is None
    assert len(calls) == 2  # attempts = 2（既存仕様）


def test_日次のリクエストボディにはformatキーが付かない(monkeypatch: pytest.MonkeyPatch) -> None:
    """日次レポートは構造化出力を使わない（Markdown 本文）。従来どおり format 無し。"""
    import scripts._ollama_common as oc

    captured: dict[str, Any] = {}

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({"message": {"content": "# 見出し"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    text, _elapsed, err = oc.run_ollama(
        oc.MODEL, "SYS", "USER", options={"num_gpu": 999}, think=False, keep_alive="10m"
    )

    assert (text, err) == ("# 見出し", "")
    assert "format" not in captured["body"]
    assert captured["body"]["options"] == {"num_ctx": 8192, "temperature": 0.7, "num_gpu": 999}
    assert captured["body"]["keep_alive"] == "10m"
    assert captured["body"]["think"] is False


def test_モデル名は日次週次実験で同じ定数を見る() -> None:
    import scripts._ollama_common as oc
    import scripts.local_report_job as lrj

    # scripts/ 配下はベアインポート規約（`import _ollama_common`）なので、
    # `scripts._ollama_common` とは別のモジュールオブジェクトになる点に注意（値で比較する）。
    assert lrj.MODEL == oc.MODEL
    assert gwi.OLLAMA_MODEL == oc.MODEL
    assert lrj.spk.MODEL == oc.MODEL
    assert oc.MODEL == "gemma4:e4b"


# ---- 2026-08-19 夜の日報で「現在（12時半頃）」と出た回帰（UTC の ts を JST に直していなかった） ----
import pytest

from scripts import _ollama_common as oc


@pytest.mark.parametrize(
    "ts, expected",
    [
        ("2026-08-19T12:55:19.703711+00:00", "21:55"),  # /api/megribi_score の形（UTC）
        ("2026-08-19T12:55:19Z", "21:55"),
        ("2026-08-19T19:00:00+09:00", "19:00"),  # /api/forecast_today の形（JST）
        ("2026-08-19T12:55:19", "21:55"),  # オフセット無しは UTC とみなす
        ("", None),
        (None, None),
        ("not-a-date-at-all", None),
    ],
)
def test_hm_jst_は_UTC_も_JST_も_日本時間のHHMMにする(ts, expected):
    assert oc.hm_jst(ts) == expected


def test_fetch_store_facts_の_latest_ts_は_JST(monkeypatch):
    def fake_get_json(url, timeout=0, retries=0):
        if "megribi_score" in url:
            return {"data": [{"slug": "shibuya", "score": 0.5, "total": 36, "ts": "2026-08-19T12:35:00+00:00"}]}
        if "forecast_today" in url:
            return {"data": [{"ts": "2026-08-19T23:30:00+09:00", "men_pred": 20, "women_pred": 25}]}
        return {}

    monkeypatch.setattr(oc, "_get_json", fake_get_json)
    facts = oc.fetch_store_facts("shibuya")
    assert facts["latest_ts"] == "21:35"
    assert facts["forecast_peak_time"] == "23:30"
