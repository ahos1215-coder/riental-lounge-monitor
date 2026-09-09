from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from ..clients.supabase import auth_headers
from ..config import AppConfig
from ..utils import timeutil
from ._cache import SingleFlightTTLCache
from .common import forecast_model_status as _forecast_model_status
from .common import get_config as _config

bp = Blueprint("health", __name__)

# ---------------------------------------------------------------------------
# 2026-09-09 Supabase egress 枯渇事故（3日半、誰も「壊れている」と気づけなかった）を受けた改修。
#
# 何が起きたか: Supabase が全リクエストに HTTP 402 を返し、収集・予測・日報が全滅した。
# それでも `/healthz` は `{"ok": true}` を HTTP 200 で返し続けたため、外形監視5経路すべてが
# 3日間ずっと緑だった。旧実装が `payload = {"ok": True, ...}` と **真偽値を定数で埋めていた**
# ことが直接の原因（中身が全滅していても ok は true）。
#
# 方針:
#   - `ok` を**診断結果**にする（本当に壊れていれば false）。壊れている中身は
#     `problems`（機械可読なコード配列）と `problem_detail`（通知本文にそのまま貼れる一文）で返す。
#   - **HTTP ステータスは 200 のまま**にする（理由は healthz() の docstring）。
#   - 上流(Supabase)の失敗は 402/401/403 のような課金・認証起因と、単なる到達不能・タイムアウトを
#     `data_freshness.reason` / `upstream_status` で区別できるようにする。監視側が
#     「原因が一文字も載らない失敗メール」ではなく原因そのものを通知本文に書けるようにするため。
# ---------------------------------------------------------------------------

# このモジュールは `oriental/__init__.py` の import 時（= プロセス起動時）に読まれるので、
# ここでの時刻はプロセス起動時刻の実用的な近似になる。gunicorn が --max-requests で
# worker を再生成した場合も、新しい worker は新しいプロセス＝この値も取り直される。
_PROCESS_START_UNIX = time.time()

# 起動直後は preload スレッドがまだ42店を読み終えていないのが正常。この猶予を過ぎても
# 1店もロードできていなければ「本当に壊れている」と見なす（今回の 402 事故はこの状態が永続した）。
_DEFAULT_MODEL_GRACE_SEC = 300.0

# 収集ウィンドウ(既定 JST 19:00-05:00)の外は新規データが無くて当然なので通常の stale 判定は
# 効かない。その盲点を塞ぐための「窓に関係なく明らかに古い」しきい値。
# 正常時の最大経過は「05:00 に収集終了 → 19:00 に再開」の約14時間なので、24時間なら
# 正常運用では絶対に踏まない。今回の事故（9/6 07:00 に収集停止・以後恒久欠損）は
# 昼の時間帯でもここで赤くなる。
_DEFAULT_MAX_DATA_AGE_SEC = 86400.0

# `/healthz` はレート制限の対象外（routes/common.py の除外接頭辞）。そのまま毎リクエスト
# Supabase へ問い合わせると、healthz を連打するだけで上流問い合わせと worker スレッドを
# 増幅できてしまう（しかも egress を食う）。短い TTL で1本にまとめる。
# 監視は5分間隔なので 30 秒の遅延は検知時間に影響しない。0 で無効化できる。
_DEFAULT_FRESHNESS_TTL_SEC = 30.0

_FRESHNESS_CACHE_KEY = "logs_latest_ts"


def _env_float(name: str, default: float) -> float:
    """env を float で読む（未設定・不正値は default）。

    `oriental/ml/_num.py::env_float` と同じ意味だが、あちらは numpy / pandas を
    import する。`/healthz` は ENABLE_FORECAST=0 でも、ML が壊れていても答えられる
    必要がある「最後の砦」なので、重い依存を増やさずここで完結させる。
    """
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _short(value: object, limit: int = 160) -> str:
    """通知本文に載せる用に1行へ潰して切り詰める。"""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


