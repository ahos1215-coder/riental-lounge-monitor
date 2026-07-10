"""scripts/_supabase_common.py（Supabase 設定読み込みの共有実装）のテスト。

scripts/generate_weekly_insights.py と scripts/local_report_job.py に verbatim で
コピペされていた `_supabase_conf` を一本化した結果、両スクリプトが同じ結果を返す
ことをロックする。`_load_env`（.env / .env.local の手動パーサ）は元々
scripts/local_report_job.py 側にのみあった機能で、temp .env フィクスチャで
挙動が変わっていないことを確認する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts._supabase_common as common
import scripts.generate_weekly_insights as gwi
import scripts.local_report_job as lrj


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
