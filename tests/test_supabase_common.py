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

import inspect
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