@bp.get("/healthz")
def healthz():
    """稼働確認（liveness）。**常に HTTP 200 を返し、良し悪しは body の `ok` で伝える。**

    非200 にしない理由（2026-09-09 に呼び出し元を調べたうえでの判断）:
      1. `/healthz` は UptimeRobot の monitor #1 が5分間隔で叩いている（plan/STATUS.md の
         監視表）。主目的は Render のコールドスタート回避＝**暖機**であり、暖機の口が
         非200を返し始めても得るものが無い。
      2. **Render のヘルスチェック設定はダッシュボード側にあり、このリポジトリからは
         確認できない**（`render.yaml` は存在しない）。`/healthz` が指定されている可能性を
         否定できず、非200 にするとインスタンスが unhealthy と判定されて再起動／デプロイ失敗に
         なり得る。「監視を正直にする」ために本番を落としては本末転倒なので、
         確信が持てない側（＝200維持）を選ぶ。
      3. HTTP ステータスで落としたい用途にはすでに `/readyz`（壊れていれば 503）がある。

    `/readyz` との役割分担:
      - `/healthz` … プロセスが応答するか＋**何が壊れているかの診断書**。常に 200。
        監視は本文の `ok` / `problems` / `problem_detail` を読むこと。
      - `/readyz`  … いま実トラフィックをさばける状態か。**自然復旧しない原因**で壊れて
        いれば 503（一過性の上流失敗では 503 にしない。`_READYZ_BLOCKING_CODES` 参照）。
        ロードバランサ／切り離し判断用で、起動直後（モデル未ロード）も 503 になる。
    """
    cfg = _config()
    forecast_model = _forecast_model_status()
    data_freshness = _data_freshness(cfg)
    issues = _diagnose(cfg, forecast_model, data_freshness)

    payload = {"ok": not issues, **cfg.health_summary()}
    payload["forecast_model"] = forecast_model
    payload["data_freshness"] = data_freshness
    payload["memory"] = _memory_status()
    payload["api_rate_limit"] = _rate_limit_status()
    payload["problems"] = [code for code, _detail in issues]
    payload["problem_detail"] = _problem_detail(issues)
    if issues:
        # 200 を返す以上、ログにだけは必ず理由を残す（Render のログから追える）。
        current_app.logger.warning("health.not_ok %s", payload["problem_detail"])
    return jsonify(payload)


def _diagnose(
    cfg: AppConfig, forecast_model: dict, data_freshness: dict
) -> list[tuple[str, str]]:
    """「本当に壊れている」条件を1箇所で判定する（`(コード, 説明)` の配列）。

    ここに入れるのは**利用者に誤情報が出る／データが失われる**レベルのものだけ。
    メモリ逼迫のような予兆は `memory` ブロックとログに出すだけで `ok` は倒さない
    （倒すと「常に赤い監視」になり、また誰も見なくなる）。
    """
    issues: list[tuple[str, str]] = []

    if _should_judge_forecast_model(cfg):
        if not forecast_model.get("loaded"):
            cause = (
                forecast_model.get("last_error")
                or forecast_model.get("note")
                or "no bundles loaded"
            )
            issues.append(
                ("forecast_model_not_loaded", f"予測モデルが1店もロードできていない ({_short(cause)})")
            )
        else:
            shortfall = _partial_model_load_detail(forecast_model)
            if shortfall:
                issues.append(("forecast_model_partially_loaded", shortfall))

    reason = data_freshness.get("reason")
    if reason == "upstream_error":
        status = data_freshness.get("upstream_status")
        message = data_freshness.get("upstream_message")
        # 402/401/403 は「課金枠の枯渇 or 資格情報の失効」で、放置しても自然復旧しない。
        # 5xx などの一時障害と区別できるようコードを分ける（通知の文面を変えられるように）。
        code = {
            402: "data_upstream_payment_required",
            401: "data_upstream_unauthorized",
            403: "data_upstream_forbidden",
        }.get(status if isinstance(status, int) else -1, "data_upstream_error")
        detail = f"Supabase /rest/v1/logs が HTTP {status}"
        if message:
            detail += f" ({message})"
        issues.append((code, detail))
    elif reason == "request_failed":
        issues.append(
            (
                "data_unreachable",
                f"Supabase へ問い合わせできない ({_short(data_freshness.get('upstream_message') or 'unknown')})",
            )
        )
    elif reason in ("no_rows", "no_ts"):
        issues.append(
            ("data_missing", "logs テーブルから最新行が取れない（0件、または ts が空）")
        )
    elif data_freshness.get("stale_hard"):
        issues.append(
            (
                "data_too_old",
                f"最新ログが古すぎる (age_sec={data_freshness.get('age_sec')}, latest_ts={data_freshness.get('latest_ts')})",
            )
        )
    elif data_freshness.get("stale"):
        issues.append(
            (
                "data_stale",
                f"収集ウィンドウ内なのに更新が止まっている (age_sec={data_freshness.get('age_sec')})",
            )
        )
    # reason が "not_configured" / "no_http_session" のときは**問題にしない**:
    # Supabase 資格情報を渡さないローカル実行・テストがこれに当たり、これで赤くすると
    # 「開発では常に赤い」＝また誰も見ない監視に戻る。
    return issues


