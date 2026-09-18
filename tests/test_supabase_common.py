"""scripts/_supabase_common.py（Supabase 設定読み込みの共有実装）のテスト。

scripts/generate_weekly_insights.py と scripts/local_report_job.py に verbatim で
コピペされていた `_supabase_conf` を一本化した結果、両スクリプトが同じ結果を返す
ことをロックする。`_load_env`（.env / .env.local の手動パーサ）は temp .env
フィクスチャで挙動が変わっていないことを確認する。

`_load_env` は元々8本のスクリプトに同一本文でコピーされていた（B-02）。再び
verbatim コピーが生まれる事故を検知するため、移行済みスクリプトの `_load_env` が
必ずこの共有ファイル由来であることも固定する。
"""

from __future__ import annotations

import gzip
import inspect
import json
from pathlib import Path

import pytest

import scripts._supabase_common as common
import scripts.analytics_weekly_report as awr
import scripts.backup_logs as bl
import scripts.build_templates as bt
import scripts.cleanup_old_models as com
import scripts.generate_weekly_insights as gwi
import scripts.local_report_job as lrj
import scripts.patch_weekly_store_ids as patch
import scripts.score_forecasts as sf
import scripts.snapshot_forecasts as snap


# --------------------------------------------------------------------------- #
# _supabase_conf: 環境変数の探索順・整形
# --------------------------------------------------------------------------- #
class TestSupabaseConf:
    def test_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
        assert common._supabase_conf() is None

    def test_none_when_only_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
        assert common._supabase_conf() is None

    def test_strips_trailing_slash_and_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "  https://example.supabase.co/  ")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "  secret-key  ")
        assert common._supabase_conf() == ("https://example.supabase.co", "secret-key")

    def test_service_role_key_wins_over_service_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "role-key")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "legacy-key")
        assert common._supabase_conf() == ("https://example.supabase.co", "role-key")

    def test_falls_back_to_service_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "legacy-key")
        assert common._supabase_conf() == ("https://example.supabase.co", "legacy-key")

    def test_generate_weekly_insights_and_local_report_job_agree_with_shared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """旧: 両スクリプトにそれぞれ verbatim コピーがあった。
        新: どちらも scripts/_supabase_common.py の _supabase_conf を import している
        ので、同じ環境変数に対して常に共有実装と同じ結果を返す。"""
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "role-key")
        expected = common._supabase_conf()
        assert expected == ("https://example.supabase.co", "role-key")
        assert gwi._supabase_conf() == expected
        assert lrj._supabase_conf() == expected


