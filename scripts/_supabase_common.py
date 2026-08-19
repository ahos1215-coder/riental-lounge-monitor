"""Supabase の設定読み込み・認証ヘッダ・Storage オブジェクト GET/PUT の共有ヘルパー。

公開名は `load_env` / `supabase_conf` / `auth_headers` / `storage_get` / `storage_put`。
`_load_env` / `_supabase_conf` / `_auth_headers` は同じ関数への旧別名（既存の import を
壊さないために残しているだけ。新規に書くコードは `_` の付かない公開名を使う）。

`supabase_conf`（SUPABASE_URL / SERVICE_ROLE_KEY の環境変数解決）と
`load_env`（.env / .env.local の手動パーサ）は scripts/ 配下に verbatim で
コピペされていたものの一本化。実環境変数（GitHub Actions secrets 等）が
.env ファイルより優先される（setdefault）。
※ scripts/train_ml_model.py だけは `load_dotenv(..., override=True)` の別実装で、
   .env.local がプロセス環境変数に勝つ逆仕様（同ファイル内の注記を参照）。

`auth_headers`（apikey + Authorization）は scripts/ 配下15箇所に手書きコピーされていた。
「片方が欠けて 401」という事故を1箇所で防ぐため、Flask 側 `oriental/clients/supabase.py`
の `auth_headers` と**同じシグネチャ**（`accept_json` / `content_type` の任意フラグ）で
ここにも置く。2つのモジュールが存在するのは、scripts/ が oriental パッケージ（flask 等）を
import できない最小依存環境でも動く必要があるため。挙動は
tests/test_scripts_auth_headers_ssot.py が両者一致で固定する。

`storage_get` / `storage_put`（Storage オブジェクトの読み書き）は
score_forecasts.py / build_templates.py / snapshot_forecasts.py /
analytics_weekly_report.py の4本に手書きされ、2026-08-18 の Supabase 飽和事故
（存在するオブジェクトにも HTTP 544 / 429 が返る）への再試行追加がそのうち2本にしか
入らなかった。「Storage の読み書きが失敗したときに何が起きるか」を1箇所で読めるよう
ここへ集約する（次に同種の事故が起きたとき、直す場所が1つになる）。

REST（`/rest/v1/logs`）の fetch/paging はスクリプトごとにクエリも完全性要件も
異なるため、ここでは統合しない。

トップレベルスクリプトとして `python scripts/x.py` 実行される前提（パッケージ化しない）
なので、他の scripts/ 内モジュール（例: commentary_quality_gate.py）と同じ規約で、
呼び出し側が `sys.path.insert(0, <自分のディレクトリ>)` した上で
`from _supabase_common import ...` のようにベアインポートする。
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 同じ scripts/ ディレクトリの _retry_common.py（バックオフ計算）をベアインポートする。
# このモジュール自体が `scripts._supabase_common` としてもベア `_supabase_common` としても
# import されうるので、探索パスは自分で確実に通す。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _retry_common import backoff_delay, is_retryable_status  # noqa: E402

# Storage の既定値（旧実装の値をそのまま踏襲）。
STORAGE_GET_RETRIES = 6      # score/build 版の再試行回数
STORAGE_GET_BACKOFF_CAP = 30  # min(2**attempt, 30) 秒
STORAGE_GET_TIMEOUT = 60
STORAGE_PUT_RETRIES = 3      # snapshot 版の再試行回数
STORAGE_PUT_TIMEOUT = 30

# Supabase Storage が「オブジェクトが無い」を HTTP 400 のボディで伝えてくるときの目印
# （小文字化した本文に対する部分一致）。
# ★鏡像注意★ oriental/clients/supabase.py の NOT_FOUND_BODY_MARKERS と同一。片方を
# 変えたら必ず両方直すこと（片方だけ直すと「テンプレ/スナップショットが無い」の誤判定が
# 片系統だけに残り、2026-08-18 の事故と同じ見えにくい壊れ方をする）。
# 両者の一致は tests/test_storage_not_found_markers.py が固定する。
NOT_FOUND_BODY_MARKERS = ("not_found", "not found", "object not found")


def load_env() -> None:
    """.env / .env.local を読み込み os.environ に setdefault する。

    実環境変数（GitHub Actions secrets 等）が最優先。
    scripts/local_report_job.py（旧 `_load_env`）/ scripts/backup_logs.py の
    `_load_env` と同一の手動パーサ。
    """
    for name in (".env", ".env.local"):
        p = REPO_ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def supabase_conf() -> tuple[str, str] | None:
    """SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY（フォールバック: SUPABASE_SERVICE_KEY）
    を解決する。どちらか欠けていれば None。

    scripts/generate_weekly_insights.py と scripts/local_report_job.py の
    旧 `_supabase_conf` と同一の探索順（キー自体は返り値以外に出力しない）。
    """
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )
    if not base or not key:
        return None
    return base, key


def _storage_endpoint(bucket: str, path: str, url: str) -> str:
    return f"{url}/storage/v1/object/{bucket}/{path}"


def auth_headers(
    key: str, *, accept_json: bool = False, content_type: bool = False
) -> dict[str, str]:
    """Supabase REST / Storage 共通の認証ヘッダ。

    service role key は `apikey` と `Authorization: Bearer` の両方に必要
    （どちらか片方だけだと PostgREST / Storage が 401 を返す）。

    Flask 側の `oriental/clients/supabase.py::auth_headers` と同シグネチャ・同結果。
    scripts/ は oriental パッケージ（flask 等）を import できない最小依存環境でも
    動く必要があるため、実装は意図的に2箇所ある（一致は
    tests/test_scripts_auth_headers_ssot.py が固定）。
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if accept_json:
        headers["Accept"] = "application/json"
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