def _problem_detail(issues: list[tuple[str, str]]) -> str:
    """通知本文にそのまま貼れる一文にまとめる（正常時は空文字）。"""
    return " / ".join(f"{code}: {detail}" for code, detail in issues)


def _should_judge_forecast_model(cfg: AppConfig) -> bool:
    """「モデル未ロード＝異常」と判定してよい状況か。

    次の3つのときは未ロードでも正常なので判定しない（誤検知でオオカミ少年にしないため）:
      - `ENABLE_FORECAST=0` … 予測機能を意図的に切っている。
      - `DISABLE_MODEL_PRELOAD=1` … preload を意図的に切っている＝遅延ロード運用。
        最初の予測リクエストが来るまでロードされていないのが正常（テストもこれ）。
      - プロセス起動から `HEALTH_MODEL_GRACE_SEC`(既定300秒) 以内 … preload スレッドが
        42店を読み終える前。ここを猶予しないと毎デプロイ直後に赤くなる。
    """
    if not cfg.enable_forecast:
        return False
    if os.getenv("DISABLE_MODEL_PRELOAD") == "1":
        return False
    grace = _env_float("HEALTH_MODEL_GRACE_SEC", _DEFAULT_MODEL_GRACE_SEC)
    return (time.time() - _PROCESS_START_UNIX) >= grace


def _expected_store_count() -> int:
    """ロードされているべき店舗数（= 店舗マスタの全店数）。取れなければ 0。

    `oriental/utils/stores.py` が単一ソース（CLAUDE.md §3）。ここで数を持たない
    （持つと新店追加のたびに二重管理になる）。import は関数内で行う: `/healthz` は
    「他が全部壊れていても答えられる最後の砦」なので、モジュール読み込み時の
    依存を1つでも増やさない（stores.py 自体は stdlib のみ・失敗しても [] を返す設計）。
    """
    try:
        from ..utils.stores import ALL_STORE_IDS

        return len(ALL_STORE_IDS)
    except Exception:  # noqa: BLE001 — 店舗マスタが読めないだけで /healthz を落とさない
        return 0


# 「何割ロードできていれば正常とみなすか」。既定 0.5（42店なら 21 店未満で異常）。
#
# なぜ「1店でも欠けたら異常」にしないか: 新規開店直後の店や学習データ不足の店は
# バンドルが存在しないのが正常で、42/42 を要求すると**常に赤い監視**になる。
# それは今回の事故（誰も監視を見なくなっていた）を再生産する。
# なぜ「1店でもあれば正常」（＝これまでの `loaded` 真偽値）で足りないか: `loaded` は
# バンドルが1つでもあれば True なので、42店中41店の preload が失敗しても ok:true のまま
# ＝ サイトのほぼ全店で予測が出ていないのに緑になる。
# 半分は「大半の店で予測が出ていない」と断言できる、議論の余地が少ない線として選んだ。
_DEFAULT_MIN_LOADED_STORE_RATIO = 0.5