# --------------------------------------------------------------------------- #
# _load_env: .env / .env.local の手動パース（temp フィクスチャ）
# --------------------------------------------------------------------------- #
class TestLoadEnv:
    def test_load_env_reads_dotenv_and_dotenv_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text(
            "SUPABASE_URL=https://from-dotenv.supabase.co\n"
            "# comment line is ignored\n"
            "\n"
            'SUPABASE_SERVICE_ROLE_KEY="quoted-key"\n',
            encoding="utf-8",
        )
        (tmp_path / ".env.local").write_text(
            "SUPABASE_SERVICE_KEY='local-only-key'\n"
            "EXTRA_LOCAL_VAR=only-in-local\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
        for name in (
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_SERVICE_KEY",
            "EXTRA_LOCAL_VAR",
        ):
            monkeypatch.delenv(name, raising=False)

        common._load_env()

        assert __import__("os").environ["SUPABASE_URL"] == "https://from-dotenv.supabase.co"
        assert __import__("os").environ["SUPABASE_SERVICE_ROLE_KEY"] == "quoted-key"
        assert __import__("os").environ["EXTRA_LOCAL_VAR"] == "only-in-local"
        assert common._supabase_conf() == (
            "https://from-dotenv.supabase.co",
            "quoted-key",
        )

    def test_real_env_wins_over_dotenv_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text(
            "SUPABASE_URL=https://from-file.supabase.co\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
        monkeypatch.setenv("SUPABASE_URL", "https://from-real-env.supabase.co")

        common._load_env()

        assert __import__("os").environ["SUPABASE_URL"] == "https://from-real-env.supabase.co"

    def test_missing_env_files_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
        monkeypatch.delenv("SOME_VAR_THAT_SHOULD_NOT_EXIST", raising=False)
        common._load_env()  # 例外を投げない
        assert "SOME_VAR_THAT_SHOULD_NOT_EXIST" not in __import__("os").environ


# --------------------------------------------------------------------------- #
# _load_env / storage_* を共有実装から取っていること（verbatim コピー再発の検知）
# --------------------------------------------------------------------------- #
_SHARED_SOURCE = Path(common.__file__).resolve()

_LOAD_ENV_USERS = [
    pytest.param(awr, id="analytics_weekly_report"),
    pytest.param(bl, id="backup_logs"),
    pytest.param(bt, id="build_templates"),
    pytest.param(com, id="cleanup_old_models"),
    pytest.param(lrj, id="local_report_job"),
    pytest.param(patch, id="patch_weekly_store_ids"),
    pytest.param(sf, id="score_forecasts"),
    pytest.param(snap, id="snapshot_forecasts"),
]


@pytest.mark.parametrize("mod", _LOAD_ENV_USERS)
def test_load_env_comes_from_shared_module(mod) -> None:
    """各スクリプトの `_load_env` は共有実装そのもの（手書きコピーではない）。

    ※ scripts/train_ml_model.py だけは load_dotenv(override=True) の別仕様なので
    意図的に対象外（同ファイル内の docstring に理由を明記してある）。
    """
    assert Path(inspect.getsourcefile(mod._load_env)).resolve() == _SHARED_SOURCE


@pytest.mark.parametrize(
    "mod",
    [
        pytest.param(sf, id="score_forecasts"),
        pytest.param(bt, id="build_templates"),
        pytest.param(snap, id="snapshot_forecasts"),
    ],
)
def test_storage_get_comes_from_shared_module(mod) -> None:
    assert Path(inspect.getsourcefile(mod._storage_get.func)).resolve() == _SHARED_SOURCE


@pytest.mark.parametrize(
    "mod",
    [
        pytest.param(sf, id="score_forecasts"),
        pytest.param(bt, id="build_templates"),
        pytest.param(snap, id="snapshot_forecasts"),
        pytest.param(awr, id="analytics_weekly_report"),
    ],
)
def test_storage_put_comes_from_shared_module(mod) -> None:
    assert Path(inspect.getsourcefile(mod._storage_put.func)).resolve() == _SHARED_SOURCE


# --------------------------------------------------------------------------- #
# REST GET の gzip 受信（2026-09-18 追加）
#
# 背景: Supabase 無料枠の uncached egress（DB 側・5GB/月）が余裕 1.1 倍しかなく、
# 次に止まる最有力候補だった。主犯は urllib で REST を読むスクリプトが
# Accept-Encoding を送らず非圧縮で受けていたこと（gzip 要求で本文は 6〜11 倍に縮む・本番で実測。列数で変わる）。
#
# ここで固定するのは「ヘッダの付与」と「Content-Encoding を見た解凍」がペアで
# 動くこと。片方だけ入ると json.loads が gzip のバイト列を食って壊れるため、
# この2つは必ず一緒に検問する。
# --------------------------------------------------------------------------- #


class _FakeResponse:
    """urlopen の戻り値（context manager）の最小フェイク。"""

    def __init__(self, body: bytes, encoding: str | None) -> None:
        self._body = body
        # encoding=None は「Content-Encoding ヘッダそのものが無い」を表す
        self.headers = {} if encoding is None else {"Content-Encoding": encoding}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _capture_urlopen(monkeypatch: pytest.MonkeyPatch, body: bytes, encoding: str | None) -> dict:
    """urlopen を差し替え、送信 Request を captured["req"] に記録する。"""
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeResponse(body, encoding)

    monkeypatch.setattr(common.urllib.request, "urlopen", fake_urlopen)
    return captured


class TestRestGetBytes:
    def test_sends_accept_encoding_gzip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accept-Encoding: gzip を必ず送る（これが無いと非圧縮で受けてしまう）。"""
        cap = _capture_urlopen(monkeypatch, b"[]", None)
        common.rest_get_bytes("https://example.supabase.co/rest/v1/logs", {"apikey": "k"})
        # urllib は header 名を .capitalize() して持つ
        assert cap["req"].get_header("Accept-encoding") == "gzip"

    def test_overrides_caller_supplied_accept_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """呼び出し側が identity を渡しても上書きする（付与と解凍をペアで管理するため）。"""
        cap = _capture_urlopen(monkeypatch, b"[]", None)
        common.rest_get_bytes("https://x/rest/v1/logs", {"Accept-Encoding": "identity"})
        assert cap["req"].get_header("Accept-encoding") == "gzip"

    def test_keeps_caller_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """認証ヘッダなど呼び出し側のヘッダは保持する。"""
        cap = _capture_urlopen(monkeypatch, b"[]", None)
        common.rest_get_bytes("https://x/rest/v1/logs", {"apikey": "k", "Authorization": "Bearer k"})
        assert cap["req"].get_header("Apikey") == "k"
        assert cap["req"].get_header("Authorization") == "Bearer k"

    def test_does_not_mutate_caller_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """呼び出し側の dict を書き換えない（使い回される headers を汚さない）。"""
        _capture_urlopen(monkeypatch, b"[]", None)
        headers = {"apikey": "k"}
        common.rest_get_bytes("https://x/rest/v1/logs", headers)
        assert headers == {"apikey": "k"}

    @pytest.mark.parametrize("encoding", ["gzip", "x-gzip", "GZIP", " gzip "])
    def test_decompresses_gzip(self, monkeypatch: pytest.MonkeyPatch, encoding: str) -> None:
        """gzip と名乗る応答は解凍して返す（大文字・前後空白も吸収）。"""
        payload = b'[{"id":1,"ts":"2026-09-18T10:00:00+00:00"}]'
        _capture_urlopen(monkeypatch, gzip.compress(payload), encoding)
        assert common.rest_get_bytes("https://x/rest/v1/logs", {}) == payload

    @pytest.mark.parametrize("encoding", [None, "", "identity"])
    def test_passes_through_uncompressed(self, monkeypatch: pytest.MonkeyPatch, encoding) -> None:
        """非圧縮（ヘッダ無し / identity）はそのまま返す。PostgREST は小さな応答を圧縮しない。"""
        payload = b'[{"id":1}]'
        _capture_urlopen(monkeypatch, payload, encoding)
        assert common.rest_get_bytes("https://x/rest/v1/logs", {}) == payload

    def test_broken_gzip_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """gzip と名乗りながら壊れている本文は握りつぶさず送出する。

        握りつぶして生バイト列を返すと、下流の json.loads が分かりにくい形で落ちる。
        呼び出し側（backup_logs._get）は汎用 except で一過性エラーとして再試行する。
        """
        _capture_urlopen(monkeypatch, b"not actually gzip", "gzip")
        with pytest.raises(OSError):
            common.rest_get_bytes("https://x/rest/v1/logs", {})

    def test_unexpected_encoding_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """要求していない br などが来たら、黙って生バイト列を返さずに落ちる。"""
        _capture_urlopen(monkeypatch, b"\x00\x01", "br")
        with pytest.raises(ValueError, match="unexpected Content-Encoding"):
            common.rest_get_bytes("https://x/rest/v1/logs", {})

    def test_error_message_has_no_query_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """エラー本文にクエリ文字列を出さない（長いだけで診断に要らない）。"""
        _capture_urlopen(monkeypatch, b"", "br")
        url = "https://x/rest/v1/logs?select=id&order=ts.desc&limit=1000"
        with pytest.raises(ValueError) as exc:
            common.rest_get_bytes(url, {})
        assert "select=" not in str(exc.value)


class TestRestGetJson:
    def test_parses_gzip_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = [{"id": 1, "store_id": "shibuya"}]
        _capture_urlopen(monkeypatch, gzip.compress(json.dumps(payload).encode("utf-8")), "gzip")
        assert common.rest_get_json("https://x/rest/v1/logs", {}) == payload

    def test_parses_uncompressed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = [{"id": 2}]
        _capture_urlopen(monkeypatch, json.dumps(payload).encode("utf-8"), None)
        assert common.rest_get_json("https://x/rest/v1/logs", {}) == payload

    def test_handles_non_ascii(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """UTF-8 の日本語（店名など）が壊れない。"""
        payload = [{"label": "オリエンタルラウンジ 渋谷"}]
        _capture_urlopen(monkeypatch, gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")), "gzip")
        assert common.rest_get_json("https://x/rest/v1/logs", {}) == payload


@pytest.mark.parametrize(
    "mod",
    [
        pytest.param(bl, id="backup_logs"),
        pytest.param(bt, id="build_templates"),
    ],
)
def test_rest_get_json_comes_from_shared_module(mod) -> None:
    """REST GET の重い2本が共有ヘルパを使っていることを固定する。

    個別に urllib を直叩きする実装へ戻ると、Accept-Encoding の付与と解凍が
    また分かれて非圧縮に逆戻りする（uncached egress が倍に戻る）。
    """
    assert Path(inspect.getsourcefile(mod.rest_get_json)).resolve() == _SHARED_SOURCE
