"""毎朝1通のダイジェスト（scripts/monitor/daily_digest.py）の単体テスト。

この仕組みは「毎日必ず1通来ることで、沈黙を異常と判断できるようにする」ためのものなので、
守るべき性質は普通の監視と違う:

  1. **1項目が取れなくても1通は出る** … 8項目のうち1つが失敗しただけで本文が丸ごと
     消えるのがいちばん困る（それは沈黙そのもの）。失敗した項目だけが1行になる。
  2. **常に exit 0**            … 赤くする＝失敗メールを1通増やすこと。メールを減らす
     ための仕組みが自分でメールを増やしては本末転倒。LINE 未設定でも緑で終わる。
  3. **LINE の枠を食い潰さない** … 無料枠は月200通。定期便で使い切ると、本当の障害の
     ときに1通も送れない。180通以上なら送信しない。
  4. **1通に収まる**            … 900字を超えたら切り、切ったことが読み手に分かる。
     全文は GitHub のジョブサマリに残る。
  5. **公開ログに秘密を書かない** … このリポジトリは PUBLIC で、ジョブサマリは誰でも
     読める。Supabase のホスト名・トークンは本文にもサマリにも出さない（例外の
     メッセージ本文は URL を含みうるので、型名だけを出す）。

実ネットワークには一切出ない（urlopen を差し替え、未登録の URL が呼ばれたら落とす）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR_DIR = REPO_ROOT / "scripts" / "monitor"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ops-daily-digest.yml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dd = _load("daily_digest")

# テストで使う「秘密」。本文・サマリのどこにも出てはいけない文字列。
SUPA_HOST = "test-project-ref.supabase.co"
SUPA_URL = f"https://{SUPA_HOST}"
SUPA_KEY = "service-role-key-must-not-leak"
LINE_TOKEN = "line-token-must-not-leak"

NOW = datetime(2026, 9, 18, 0, 30, tzinfo=timezone.utc)  # JST 2026-09-18 09:30


# --------------------------------------------------------------------------- #
# urlopen の差し替え
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """urlopen の戻り値の最小フェイク（with 文で使える。`headers` は持たない
    ＝ _supabase_common.rest_get_bytes からは非圧縮として扱われる）。"""

    def __init__(self, payload: object, status: int = 200) -> None:
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _Router:
    """URL の部分一致でフェイク応答を返す。未登録の URL は即座にテストを落とす
    （＝「実ネットワークに出ていない」ことをテスト自身が保証する）。"""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.posted: list[dict] = []

    def __call__(self, req, timeout=None):  # noqa: ANN001 - urlopen 互換
        url = getattr(req, "full_url", None) or str(req)
        self.calls.append(url)
        data = getattr(req, "data", None)
        if data:
            try:
                self.posted.append({"url": url, "body": json.loads(data.decode("utf-8"))})
            except (ValueError, UnicodeDecodeError):
                self.posted.append({"url": url, "body": None})
        for pattern, value in self.routes.items():
            if pattern in url:
                if isinstance(value, BaseException):
                    raise value
                if callable(value):
                    return _FakeResponse(value(req))
                return _FakeResponse(value)
        raise AssertionError(f"未登録の URL が呼ばれた（実ネットワークに出ようとしている）: {url}")

    def hit(self, pattern: str) -> int:
        return sum(1 for url in self.calls if pattern in url)


def _runs(*names: str) -> dict:
    return {"workflow_runs": [{"name": n, "conclusion": "failure"} for n in names]}


def _workflows(*items: tuple[str, str, str]) -> dict:
    """(表示名, ファイル名, state) の並びから API 応答を作る。"""
    return {
        "workflows": [
            {"name": name, "path": f".github/workflows/{filename}", "state": state}
            for name, filename, state in items
        ]
    }


_HEALTHY = {
    "ok": True,
    "problems": [],
    "problem_detail": "",
    "memory": {"rss_mb": 389.0},
    "forecast_model": {"loaded_store_count": 42},
}

_STORAGE_ONE_FILE = [{"name": "metadata.json", "id": "x", "metadata": {"size": 1024}}]


def _default_routes(**overrides) -> dict[str, object]:
    routes: dict[str, object] = {
        "/actions/runs": _runs(),
        "/actions/workflows": _workflows(("収集監視", "check-collection-heartbeat.yml", "active")),
        "/healthz": _HEALTHY,
        "/rest/v1/logs": [{"ts": "2026-09-18T00:00:00+00:00"}],
        "/storage/v1/object/list": _STORAGE_ONE_FILE,
        "message/quota/consumption": {"totalUsage": 3},
        "message/push": {},
    }
    routes.update(overrides)
    return routes


@pytest.fixture
def router(monkeypatch):
    """既定は「全部正常」。各テストは必要な経路だけ差し替える。"""

    def _install(**overrides) -> _Router:
        r = _Router(_default_routes(**overrides))
        monkeypatch.setattr(urllib.request, "urlopen", r)
        return r

    return _install


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """実 .env.local を読ませない＋環境変数を毎回既知の状態にする。

    load_env() を潰しておかないと、開発機の本物のトークンがテスト中の os.environ に
    入り込み、「未設定なら送らない」経路のテストが本物の LINE を叩きかねない。
    """
    monkeypatch.setattr(dd, "load_env", lambda: None)
    for key in (
        "GITHUB_REPOSITORY",
        "GITHUB_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY",
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_USER_ID",
        "OPS_QUOTA_PAUSE_UNTIL",
        "GITHUB_STEP_SUMMARY",
    ):
        monkeypatch.delenv(key, raising=False)


def _configure(monkeypatch, *, line: bool = False) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("SUPABASE_URL", SUPA_URL)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SUPA_KEY)
    if line:
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", LINE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", "U-owner")


# --------------------------------------------------------------------------- #
# 1. 1項目が失敗しても1通は出る
# --------------------------------------------------------------------------- #
class Test項目ごとの独立性:
    def test_全項目が失敗しても本文は組み立てられる(self, monkeypatch, router) -> None:
        _configure(monkeypatch, line=True)
        boom = urllib.error.URLError(f"cannot reach {SUPA_HOST}")
        router(
            **{
                "/actions/runs": boom,
                "/actions/workflows": boom,
                "/healthz": boom,
                "/rest/v1/logs": boom,
                "/storage/v1/object/list": boom,
                "message/quota/consumption": boom,
            }
        )
        digest = dd.build_digest(now=NOW)
        body = digest.body

        # 見出しは必ず残る（何も届かないより「全部取れませんでした」が届くほうが遥かに良い）。
        assert "【めぐりび 朝の点検】2026-09-18" in body
        assert "※14:00 までに届かない日は、この通知自体の異常です。" in body
        # 各項目が独立に落ちている（1つの失敗が他を巻き込んでいない）。
        # サイトだけは「取得失敗」ではなく ❌ 到達できません と出す。/healthz は
        # 設計上つねに 200 を返すので、非200・到達不能は「確認できなかった」ではなく
        # 「サイトが落ちている」という、この通知でいちばん重い事実だから。
        assert body.count("取得失敗") == 5
        for label in (dd.L_FAILED, dd.L_STOPPED, dd.L_COLLECT, dd.L_STORAGE, dd.L_LINE):
            assert f"{label}: 取得失敗" in body
        assert f"{dd.L_SITE}: ❌ 到達できません" in body

    def test_失敗行に例外メッセージを載せない(self, monkeypatch, router) -> None:
        """urllib の例外文字列は接続先ホストを含む。型名だけに切り詰めていること。"""
        _configure(monkeypatch)
        router(**{"/rest/v1/logs": urllib.error.URLError(f"no route to {SUPA_HOST}")})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_COLLECT}: 取得失敗（URLError）" in body
        assert SUPA_HOST not in body

    def test_一項目の失敗が他の項目を消さない(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(**{"/healthz": urllib.error.HTTPError("u", 500, "err", {}, None)})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_SITE}: ❌ 到達できません（HTTP 500）" in body
        # 隣の項目は普通に出ている
        assert f"{dd.L_FAILED}: ✅ 失敗なし" in body
        assert f"{dd.L_STORAGE}: 0MB / 1GB" in body


# --------------------------------------------------------------------------- #
# 2. 失敗ワークフローの集計
# --------------------------------------------------------------------------- #
class Test失敗ワークフロー:
    def test_失敗ゼロなら失敗なし(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router()
        assert f"{dd.L_FAILED}: ✅ 失敗なし" in dd.build_digest(now=NOW, dry_run=True).body

    def test_ワークフロー名ごとに集計する(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(**{"/actions/runs": _runs("A", "B", "A")})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_FAILED}: ❌ 3件 / 2本" in body
        assert "・A ×2" in body
        assert "・B ×1" in body

    def test_多すぎるときは上位だけ出して残りは本数で示す(self, monkeypatch, router) -> None:
        """障害中は1原因で11本が同時に落ちる。全部並べると900字が名前で埋まる。"""
        _configure(monkeypatch)
        names = [f"WF{i}" for i in range(11)]
        router(**{"/actions/runs": _runs(*names)})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert body.count("・WF") == dd.FAILED_WF_SHOWN
        assert f"・ほか{11 - dd.FAILED_WF_SHOWN}本" in body

    def test_リポジトリ未設定なら未設定と出る(self, monkeypatch, router) -> None:
        router()
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_FAILED}: 未設定" in body

    def test_失敗runの照会は34時間ぶんを見る(self, monkeypatch, router) -> None:
        """連続2回のダイジェストが途切れずに覆うだけの窓が要る。

        日次 cron の実測では、このリポジトリの連続実行間隔が最大 31.87 時間だった
        （2026-09-18 の監査。CLAUDE.md §4 罠5 の「1.5〜5時間遅れ」より実際は広い）。
        26時間だと最大6時間ぶんがどちらのダイジェストにも載らず、しかもその日は
        「✅ 失敗なし」と出るので取りこぼしに気づけない。34時間は実測の最大間隔に
        2時間強の余裕を足した値。
        """
        _configure(monkeypatch)
        r = router()
        dd.build_digest(now=NOW, dry_run=True)
        (runs_url,) = [u for u in r.calls if "/actions/runs" in u]
        expected = (NOW - timedelta(hours=34)).strftime("%Y-%m-%dT%H%%3A%M%%3A%SZ")
        assert expected in runs_url

    def test_照会はcompletedで引く(self, monkeypatch, router) -> None:
        """status=failure で絞ると startup_failure / timed_out を1件も拾えない。

        どちらも run は赤くなり失敗メールも飛ぶのに、ダイジェストだけが
        「✅ 失敗なし」と言い切る＝この通知がいちばんやってはいけない嘘になる。
        """
        _configure(monkeypatch)
        r = router()
        dd.build_digest(now=NOW, dry_run=True)
        (runs_url,) = [u for u in r.calls if "/actions/runs" in u]
        assert "status=completed" in runs_url
        assert "status=failure" not in runs_url

    def test_startup_failureとtimed_outも失敗として数える(self, monkeypatch, router) -> None:
        """実在した startup_failure（2026-04 の cleanup 2件）が黙って消えないこと。"""
        _configure(monkeypatch)
        router(
            **{
                "/actions/runs": {
                    "workflow_runs": [
                        {"name": "Cleanup Old Logs", "conclusion": "startup_failure"},
                        {"name": "Train ML model", "conclusion": "timed_out"},
                        {"name": "Warm CDN", "conclusion": "failure"},
                    ]
                }
            }
        )
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_FAILED}: ❌ 3件" in body
        # failure 以外は種別を添えて、原因の見当がつくようにする
        assert "Cleanup Old Logs[startup_failure]" in body
        assert "Train ML model[timed_out]" in body
        assert "Warm CDN ×1" in body

    def test_未知のconclusionも失敗側に倒す(self, monkeypatch, router) -> None:
        """GitHub が新しい conclusion を足しても、拾う側に倒れること（許可リスト判定）。"""
        _configure(monkeypatch)
        router(**{"/actions/runs": {"workflow_runs": [{"name": "X", "conclusion": "brand_new_thing"}]}})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_FAILED}: ❌ 1件" in body
        assert "X[brand_new_thing]" in body

    def test_成功扱いのconclusionは数えない(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(
            **{
                "/actions/runs": {
                    "workflow_runs": [
                        {"name": "A", "conclusion": "success"},
                        {"name": "B", "conclusion": "skipped"},
                        {"name": "C", "conclusion": "cancelled"},
                        {"name": "D", "conclusion": "neutral"},
                    ]
                }
            }
        )
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_FAILED}: ✅ 失敗なし" in body


# --------------------------------------------------------------------------- #
# 3. 止まっているワークフロー（意図的な2本は除外）
# --------------------------------------------------------------------------- #
class Test止まっているワークフロー:
    def test_意図的にdisabledの2本は除外される(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(
            **{
                "/actions/workflows": _workflows(
                    ("週次（緊急用）", "generate-weekly-insights.yml", "disabled_manually"),
                    ("日次（緊急用）", "trigger-blog-cron.yml", "disabled_manually"),
                    ("収集監視", "check-collection-heartbeat.yml", "active"),
                )
            }
        )
        assert f"{dd.L_STOPPED}: ✅ なし" in dd.build_digest(now=NOW, dry_run=True).body

    def test_60日無活動の自動無効化は必ず出す(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(
            **{
                "/actions/workflows": _workflows(
                    ("週次（緊急用）", "generate-weekly-insights.yml", "disabled_manually"),
                    ("収集監視", "check-collection-heartbeat.yml", "disabled_inactivity"),
                )
            }
        )
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_STOPPED}: ⚠️ 1本" in body
        assert "・収集監視（disabled_inactivity）" in body
        assert "週次（緊急用）" not in body

    def test_除外リストはファイル名で持つ(self) -> None:
        """表示名は変わりうるので、除外はファイル名で固定する（定数の番犬）。"""
        assert dd.INTENTIONALLY_DISABLED == (
            "generate-weekly-insights.yml",
            "trigger-blog-cron.yml",
        )


# --------------------------------------------------------------------------- #
# 4. サイト・収集・Storage
# --------------------------------------------------------------------------- #
class Test状態の項目:
    def test_正常なhealthzを1行にまとめる(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router()
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_SITE}: ✅ 正常 / RSS 389MB(76%) / モデル42店" in body

    def test_okがfalseなら理由も出す(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(
            **{
                "/healthz": {
                    "ok": False,
                    "problems": ["data_upstream_payment_required"],
                    "problem_detail": "Supabase /rest/v1/logs が HTTP 402",
                    "memory": {"rss_mb": 400.0},
                    "forecast_model": {"loaded_store_count": 0},
                }
            }
        )
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_SITE}: ❌ ok=false" in body
        assert "HTTP 402" in body

    def test_RSSが読めなくてもサイトの行は消さない(self, monkeypatch, router) -> None:
        """RSS は添え物。本当に読みたいのは ok と problem_detail のほう。"""
        _configure(monkeypatch)
        router(**{"/healthz": {"ok": True, "memory": {"rss_mb": None}, "forecast_model": {}}})
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_SITE}: ✅ 正常 / RSS不明 / モデル不明" in body

    def test_収集の鮮度を時間で出す(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router(**{"/rest/v1/logs": [{"ts": "2026-09-17T20:30:00+00:00"}]})
        assert f"{dd.L_COLLECT}: ✅ 最新データは 4.0 時間前" in dd.build_digest(now=NOW, dry_run=True).body

    def test_24時間を超えたら異常マーク(self, monkeypatch, router) -> None:
        """収集は夜間のみなので昼間に14時間空くのは正常。24時間超は窓に関係なく異常。"""
        _configure(monkeypatch)
        router(**{"/rest/v1/logs": [{"ts": "2026-09-16T20:30:00+00:00"}]})
        assert f"{dd.L_COLLECT}: ❌ 最新データは 28.0 時間前" in dd.build_digest(now=NOW, dry_run=True).body

    def test_認証情報が無ければ未設定と出る(self, monkeypatch, router) -> None:
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        router()
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert f"{dd.L_COLLECT}: 未設定" in body
        assert f"{dd.L_STORAGE}: 未設定" in body

    def test_Storageはフォルダを辿って合計する(self, monkeypatch, router) -> None:
        """list API は1階層ぶんしか返さない（フォルダは id:null で現れる）。"""
        pages = {
            "": [
                {"name": "forecast", "id": None},
                {"name": "top.json", "id": "a", "metadata": {"size": 1024 * 1024}},
            ],
            "forecast/": [
                {"name": "model.bin", "id": "b", "metadata": {"size": 4 * 1024 * 1024}},
            ],
        }

        def handler(req):
            body = json.loads(req.data.decode("utf-8"))
            return [] if body.get("offset") else pages.get(body.get("prefix", ""), [])

        _configure(monkeypatch)
        router(**{"/storage/v1/object/list": handler})
        assert f"{dd.L_STORAGE}: 5MB / 1GB（0%）2個" in dd.build_digest(now=NOW, dry_run=True).body


# --------------------------------------------------------------------------- #
# 5. 期限つきリスク（30日フィルタ）
# --------------------------------------------------------------------------- #
class Test期限:
    def test_出典の3件を定数で持つ(self) -> None:
        """docs/FAILURE_MAP.md の「固定日付のリスク」と同じ3件（定数の番犬）。"""
        assert [iso for _label, iso in dd.DEADLINES] == ["2026-10-01", "2026-11-20", "2026-12-31"]

    def test_31日先は出さない(self) -> None:
        due = dd.parse_ymd("2026-10-01")
        assert dd.section_deadlines(due - timedelta(days=31)) == []

    def test_30日先は出す(self) -> None:
        due = dd.parse_ymd("2026-10-01")
        lines = dd.section_deadlines(due - timedelta(days=30))
        assert len(lines) == 1
        assert "まで30日" in lines[0]

    def test_期限切れは黙らせない(self) -> None:
        """過ぎた瞬間に消えると「予告を受けたが何もしなかった」型の再発そのものになる。"""
        due = dd.parse_ymd("2026-10-01")
        lines = dd.section_deadlines(due + timedelta(days=3))
        assert "🔴" in lines[0]
        assert "3日超過" in lines[0]

    def test_今日時点ではNode20だけが出る(self, monkeypatch, router) -> None:
        _configure(monkeypatch)
        router()
        body = dd.build_digest(now=NOW, dry_run=True).body
        assert body.count(f"{dd.L_DEADLINE}: ") == 1
        assert "Node.js 20" in body


# --------------------------------------------------------------------------- #
# 6. 一時停止変数
# --------------------------------------------------------------------------- #
class Test一時停止:
    def test_未来日ならゲート有効と出す(self) -> None:
        lines = dd.section_pause(dd.parse_ymd("2026-09-18"), "2026-09-20")
        assert lines and "ゲート有効（2026-09-20まで" in lines[0]

    def test_過ぎていれば何も出さない(self) -> None:
        assert dd.section_pause(dd.parse_ymd("2026-09-18"), "2026-09-16") == []

    def test_変数未設定でもゲートの既定日で判定する(self, monkeypatch) -> None:
        """変数だけを見ると「ゲートが効いているのに黙る」穴ができる。"""
        monkeypatch.setattr(dd, "GATE_DEFAULT_UNTIL", "2026-09-20")
        lines = dd.section_pause(dd.parse_ymd("2026-09-18"), "")
        assert lines and "既定値" in lines[0]

    def test_既定日も過ぎていれば何も出さない(self, monkeypatch) -> None:
        monkeypatch.setattr(dd, "GATE_DEFAULT_UNTIL", "2026-09-16")
        assert dd.section_pause(dd.parse_ymd("2026-09-18"), "") == []

    def test_既定日を読めない環境でも落ちない(self, monkeypatch) -> None:
        monkeypatch.setattr(dd, "GATE_DEFAULT_UNTIL", "")
        assert dd.section_pause(dd.parse_ymd("2026-09-18"), "") == []

    def test_読めない日付は警告にする(self) -> None:
        lines = dd.section_pause(dd.parse_ymd("2026-09-18"), "20260920")
        assert lines and "読めません" in lines[0]


# --------------------------------------------------------------------------- #
# 7. 900字で切る
# --------------------------------------------------------------------------- #
class Test長さの上限:
    def test_短い本文はそのまま(self) -> None:
        assert dd.clip_for_line("あいうえお") == "あいうえお"

    def test_超えたら900字ちょうどに切って目印を付ける(self) -> None:
        clipped = dd.clip_for_line("あ" * 2000)
        assert len(clipped) == dd.LINE_MAX_CHARS == 900
        assert clipped.endswith(dd.MORE_SUFFIX)

    def test_送信本文だけが切られサマリには全文が残る(self, monkeypatch, router, tmp_path) -> None:
        _configure(monkeypatch, line=True)
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        # 上位5本しか名前を出さない設計なので、1本あたりを長くして 900 字を超えさせる
        # （現実には起きにくいが、溢れたときの振る舞いを固定しておく）。
        long_names = [("非常に長い名前のワークフロー" * 15) + str(i) for i in range(11)]
        r = router(**{"/actions/runs": _runs(*long_names)})

        assert dd.main([]) == 0

        (push,) = [p for p in r.posted if "message/push" in p["url"]]
        sent = push["body"]["messages"][0]["text"]
        assert len(sent) == dd.LINE_MAX_CHARS
        assert sent.endswith(dd.MORE_SUFFIX)
        # 全文はサマリに残っている（切られた末尾の行がこちらには載っている）
        written = summary.read_text(encoding="utf-8")
        assert len(written) > dd.LINE_MAX_CHARS
        assert "Node.js 20" in written


# --------------------------------------------------------------------------- #
# 8. 送るか送らないか（LINE）
# --------------------------------------------------------------------------- #
class TestLINE送信:
    def test_未設定でもexit0で送らない(self, monkeypatch, router, capsys, tmp_path) -> None:
        _configure(monkeypatch)  # LINE の env は入れない
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        r = router()

        assert dd.main([]) == 0

        assert r.hit("message/push") == 0
        assert "::warning::" in capsys.readouterr().out
        # 本文はサマリに残っている（＝届かなくても読む手段がある）
        assert "朝の点検ダイジェスト" in summary.read_text(encoding="utf-8")

    def test_設定済みなら1通だけ送る(self, monkeypatch, router) -> None:
        _configure(monkeypatch, line=True)
        r = router()
        assert dd.main([]) == 0
        assert r.hit("message/push") == 1

    def test_180通に達していたら送らない(self, monkeypatch, router) -> None:
        """無料枠200通。定期便で使い切ると本当の障害のときに1通も送れない。"""
        _configure(monkeypatch, line=True)
        r = router(**{"message/quota/consumption": {"totalUsage": dd.LINE_SKIP_AT}})
        assert dd.main([]) == 0
        assert r.hit("message/push") == 0

    def test_179通なら送る(self, monkeypatch, router) -> None:
        _configure(monkeypatch, line=True)
        r = router(**{"message/quota/consumption": {"totalUsage": dd.LINE_SKIP_AT - 1}})
        assert dd.main([]) == 0
        assert r.hit("message/push") == 1

    def test_消費数は残りとして本文に出る(self, monkeypatch, router) -> None:
        _configure(monkeypatch, line=True)
        router(**{"message/quota/consumption": {"totalUsage": 12}})
        assert f"{dd.L_LINE}: ✅ 当月12/200通（残り188）" in dd.build_digest(now=NOW).body

    def test_送信失敗でもexit0(self, monkeypatch, router) -> None:
        """トークン失効（401）はいまの実態。ここで赤くすると毎朝メールが1通増える。"""
        _configure(monkeypatch, line=True)
        router(**{"message/push": urllib.error.HTTPError("u", 401, "unauthorized", {}, None)})
        assert dd.main([]) == 0

    def test_dryrunはLINEに一切触らない(self, monkeypatch, router) -> None:
        _configure(monkeypatch, line=True)
        r = router()
        assert dd.main(["--dry-run"]) == 0
        assert r.hit("message/push") == 0
        assert r.hit("message/quota") == 0


# --------------------------------------------------------------------------- #
# 9. 公開ログに秘密を書かない
# --------------------------------------------------------------------------- #
class Test秘密を出さない:
    def test_サマリにホスト名もトークンも出ない(self, monkeypatch, router, capsys, tmp_path) -> None:
        _configure(monkeypatch, line=True)
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        router()

        assert dd.main([]) == 0

        written = summary.read_text(encoding="utf-8")
        printed = capsys.readouterr().out
        for secret in (SUPA_HOST, SUPA_URL, SUPA_KEY, LINE_TOKEN, "gh-token", "U-owner"):
            assert secret not in written
            assert secret not in printed

    def test_例外がホスト名を含んでいても出さない(self, monkeypatch, router, tmp_path) -> None:
        _configure(monkeypatch, line=True)
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        boom = urllib.error.URLError(f"HTTPSConnectionPool(host='{SUPA_HOST}') failed")
        router(**{"/rest/v1/logs": boom, "/storage/v1/object/list": boom})

        assert dd.main([]) == 0
        assert SUPA_HOST not in summary.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 10. ワークフロー側の約束
# --------------------------------------------------------------------------- #
class Testワークフロー:
    @staticmethod
    def _doc() -> dict:
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_日次スケジュールと手動実行を持つ(self) -> None:
        doc = self._doc()
        triggers = doc.get("on") if "on" in doc else doc.get(True)
        crons = [entry["cron"] for entry in (triggers or {}).get("schedule") or []]
        # 日次1本だけ（実測で欠落ゼロなのは日次。毎時24%・2時間毎43%には頼らない）
        assert len(crons) == 1
        minute, hour, *_rest = crons[0].split()
        assert hour == "0"  # UTC 0 時台 = JST 9 時台
        assert 0 <= int(minute) < 60
        assert "workflow_dispatch" in (triggers or {})

    def test_必要な権限だけを持つ(self) -> None:
        assert self._doc()["permissions"] == {"actions": "read", "contents": "read"}

    def test_スクリプトを呼ぶだけでPythonを埋め込まない(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "python3 scripts/monitor/daily_digest.py" in text
        assert "<<'PY'" not in text

    def test_常に成功で終える(self) -> None:
        """赤くする＝失敗メールを1通増やすこと。この仕組みの目的と正面衝突する。"""
        assert "exit 0" in WORKFLOW.read_text(encoding="utf-8")

    def test_運用ルールを冒頭に書いてある(self) -> None:
        """「来ないこと」に気づくための基準がファイルに無いと、仕組みが成立しない。"""
        header = "\n".join(WORKFLOW.read_text(encoding="utf-8").splitlines()[:40])
        assert "14:00" in header

    def test_スクリプトが読むenvを全部渡す(self) -> None:
        """1つ渡し忘れると、その項目だけ静かに「未設定」になって気付けない。"""
        import re

        script = (MONITOR_DIR / "daily_digest.py").read_text(encoding="utf-8")
        wanted = set(re.findall(r'os\.environ\.get\(\s*"([A-Z0-9_]+)"', script))
        wanted -= {"GITHUB_STEP_SUMMARY"}  # runner が常に設定する
        provided: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                env = node.get("env")
                if isinstance(env, dict):
                    provided.update(str(k) for k in env)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(self._doc())
        assert wanted - provided == set()