def _partial_model_load_detail(forecast_model: dict) -> str | None:
    """「バンドルはあるが大半の店で欠けている」なら説明文、正常なら None。

    `loaded=True` だけを見ていると 41/42 失敗を取りこぼす（2026-09-09 レビュー）。
    判定できる材料が揃わないとき（店舗マスタが読めない・`loaded_store_count` が無い
    古い形の status）は**黙って正常扱い**にする。分からないことを異常として通知しない。
    """
    expected = _expected_store_count()
    loaded_count = forecast_model.get("loaded_store_count")
    if expected <= 0 or not isinstance(loaded_count, int) or isinstance(loaded_count, bool):
        return None
    ratio = _env_float("HEALTH_MIN_LOADED_STORE_RATIO", _DEFAULT_MIN_LOADED_STORE_RATIO)
    if loaded_count >= expected * ratio:
        return None
    return (
        f"予測モデルが大半の店でロードできていない "
        f"({loaded_count}/{expected} 店, 下限 {ratio:.0%})"
    )


def _rate_limit_status() -> dict:
    """`/api/*` レート制限の効きを外から観測できるようにする（2026-08-21）。

    本番で 400 連打しても 429 が出ない事象を、ログを見られない状態でも切り分けられるように
    した。連打の直後にこれを見て `tracked_keys` が 1 なら効いている（同じ IP を1バケットに
    まとめられている）、連打数と同じ勢いで増えていればキーの取り方が壊れている。
    """
    limiter = current_app.config.get("API_RATE_LIMITER")
    if limiter is None:
        return {"enabled": False}
    return limiter.status()


def _process_rss_mb() -> float | None:
    """現在プロセスの RSS を MB で返す。

    本番 Linux (Render) は `/proc/self/status` の VmRSS を読む（stdlib のみ・追加依存なし）。
    Windows 開発機ではベストエフォートで ctypes(GetProcessMemoryInfo) を試し、
    失敗・非対応環境では None を返す。/healthz は追加フィールドのみで、None でも
    `memory.rss_mb` キー自体は常に存在する（レスポンス形状は後方互換）。
    """
    # Linux 本番: /proc/self/status VmRSS（kB 表記）
    try:
        with open("/proc/self/status", "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(float(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    # Windows 開発機フォールバック（best-effort。失敗しても静かに None）
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / (1024.0 * 1024.0), 1)
    except Exception:  # noqa: BLE001 — 非 Windows / 取得失敗は None にフォールバック
        pass
    return None


def _memory_status() -> dict:
    """`/healthz` 用のメモリ観測。rss_mb が MEMORY_WARN_MB(既定350) を超えたら WARNING を出す。

    Render Starter は 1worker×8threads（既定 WEB_CONCURRENCY=1 / GUNICORN_THREADS=8、
    2026-07-17 メモリ成長事件#2以降の構成。Procfile 参照）で 512MB を使うため、
    プロセス RSS が 350MB を超えたら OOM 再発の予兆として監視ログに残す
    （fix/memory-budget）。

    なお RSS 逼迫は「予兆」であって「壊れている」ではないので、`ok` は倒さない
    （倒すと常時赤に近づき、本当の障害が埋もれる。実際 2026-09-09 の事故は
    「失敗メールの洪水に原因が埋もれた」ことが検知遅れの理由だった）。
    """
    rss_mb = _process_rss_mb()
    if rss_mb is not None:
        warn_mb = _env_float("MEMORY_WARN_MB", 350.0)
        if rss_mb > warn_mb:
            current_app.logger.warning(
                "health.memory_high rss_mb=%.1f warn_mb=%.1f", rss_mb, warn_mb
            )
    return {"rss_mb": rss_mb}


