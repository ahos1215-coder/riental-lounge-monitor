"""監視スクリプトが「照会に失敗した理由」を通知に載せられることを固定するテスト。

守っている事故（2026-09-05〜09-09）:
  Supabase が全リクエストへ HTTP 402（egress クォータ超過）を返し始めたのに、
  オーナーが気づくまで3日半かかった。検知は動いていた（収集ハートビートは
  停止5時間後から16回連続で赤）。壊れていたのは**届け方**で、
    - 照会に失敗すると detail を出す前に sys.exit(1) していた → 通知本文が空
    - 残る固定文が挙げる原因は「PC停止 / Render障害 / cron-job.org障害」＝全部ハズレ
  だったため、通知に本当の原因が一文字も載らなかった。

ここで固定するのは2つだけ:
  1) 照会失敗時に detail（HTTPステータスとレスポンス本文の先頭）が必ず出ること
  2) 401/402/403 が「課金・認証起因」として区別され、ハズレの原因を出さないこと

Supabase へは一切アクセスしない（urlopen を差し替える）。
"""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"

# 2026-09-05 に Supabase が返していた本文（通知に載ってほしい一次情報）。
QUOTA_BODY = b'{"message":"exceed_cached_egress_quota","statusCode":"402"}'

# 通知に出てはいけない「ハズレの原因」。402 のときにこれらを出すと、
# 読んだ人が PC・Render・cron-job.org・Ollama を調べに行って時間を失う。
WRONG_CAUSES = ("PC停止", "Render障害", "cron-job.org", "Ollama")


def _load(name: str):
    """scripts/monitor/<name>.py を単体モジュールとして読み込む（実行時と同じ形）。"""
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qf = _load("_query_failure")
hb = _load("check_collection_heartbeat")
daily = _load("check_daily_published")
weekly = _load("check_weekly_published")