# ---- 旧 private 名（既存 import の互換のために残す別名。新規コードは公開名を使う）----
_load_env = load_env
_supabase_conf = supabase_conf
_auth_headers = auth_headers


def storage_get(
    bucket: str,
    path: str,
    url: str,
    key: str,
    retries: int = STORAGE_GET_RETRIES,
    *,
    log_prefix: str = "[storage]",
) -> bytes | None:
    """Storage オブジェクトを読む。404/400(not_found) は None、飽和系(429/5xx)は再試行。

    2026-08-18: Supabase Storage はオブジェクトのメタデータを同じ Postgres 上の
    `storage.objects` に持つため、DB が混雑すると存在するオブジェクトに対しても
    HTTP 544 (database_timeout) や 429 (too_many_connections) を返す。再試行が無いと
    「no snapshot for <date>（採点対象なし）」という本来の分かりやすい終了ではなく
    生のトレースバックで落ちる（build_templates は main() の最初のネットワーク呼び出しが
    ここなので、9回連続で即死していた）。

    401/403 のような恒久エラーは再試行せずそのまま送出する。

    再試行の対象は `_retry_common.is_retryable_status`（429 と 5xx）。Flask 側
    `oriental/clients/http.py` は同じ Supabase を叩きながら **500 を再試行しない**
    （2026-08-18 決定）。方針が逆である理由は `_retry_common.is_retryable_status` の
    docstring を参照。
    """
    req = urllib.request.Request(_storage_endpoint(bucket, path, url), headers=auth_headers(key))
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=STORAGE_GET_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            # Storage は存在しないオブジェクトに対し HTTP 400 + body {"error":"not_found",...}
            # を返すことがある（初回でスナップショット/サマリが未作成のケース）。これは「無い」扱い。
            if exc.code == 400:
                try:
                    body = exc.read().decode("utf-8", "replace").lower()
                except Exception:  # noqa: BLE001
                    body = ""
                if any(marker in body for marker in NOT_FOUND_BODY_MARKERS):
                    return None
            # 429 / 5xx（544 DatabaseTimeout を含む）は一時的な飽和 → 再試行
            # （判定は _retry_common.is_retryable_status が単一ソース。真理値は従来と同一）
            if not is_retryable_status(exc.code):
                raise
            last_err = exc
        except Exception as exc:  # noqa: BLE001 - transient network error
            last_err = exc
        if attempt < retries:
            wait = backoff_delay(attempt, cap=STORAGE_GET_BACKOFF_CAP)
            print(
                f"{log_prefix} storage GET {path} transient error ({last_err}); "
                f"retry {attempt}/{retries} in {wait:.0f}s"
            )
            time.sleep(wait)
    raise last_err if last_err else RuntimeError(f"storage get failed: {path}")


def storage_put(
    bucket: str,
    path: str,
    payload: bytes,
    url: str,
    key: str,
    retries: int = STORAGE_PUT_RETRIES,
    *,
    log_prefix: str = "[storage]",
) -> None:
    """Storage オブジェクトを書く（x-upsert）。429/5xx・ネットワーク断は再試行する。

    ここが1発で落ちるとその回の成果物（夜次スナップショット・スコア・テンプレ）を
    丸ごと失い、後続ジョブが動けなくなる。401/403/404 のような恒久エラーは
    再試行しても無駄なので即座に送出する。
    待機式は線形 `3*attempt` 秒（snapshot_forecasts.py の既存実装をそのまま踏襲）。
    """
    headers = {
        **auth_headers(key),
        "x-upsert": "true",
        "Content-Type": "application/json",
    }
    endpoint = _storage_endpoint(bucket, path, url)
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
        try:
            urllib.request.urlopen(req, timeout=STORAGE_PUT_TIMEOUT)
            return
        except urllib.error.HTTPError as exc:
            if not is_retryable_status(exc.code) or attempt >= retries:
                raise
            print(f"{log_prefix} PUT {path} failed (HTTP {exc.code}), retry {attempt}/{retries - 1}")
        except Exception as exc:  # noqa: BLE001 - URLError/timeout など
            if attempt >= retries:
                raise
            print(f"{log_prefix} PUT {path} failed ({str(exc)[:120]}), retry {attempt}/{retries - 1}")
        # 意図的に線形（3, 6 秒）。GET 側の指数バックオフ（backoff_delay）と違い、PUT は
        # 試行3回で終わるうえ「その回の成果物を落とさない」ことが目的なので、待ちを
        # 短く保つ旧 snapshot_forecasts.py の式をそのまま維持する（待ち秒は変えない）。
        time.sleep(3 * attempt)