# `/readyz` が 503 を返してよい問題コード（＝**放置しても自然復旧しない**原因）。
#
# なぜ許可リスト方式なのか（2026-09-09 レビュー）: `/readyz` の 503 は、Render の
# ヘルスチェックがこれを見ている場合に**インスタンスの再起動＝サイト全落ち**を意味する
# （その設定はダッシュボード側にありリポジトリからは確認できない。healthz() の docstring 参照）。
# 「壊れているかもしれない」で落とすのではなく、「落として困らない・落とさないほうが困る」
# 原因だけを列挙する。
#   - 402/401/403 … 課金枠の枯渇・資格情報の失効。待っても直らず、このインスタンスは
#     どのみちデータを返せない。
#   - forecast_model_not_loaded … 暖まっていない/壊れた worker にトラフィックを送らない
#     （この endpoint の導入時からの挙動）。
#   - data_stale / data_too_old … 収集が止まっている。利用者に古い情報を出し続けるより
#     切り離したほうがよい。
#
# 逆に**除外**するもの（healthz では ok:false になるが readyz は ready のまま）:
#   - data_unreachable（reason=request_failed）… ネットワークの瞬断・タイムアウト。
#     `ConfiguredSession` は Retry(total=3, backoff=0.6) を持つので、**1回の瞬断でも
#     約24秒かけて必ずここに落ちる**。しかも結果は 30 秒 TTL キャッシュに乗るため、
#     瞬断1回で 503 が最大30秒続く。これで再起動されるとサイトが落ちる ——
#     「監視を正直にする」ために本番を落としては本末転倒（healthz が 200 を維持するのと同じ判断）。
#   - data_upstream_error（上流の 5xx など）… 同じく一過性。402/401/403 と違い待てば戻る。
#   - data_missing（logs が0件）… 異常ではあるが、このインスタンスを切り離しても他の
#     インスタンスで同じ結果になる。切り離しでは解決しないので 503 の意味が無い。
#   - forecast_model_partially_loaded … 半分未満でも「その店は予測が出ない」だけで、
#     ロード済みの店は正常にさばける。切り離すと**さばけていた分まで**止まる。
# いずれも `/healthz` の `ok:false` と `problems`、および `/readyz` の `problems`
# （下の payload は blocking かどうかに関わらず全件載せる）で監視には必ず届く。
_READYZ_BLOCKING_CODES = frozenset(
    {
        "forecast_model_not_loaded",
        "data_upstream_payment_required",
        "data_upstream_unauthorized",
        "data_upstream_forbidden",
        "data_stale",
        "data_too_old",
    }
)


@bp.get("/readyz")
def readyz():
    """Readiness: liveness の `/healthz` とは異なり、実際にトラフィックをさばける状態かを判定する。

    `/healthz` より**厳しい**: 起動直後の猶予も `ENABLE_FORECAST` も見ずに「予測モデルが
    1つも無ければ未 ready」とする（切り離し判断が目的なので、暖まっていない worker に
    トラフィックを送りたくない）。加えて `/healthz` と同じデータ層の異常のうち、
    **自然復旧しないもの**（上流の 402・401・403 / stale / 明らかに古い）でも 503 を返す。

    一過性の失敗（到達不能・上流 5xx）は `problems` には載せるが 503 にはしない。
    理由は `_READYZ_BLOCKING_CODES` のコメントを参照（要は、瞬断で本番を再起動させないため）。

    外部の uptime monitor 用の `/healthz` は warm-up 目的で常に 200 のまま維持する
    （そちらは body の `ok` と `problems` で良し悪しを伝える）。
    """
    cfg = _config()
    forecast_model = _forecast_model_status()
    data_freshness = _data_freshness(cfg)

    issues = _diagnose(cfg, forecast_model, data_freshness)
    codes = [code for code, _detail in issues]
    if not forecast_model.get("loaded") and "forecast_model_not_loaded" not in codes:
        # /healthz 側で猶予・設定により判定を見送ったケースでも、readyz は未ロードを未 ready 扱いにする
        # （導入前からの挙動を維持する。旧実装も loaded=False なら無条件に 503 だった）。
        issues = [*issues, ("forecast_model_not_loaded", "予測モデルが1店もロードできていない")]

    blocking = [(code, detail) for code, detail in issues if code in _READYZ_BLOCKING_CODES]
    ready = not blocking
    payload = {
        "ok": ready,
        "forecast_model": forecast_model,
        "data_freshness": data_freshness,
        # problems は「見つかった異常の全件」（一過性のものも含む＝ /healthz と同じ集合）。
        # blocking_problems は「そのうち 503 の根拠になったもの」。ok:true でも problems が
        # 空でないことがあり、それが正しい（一過性の失敗を観測しつつ、切り離しはしない）。
        "problems": [code for code, _detail in issues],
        "blocking_problems": [code for code, _detail in blocking],
        "problem_detail": _problem_detail(issues),
    }
    return jsonify(payload), 200 if ready else 503