def _http_error(status: int, body: bytes = QUOTA_BODY) -> HTTPError:
    return HTTPError(
        url="https://example.supabase.co/rest/v1/logs",
        code=status,
        msg="Payment Required",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


class Test失敗の説明:
    def test_402は課金起因として分類される(self) -> None:
        f = qf.describe(_http_error(402))
        assert f.status == 402
        assert f.is_billing is True
        assert "exceed_cached_egress_quota" in f.body

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_401と403も課金認証起因(self, status: int) -> None:
        assert qf.describe(_http_error(status, b"nope")).is_billing is True

    @pytest.mark.parametrize("status", [429, 500, 502, 544])
    def test_一時的な失敗は課金起因にしない(self, status: int) -> None:
        assert qf.describe(_http_error(status, b"busy")).is_billing is False

    def test_通信失敗はステータスなしとして説明できる(self) -> None:
        f = qf.describe(URLError("The read operation timed out"))
        assert f.status is None
        assert f.is_billing is False
        detail = f.detail()
        assert "（なし＝通信失敗・タイムアウト）" in detail
        assert "The read operation timed out" in detail

    def test_detailにステータスと本文が載る(self) -> None:
        detail = qf.describe(_http_error(402)).detail()
        assert "- HTTP ステータス: 402" in detail
        assert "exceed_cached_egress_quota" in detail
        assert "Supabase ダッシュボード" in detail  # 見に行く先が書いてある

    def test_本文は200字で切り詰めて1行に畳む(self) -> None:
        f = qf.describe(_http_error(402, b"a\nb" + b"x" * 500))
        assert "\n" not in f.body
        assert len(f.body) == qf.BODY_PREVIEW_CHARS + 1  # 末尾の省略記号ぶん

    def test_課金起因ならハズレの原因を出さない(self) -> None:
        fallback = "⚠️ PC停止 / Render障害 / cron-job.org障害など"
        cause = qf.describe(_http_error(402)).cause_line(fallback)
        assert "Supabase が 402 を返しています" in cause
        assert "プロジェクトが停止している可能性があります" in cause
        for wrong in WRONG_CAUSES:
            assert wrong not in cause

    def test_課金起因でなければ従来の固定文に戻る(self) -> None:
        fallback = "⚠️ PC停止 / Render障害 / cron-job.org障害など"
        assert qf.describe(_http_error(500, b"boom")).cause_line(fallback) == fallback

    def test_本文が読めなくても説明は作れる(self) -> None:
        class _Broken(Exception):
            code = 402

            def read(self):  # noqa: ANN201
                raise OSError("stream already consumed")

        f = qf.describe(_Broken("boom"))
        assert f.status == 402 and f.body == ""
        assert "boom" in f.detail()

    def test_本文を読まずに再試行可否だけ判定できる(self) -> None:
        """describe() は本文を消費するので、再試行判定は別の関数で行う。"""
        err = _http_error(402)
        assert qf.is_billing_error(err) is True
        # 本文はまだ消費されていない＝あとから通知に載せられる
        assert "exceed_cached_egress_quota" in qf.describe(err).body
        assert qf.is_billing_error(URLError("timeout")) is False


class Test本文が想定外という第3分類:
    """「通信失敗」と「本文が想定外」を混ぜないこと（2026-09-09）。

    以前は `raise ValueError("unexpected response shape: ...")` も通信失敗と同じ器に
    包まれていたため、通知に「HTTP ステータス: （なし＝通信失敗・タイムアウト）」と出た。
    実際は HTTP が成功していて中身だけが想定外なので、読んだ人はネットワークや PC を
    疑って調べる先を間違える。ここではその書き分けを固定する。
    """

    def test_ステータスが取れたのに通信失敗とは言わない(self) -> None:
        f = qf.describe(qf.UnexpectedBody("配列ではない", status=200, body=b'{"message":"x"}'))
        assert f.unexpected_body is True
        assert f.status == 200
        detail = f.detail()
        assert "- HTTP ステータス: 200（通信は成功。本文が想定外の形）" in detail
        assert "（なし＝通信失敗・タイムアウト）" not in detail

    def test_想定外の本文でもハズレの原因を出さない(self) -> None:
        fallback = "⚠️ PC停止 / Render障害 / cron-job.org障害など"
        cause = qf.describe(qf.UnexpectedBody("配列ではない", status=200)).cause_line(fallback)
        assert "想定外の形" in cause
        for wrong in WRONG_CAUSES:
            assert wrong not in cause

    def test_素のValueErrorも本文が想定外として扱う(self) -> None:
        """json.JSONDecodeError も ValueError。ステータスが無くても通信失敗とは言わない。"""
        f = qf.describe(ValueError("Expecting value: line 1 column 1"))
        assert f.unexpected_body is True
        assert "不明（通信は成功。本文が想定外の形）" in f.detail()

    def test_通信失敗は第3分類に混ざらない(self) -> None:
        assert qf.describe(URLError("timed out")).unexpected_body is False
        assert qf.describe(_http_error(402)).unexpected_body is False

    def test_課金起因の判定は第3分類に影響されない(self) -> None:
        """200 は課金起因ではないので、Supabase の Billing を見に行かせない。"""
        assert qf.describe(qf.UnexpectedBody("x", status=200)).is_billing is False


class Test公開リポジトリに本文を出さない:
    """このリポジトリは public。GITHUB_STEP_SUMMARY も Actions のログも誰でも読める。

    レスポンス本文200字はそこへ出さず、非公開の通知（LINE / Slack）にだけ載せる。
    ステータスと例外メッセージは原因追跡に要るので公開側にも残す。
    """

    def test_include_bodyがFalseなら本文を落とす(self) -> None:
        f = qf.describe(_http_error(402))
        assert "exceed_cached_egress_quota" in f.detail()
        public = f.detail(include_body=False)
        assert "exceed_cached_egress_quota" not in public
        # 何が落ちているのかは分かるようにする（黙って消さない）
        assert "通知(LINE/Slack)にだけ載せています" in public
        # 追跡に要る情報は公開側にも残る
        assert "- HTTP ステータス: 402" in public
        assert "Supabase ダッシュボード" in public

    def test_本文が無いときは断り書きも出さない(self) -> None:
        public = qf.describe(URLError("timed out")).detail(include_body=False)
        assert "通知(LINE/Slack)にだけ載せています" not in public


class _Recorder:
    """urlopen の差し替え。呼ばれた回数を数え、毎回同じ例外を投げる。"""

    def __init__(self, factory) -> None:  # noqa: ANN001
        self.factory = factory
        self.calls = 0

    def __call__(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        raise self.factory()


@pytest.fixture()
def gha_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """GHA と同じ形の環境（Supabase 設定 + 出力ファイル2種）を用意する。"""
    out = tmp_path / "output.txt"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key-not-a-secret")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("ALLOWED_MISSING_SLUGS", raising=False)
    return out, summary


def _outputs(out: Path) -> str:
    return out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("module", "attempts_attr"),
    [
        (hb, "NEWEST_ATTEMPTS"),
        (daily, "FETCH_ATTEMPTS"),
        (weekly, "FETCH_ATTEMPTS"),
    ],
    ids=["heartbeat", "daily", "weekly"],
)
class Test監視3本の照会失敗:
    def test_402なら原因を言って1で終わる(
        self, module, attempts_attr, gha_env, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        out, summary = gha_env
        recorder = _Recorder(lambda: _http_error(402))
        monkeypatch.setattr(urllib.request, "urlopen", recorder)

        # 旧実装は sys.exit(1)（= SystemExit）で、main の出力処理に到達できなかった。
        assert module.main() == 1

        outputs = _outputs(out)
        assert "detail<<EOF" in outputs
        assert "- HTTP ステータス: 402" in outputs
        assert "exceed_cached_egress_quota" in outputs  # 一次情報が通知に載る
        assert "cause<<EOF" in outputs
        assert "Supabase が 402 を返しています" in outputs
        assert "プロジェクトが停止している可能性があります" in outputs
        # ステップサマリにも同じ detail が出る（Actions の画面で読める）
        assert "- HTTP ステータス: 402" in summary.read_text(encoding="utf-8")

        # 課金起因のときはハズレの原因を1つも出さない
        cause = outputs.split("cause<<EOF\n", 1)[1]
        for wrong in WRONG_CAUSES:
            assert wrong not in cause

    def test_402は再試行しない(
        self, module, attempts_attr, gha_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """再試行しても直らないので、待たずに人へ届ける（1回で諦める）。"""
        recorder = _Recorder(lambda: _http_error(402))
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        monkeypatch.setattr(
            module.time, "sleep", lambda *_a, **_k: pytest.fail("402 で待ってはいけない")
        )
        assert module.main() == 1
        # daily は2エディションぶん呼ぶので「試行回数ぶん繰り返していない」ことを見る
        assert recorder.calls <= 2
        assert recorder.calls < getattr(module, attempts_attr) * 2

    def test_通信失敗でもdetailは空にならない(
        self, module, attempts_attr, gha_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(lambda: URLError("The read operation timed out"))
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        monkeypatch.setattr(module, attempts_attr, 1)  # 待たせない

        assert module.main() == 1

        outputs = _outputs(gha_env[0])
        assert "Supabase 照会に失敗したため、監視は判定できていません。" in outputs
        assert "The read operation timed out" in outputs
        # 原因を特定できないときは従来の固定文（PC停止 等）に戻る。
        # ワークフローの `outputs.cause || '<固定文>'` は、スクリプトが異常終了して
        # cause を書けなかったときのための保険であって、通常はこちらが埋まる。
        assert module.GENERIC_CAUSE in outputs


class _FakeResponse:
    """urlopen が返すレスポンスの最小の偽物（with 文・.status・.read()）。"""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_exc) -> bool:  # noqa: ANN002
        return False

    def read(self) -> bytes:
        return self._payload


class Test日次チェックの照会失敗の届け方:
    """check_daily_published.py 側で、上の分類が実際に通知へ届くこと。"""

    def _run(self, payload: bytes, gha_env, monkeypatch: pytest.MonkeyPatch) -> int:
        monkeypatch.setattr(daily, "FETCH_ATTEMPTS", 1)  # 待たせない
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse(payload, status=200)
        )
        return daily.main()

    def test_200なのに配列でない応答は通信失敗と言わない(
        self, gha_env, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """PostgREST がエラーオブジェクトを 200 で返した、のような形。"""
        out, summary = gha_env
        assert self._run(b'{"message":"boom","hint":"x"}', gha_env, monkeypatch) == 1

        outputs = _outputs(out)
        assert "- HTTP ステータス: 200（通信は成功。本文が想定外の形）" in outputs
        assert "（なし＝通信失敗・タイムアウト）" not in outputs
        # 想定外の本文は通知（非公開）にだけ載る
        assert '"message":"boom"' in outputs.replace(" ", "")
        assert "cause<<EOF" in outputs
        cause = outputs.split("cause<<EOF\n", 1)[1]
        for wrong in WRONG_CAUSES:
            assert wrong not in cause

    def test_JSONですらない応答も同じ扱い(
        self, gha_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._run(b"<html>502 Bad Gateway</html>", gha_env, monkeypatch) == 1
        assert "- HTTP ステータス: 200（通信は成功。本文が想定外の形）" in _outputs(gha_env[0])

    def test_想定外の本文は公開される場所に出さない(
        self, gha_env, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """ステップサマリと標準出力は公開リポジトリでは誰でも読める。"""
        out, summary = gha_env
        assert self._run(b'{"message":"secret-ish-internal-detail"}', gha_env, monkeypatch) == 1

        public = summary.read_text(encoding="utf-8") + capsys.readouterr().out
        assert "secret-ish-internal-detail" not in public
        assert "- HTTP ステータス: 200（通信は成功。本文が想定外の形）" in public  # 原因追跡は残す
        # 通知側（GITHUB_OUTPUT）にはちゃんと載っている
        assert "secret-ish-internal-detail" in _outputs(out)

    def test_402の本文も公開される場所には出さない(
        self, gha_env, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        out, summary = gha_env
        monkeypatch.setattr(urllib.request, "urlopen", _Recorder(lambda: _http_error(402)))
        assert daily.main() == 1

        public = summary.read_text(encoding="utf-8") + capsys.readouterr().out
        assert "exceed_cached_egress_quota" not in public
        assert "- HTTP ステータス: 402" in public
        assert "exceed_cached_egress_quota" in _outputs(out)


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
SITE_DOWN_WATCH = WORKFLOWS / "site-down-watch.yml"


def _yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Testサイト停止の外形監視:
    """site-down-watch.yml が「Supabaseが死んでいても動く」形を保っていること。

    2026-09-05 の事故では外形監視5経路が3日間すべて緑だった。`/healthz` は
    payload を jsonify して返すだけで常に200なので、下流が全滅していても気付けない。
    この1本だけは「利用者に本物のデータが出ているか」を見る。
    """

    def test_公開APIを叩いていてSupabaseの認証情報を使わない(self) -> None:
        text = SITE_DOWN_WATCH.read_text(encoding="utf-8")
        assert "https://www.meguribi.jp/api/range?store=shibuya&limit=1" in text
        # Supabase の秘密が要るなら、Supabase が死んだ日にこの監視も道連れになる。
        assert "SUPABASE_URL" not in text
        assert "SUPABASE_SERVICE_ROLE_KEY" not in text

    def test_ワークフロー名だけで意味が通る(self) -> None:
        """GitHub の失敗メールは件名にワークフロー名しか載せない。

        今回の事故では check-... / warm-... という名前の失敗メールが9ワークフロー
        49通に増幅されて埋もれた。この1本は件名で用件が分かる日本語にしてある。
        """
        name = _yaml(SITE_DOWN_WATCH)["name"]
        assert "サイト停止" in name
        assert "check" not in name.lower()
        assert "warm" not in name.lower()

    def test_通知本文にHTTPステータスと応答本文が載る(self) -> None:
        doc = _yaml(SITE_DOWN_WATCH)
        body = doc["jobs"]["notify"]["with"]["custom_body"]
        assert "outputs.status" in body
        assert "outputs.body" in body
        outputs = doc["jobs"]["probe"]["outputs"]
        assert set(outputs) >= {"down", "status", "body", "url"}

    def test_1回の非200では落とさない(self) -> None:
        """Render のコールドスタート由来の一時的な502で誤報しないこと。"""
        run = _yaml(SITE_DOWN_WATCH)["jobs"]["probe"]["steps"][0]["run"]
        assert run.count("probe_once") >= 3  # 定義 + 1回目 + 再試行
        assert "sleep 60" in run

    def test_LINEのSecretが未設定でも壊れない(self) -> None:
        steps = _yaml(SITE_DOWN_WATCH)["jobs"]["probe"]["steps"]
        line_step = next(s for s in steps if "LINE" in (s.get("name") or ""))
        # 既存の check-pat-expiry.yml と同じ Secret 名・同じ「未設定ならスキップ」の形。
        assert line_step["env"]["LINE_TOKEN"] == "${{ secrets.LINE_CHANNEL_ACCESS_TOKEN }}"
        assert line_step["env"]["LINE_USER"] == "${{ secrets.LINE_USER_ID }}"
        assert "Skipping LINE notification" in line_step["run"]
        assert "exit 0" in line_step["run"]

    def test_判定できなかったときも赤くする(self) -> None:
        """fail-open の直し（2026-09-09）。

        probe ステップは curl の失敗をログに残すため `set +e` していて、エラー伝播が
        切れている。そのため「停止を検知したのに outputs を書けなかった」場合に
        ジョブが緑で終わる穴があった＝監視が黙る。最終ステップを always() で必ず走らせ、
        down が true/false のどちらでもないときも exit 1 することで塞ぐ。
        """
        steps = _yaml(SITE_DOWN_WATCH)["jobs"]["probe"]["steps"]
        guard = steps[-1]
        assert guard["if"] == "always()", "番人が always() でないと probe が死んだ瞬間に黙る"
        run = guard["run"]
        # down が空（＝判定できなかった）でも参照できるように env で受けていること
        assert guard["env"]["DOWN"] == "${{ steps.probe.outputs.down }}"
        # true / それ以外（*）の両方で exit 1 する＝緑になるのは false のときだけ
        assert run.count("exit 1") >= 2
        assert "*)" in run
        assert "判定できませんでした" in run

    def test_200でも中身が空なら緑にしない(self) -> None:
        """ワークフロー名（利用者にデータが出ていません）と判定を一致させる。

        200 + {"ok":true,"rows":[]} は「収集だけ止まって Supabase は生きている」形で、
        2026-09-06 07:00 に実際に起きた。HTTP だけ見ていると素通りする。
        """
        run = _yaml(SITE_DOWN_WATCH)["jobs"]["probe"]["steps"][0]["run"]
        assert ".ok == true" in run
        assert ".rows" in run
        # 判定は「200 かつ 本文OK」の連言であること（片方だけで緑にしない）
        assert '[ "$CODE" = "200" ] && [ "$REASON" = "OK" ]' in run

    def test_停止中の通知を増幅させない(self) -> None:
        """通知の間引き（2026-09-09）。

        停止が続く間、発火のたびに LINE + Slack/Discord + GitHub失敗メールが鳴る。
        30分毎のままだと3日半で約500通になり、事故を埋もれさせた49通を上回る。
        cron を毎時へ落とし、さらに LINE だけを約6時間に1回へ絞る
        （LINE はブログ承認フローと同じチャネルなので、障害中に承認が埋まる）。
        """
        doc = _yaml(SITE_DOWN_WATCH)
        crons = [c["cron"] for c in doc["on" if "on" in doc else True]["schedule"]]
        assert crons == ["17 * * * *"], "毎時であること（*/30 は通知が多すぎる）"

        steps = doc["jobs"]["probe"]["steps"]
        line_run = next(s for s in steps if "LINE" in (s.get("name") or ""))["run"]
        # 状態を持たない最も単純な間引き: 実行時刻の UTC 時で送信枠を決める
        assert "HOUR_UTC % 6" in line_run
        assert "date -u" in line_run

    def test_キャッシュの効き方について嘘を書かない(self) -> None:
        """リクエストの Cache-Control は Vercel のエッジキャッシュをバイパスしない。

        以前は `-H 'Cache-Control: no-cache'` を付けたうえで、コメントが
        「素通しで見ている」と読めた。ヘッダを外し、なぜ CDN 越しのままでよいのか
        （成功応答の s-maxage=240 + swr=300 ＝ 最長9分強しか古くならない）を書いた。
        """
        text = SITE_DOWN_WATCH.read_text(encoding="utf-8")
        assert "-H 'Cache-Control: no-cache'" not in text
        assert "s-maxage=240" in text


class Test監視3本のワークフローが原因を優先して出す:
    """cause が埋まっていれば固定文（ハズレの原因）を出さないこと。"""

    CASES = {
        "check-collection-heartbeat.yml": "check-heartbeat",
        "check-daily-published.yml": "check-published",
        "check-weekly-published.yml": "check-published",
    }

    def test_custom_bodyはcauseを先に見る(self) -> None:
        for filename, job in self.CASES.items():
            doc = _yaml(WORKFLOWS / filename)
            body = doc["jobs"]["notify"]["with"]["custom_body"]
            assert f"needs.{job}.outputs.cause ||" in body, filename
            assert f"needs.{job}.outputs.detail" in body, filename

    def test_causeがjob_outputsに公開されている(self) -> None:
        for filename, job in self.CASES.items():
            doc = _yaml(WORKFLOWS / filename)
            assert doc["jobs"][job]["outputs"].get("cause"), filename