def _freshness_result(**overrides) -> dict:
    """`data_freshness` ブロックを常に同じキー集合で返す（監視側がキーの有無を気にしないで済む）。"""
    base = {
        "available": False,
        "age_sec": None,
        "latest_ts": None,
        "stale": None,
        "stale_hard": None,
        "in_collection_window": None,
        # reason: ok / not_configured / no_http_session / upstream_error / request_failed / no_rows / no_ts
        "reason": None,
        "upstream_status": None,
        "upstream_message": None,
    }
    base.update(overrides)
    return base


def _upstream_message(resp) -> str | None:
    """上流のエラー応答から**既知のキーだけ**を短く取り出す。

    生ボディをそのまま載せない: HTML エラーページのノイズを避けるためと、上流が何を返すか
    分からない以上、想定外の内容を公開レスポンスへ素通しさせないため。Supabase の 402 は
    `{"message": "..."}` 形式なので、これで「課金枠の枯渇」という**原因そのもの**が
    通知本文に載る（2026-09-09 の事故では、原因が通知に一文字も載らなかったことが
    3日半の沈黙の一因だった）。

    候補キーは `message` / `msg` / `error` の3つだけに絞る（2026-09-09 レビュー）。
    以前は `error_description` / `code` / `hint` も拾っていたが、PostgREST の `hint` は
    「テーブル `logs` の列 `ts_utc` では？」のように**スキーマ（テーブル名・列名）を本文に
    含む**。`/healthz` は public・無認証・レート制限対象外なので、ここに載せた文字列は
    誰でも読める＝内部構造の無料の見取り図になる。`code` は PostgreSQL の SQLSTATE で、
    人間向けの原因説明としての情報量が無い割に同じリスクを持つ。
    """
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — JSON でない応答は本文を載せない
        return None
    if not isinstance(body, dict):
        return None
    for key in ("message", "msg", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return _short(value.strip())
    return None


def _freshness_cache() -> SingleFlightTTLCache | None:
    """`data_freshness` 用のプロセス内 TTL キャッシュ（app 単位。TTL<=0 で無効）。"""
    ttl = _env_float("HEALTH_FRESHNESS_TTL_SEC", _DEFAULT_FRESHNESS_TTL_SEC)
    if ttl <= 0:
        return None
    entry = current_app.config.get("HEALTH_FRESHNESS_CACHE")
    if entry is None or entry[0] != ttl:
        # モジュールグローバルにせず app.config に持たせる（テストで create_app() を
        # 何度作っても互いに干渉しない。routes/common.py の SUPABASE_PROVIDER と同じ流儀）。
        entry = (ttl, SingleFlightTTLCache(ttl, max_entries=4, wait_timeout=10.0))
        current_app.config["HEALTH_FRESHNESS_CACHE"] = entry
    return entry[1]


def _data_freshness(cfg: AppConfig) -> dict:
    """最新ログのタイムスタンプを Supabase から取得して鮮度情報を返す。

    外部監視ツールが `stale=true` / `stale_hard=true` / `reason` を見てアラートを上げられる。
    結果は数十秒 TTL でキャッシュする（`/healthz` はレート制限の対象外なので、
    毎リクエスト上流に問い合わせると連打で上流と egress を増幅できてしまうため）。
    キャッシュにより `age_sec` は最大 TTL 秒ぶん過小に出るが、しきい値は 1800 秒 /
    86400 秒なので判定には影響しない。
    """
    cache = _freshness_cache()
    if cache is None:
        return _probe_data_freshness(cfg)
    result, _status = cache.get_or_compute(
        _FRESHNESS_CACHE_KEY, lambda: (_probe_data_freshness(cfg), True)
    )
    return result


def _probe_data_freshness(cfg: AppConfig) -> dict:
    """実際に Supabase `logs` の最新1行を引いて鮮度を判定する（キャッシュなしの本体）。"""
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        # 資格情報が無い＝ローカル実行・テスト。異常ではないので problems には入らない。
        return _freshness_result(reason="not_configured")

    session = current_app.config.get("HTTP_SESSION")
    if session is None:
        return _freshness_result(reason="no_http_session")

    endpoint = cfg.supabase_url.rstrip("/") + "/rest/v1/logs"
    headers = auth_headers(cfg.supabase_service_role_key, accept_json=True)
    params = [("select", "ts"), ("order", "ts.desc"), ("limit", "1")]

    try:
        resp = session.get(endpoint, params=params, headers=headers, timeout=5)
        if not resp.ok:
            # ここが 2026-09-09 の事故で 402 を返していた場所。旧実装は available=False に
            # 潰すだけでステータスも理由も捨てており、監視は「不明」と「正常」を
            # 区別できなかった。
            return _freshness_result(
                reason="upstream_error",
                upstream_status=getattr(resp, "status_code", None),
                upstream_message=_upstream_message(resp),
            )
        rows = resp.json()
        if not rows:
            return _freshness_result(available=True, stale=True, reason="no_rows")
        latest_ts = rows[0].get("ts")
        if not latest_ts:
            return _freshness_result(available=True, stale=True, reason="no_ts")
        ts_fixed = latest_ts.replace("Z", "+00:00") if latest_ts.endswith("Z") else latest_ts
        dt = datetime.fromisoformat(ts_fixed)
        age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
        # 収集は設定された時間帯（デフォルト JST 19:00-05:00）の夜間のみ稼働する。
        # 閉店時間帯は新規データが無くて当然なので stale としない（従来は毎日
        # ~14h 誤って stale=true になっていた）。tasks_tick と同じ判定ロジックを使う。
        in_window, _start_dt, _end_dt = timeutil.collection_window(
            current=timeutil.now(cfg.timezone),
            start_hour=cfg.window_start,
            end_hour=cfg.window_end,
            tz_name=cfg.timezone,
        )
        # 30 分以上更新がなければ stale（ただし収集ウィンドウ内のみ）
        stale = in_window and age_sec > 1800
        # ウィンドウ判定の盲点（昼の時間帯は何日止まっていても stale にならない）を塞ぐ、
        # 窓に依存しない絶対しきい値。
        stale_hard = age_sec > _env_float("HEALTH_MAX_DATA_AGE_SEC", _DEFAULT_MAX_DATA_AGE_SEC)
        return _freshness_result(
            available=True,
            age_sec=age_sec,
            latest_ts=latest_ts,
            stale=stale,
            stale_hard=stale_hard,
            in_collection_window=in_window,
            reason="ok",
        )
    except Exception as exc:  # noqa: BLE001 — 到達不能・タイムアウト・壊れた応答すべて
        # **例外メッセージ本文（str(exc)）は載せない。型名だけにする**（2026-09-09 レビュー）。
        # requests の接続系例外は
        #   HTTPSConnectionPool(host='<project-ref>.supabase.co', port=443): ...
        #   Max retries exceeded with url: /rest/v1/logs?select=ts&order=ts.desc&limit=1
        # のように**上流のホスト名・REST のパス・クエリをそのまま文字列に含む**。
        # `/healthz` は public・無認証・レート制限対象外なので、これを載せると
        # 「誰でも叩ける口」に「枯渇させられる相手先」を書くことになる（今回の事故が
        # egress 枯渇である以上、特に筋が悪い）。
        # 型名（ConnectTimeout / ConnectionError / ReadTimeout …）だけで
        # 「到達不能なのか・遅いのか・応答が壊れているのか」の切り分けには足りる。
        # 完全な例外文字列が要るときは Render のログ（下の warning）を見ること。
        current_app.logger.warning(
            "health.freshness_request_failed %s", _short(f"{type(exc).__name__}: {exc}")
        )
        return _freshness_result(
            reason="request_failed",
            upstream_message=type(exc).__name__,
        )
