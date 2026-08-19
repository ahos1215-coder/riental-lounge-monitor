#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ローカル LLM（Ollama）呼び出しと facts 取得の共通実装。

ここが「本番の日次/週次レポートがローカル LLM をどう叩くか」の唯一の正本:
  - 使うモデル名（`MODEL`）
  - Ollama のエンドポイント（`OLLAMA_URL`）と共通の呼び出し方（`run_ollama` / `unload_ollama`）
  - レポート本文用の事実ブロック（`fetch_store_facts` / `facts_block`）と SYSTEM プロンプト

利用者:
  - scripts/local_report_job.py（日次・Task Scheduler 18:00 / 21:30）
  - scripts/generate_weekly_insights.py（週次・Task Scheduler 水曜 06:30）
  - scripts/experiments/local_llm_spike.py ほか実験系（ここから import して使う）

もともとこの中身は scripts/experiments/local_llm_spike.py にあり、本番の日次ジョブが
「実験用ファイル」を import する形になっていた（消してよいファイルだと誤解される配置）。
2026-08-19 の整理で、本番が使う部分だけをこのファイルへ移した。

標準ライブラリのみに依存する（GHA の最小環境・オーナーPC どちらでも動くこと）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

# ---- 設定 -----------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434"
# 本番の日次/週次レポートが使うモデル。ここが唯一の正本
# （2026-07-08 に gemma4:12b -> gemma4:e4b。当時は日次と週次で別々に直す羽目になった）。
MODEL = "gemma4:e4b"
BACKEND = "https://riental-lounge-monitor.onrender.com"
NUM_CTX = 8192
TIMEOUT_SEC = 360


def _get_json(url: str, timeout: int = 25, retries: int = 1, backoff_base: float = 2.0):
    """GET して JSON デコードする。

    retries>1 を指定すると、一時的な失敗（タイムアウト・接続エラー・5xx 等の
    urlopen 例外全般）を指数バックオフ（backoff_base * 2^(試行-1) 秒）で再試行し、
    全試行が失敗した場合のみ最後の例外を送出する。既存呼び出し元（check_ollama 等）は
    retries=1（既定）のままなので 1 発勝負で従来どおり変化しない。

    2026-07-16 21:30 の日次レポート障害（CONFIRMED BUG #2: backend のメモリイベントに
    起因する一時的なタイムアウトで facts 取得が失敗し、42 店中 1 店しか生成できなかった）
    を受けて、fetch_store_facts がこの retries 機構を使うよう変更した。
    """
    req = urllib.request.Request(url, headers={"User-Agent": "megribi-spike"})
    last_exc: Exception | None = None
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                sleep_sec = backoff_base * (2 ** (attempt - 1))
                print(
                    f"[facts-fetch] attempt {attempt}/{attempts} failed for {url}: {exc}; "
                    f"retrying in {sleep_sec:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(sleep_sec)
    assert last_exc is not None
    raise last_exc


# 2026-07-16 21:30 障害（CONFIRMED BUG #2）: backend がメモリイベント直後で一時的に
# 詰まっていたため、facts 取得（megribi_score / forecast_today）が単発 25s タイムアウトで
# 失敗し、sample(fallback) 化 -> local_report_job.py 側で公開停止、という連鎖が起きた。
# facts 取得だけタイムアウトを延ばし・指数バックオフで再試行して一時的な劣化を吸収する。
FACTS_FETCH_TIMEOUT_SEC = 45
FACTS_FETCH_RETRIES = 3


def fetch_store_facts(slug: str) -> dict:
    """megribi_score(最新の混雑/男女比) + forecast_today(今夜のピーク予測) から
    レポート用の facts を組み立てる。失敗時はサンプルにフォールバック。

    各エンドポイントは FACTS_FETCH_RETRIES 回まで・FACTS_FETCH_TIMEOUT_SEC 秒/回で
    再試行する（#2: backend の一時的なメモリイベント degradation を吸収するため）。
    """
    facts = {"slug": slug, "source": "live"}
    try:
        ms = _get_json(
            f"{BACKEND}/api/megribi_score?stores={slug}",
            timeout=FACTS_FETCH_TIMEOUT_SEC,
            retries=FACTS_FETCH_RETRIES,
        )
        row = next((d for d in (ms.get("data") or []) if d.get("slug") == slug), None)
        if row:
            facts["megribi_score"] = row.get("score")
            facts["occupancy_rate"] = row.get("occupancy_rate")
            facts["female_ratio"] = row.get("female_ratio")
            facts["latest_total"] = row.get("total")
            facts["men_seat_pct"] = row.get("men_seat_pct")
            facts["women_seat_pct"] = row.get("women_seat_pct")
            # 「いつの実測か」を本文で言えるようにするための時刻（同一レスポンス内の値なので
            # 追加のAPI呼び出しは発生しない）。ISO文字列から HH:MM だけを取り出す。
            ts = row.get("ts") or ""
            if isinstance(ts, str) and len(ts) >= 16:
                facts["latest_ts"] = ts[11:16]
    except Exception as e:  # noqa: BLE001
        facts["megribi_error"] = str(e)
    try:
        fc = _get_json(
            f"{BACKEND}/api/forecast_today?store={slug}",
            timeout=FACTS_FETCH_TIMEOUT_SEC,
            retries=FACTS_FETCH_RETRIES,
        )
        data = fc.get("data") or []
        pts = [(p.get("ts", ""), float(p.get("total_pred", 0) or 0)) for p in data]
        if pts:
            peak_ts, peak_val = max(pts, key=lambda x: x[1])
            facts["forecast_peak_total"] = round(peak_val, 1)
            facts["forecast_peak_time"] = peak_ts[11:16] if len(peak_ts) >= 16 else peak_ts
            facts["forecast_points"] = len(pts)
    except Exception as e:  # noqa: BLE001
        facts["forecast_error"] = str(e)
    # 何も取れなければサンプル
    if "megribi_score" not in facts and "forecast_peak_total" not in facts:
        facts["source"] = "sample(fallback)"
        facts.update({
            "megribi_score": 0.62, "occupancy_rate": 0.48, "female_ratio": 0.44,
            "latest_total": 22, "forecast_peak_total": 30.0, "forecast_peak_time": "22:30",
        })
    return facts


def _pct(value: object) -> str | None:
    """0-1 の割合を『約NN%』の文字列にする。数値でなければ None。"""
    try:
        return f"約{round(float(value) * 100)}%"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def facts_block(facts: dict, label: str, brand: str = "oriental") -> str:
    """LLM に渡す事実ブロックを組み立てる。ブランドで渡す指標を変える。

    2026-08-19 の監査 (所見2) を受けての設計:
      - オリエンタル (ol_*) は定員を一律 80 人と決め打ちした推定のため、
        `occupancy_rate`（席の埋まり具合）と `megribi_score` が構造的に誤る。
        オーナー判断で UI からも非表示にしてある指標なので
        （frontend/src/lib/featureFlags.ts の SHOW_MEGRIBI_JUDGMENTS=false）、
        LLM にも渡さない。渡すのは実測人数・時刻・今夜のピーク予測だけ。
      - 相席屋 (ay_*) は capacity が実値なので席の埋まり具合(%)は渡してよい。
        ただし人数は内部の逆算推定値なので渡さない（%表示のみが正式仕様）。
      - `megribi_score` はどちらのブランドにも渡さない。0〜1 の内部スコアであり、
        『狙い目かどうか』という判定そのものが現在は無効化されているため。
    """
    is_aisekiya = brand == "aisekiya"
    lines = [f"【{label}】"]

    def add(k, name, suffix=""):
        if facts.get(k) is not None:
            lines.append(f"- {name}: {facts[k]}{suffix}")

    if is_aisekiya:
        seat = _pct(facts.get("occupancy_rate"))
        if seat:
            lines.append(f"- 現在の席の埋まり具合: {seat}")
        add("men_seat_pct", "男性席の埋まり具合", "%")
        add("women_seat_pct", "女性席の埋まり具合", "%")
    else:
        add("latest_total", "直近の来店人数(実測・人)")
        add("forecast_peak_total", "今夜のピーク予測(人)")

    add("latest_ts", "直近データの時刻")
    if not is_aisekiya:
        # 相席屋には男女別の席の埋まり具合を既に渡している。似た数字（来店者に占める
        # 女性の割合 / 女性席の埋まり具合）を2つ並べるとLLMが取り違えるので渡さない。
        female = _pct(facts.get("female_ratio"))
        if female:
            lines.append(f"- 女性の割合: {female}")
    add("forecast_peak_time", "ピーク予測時刻")
    lines.append(f"- データ出典: {facts.get('source')}")
    return "\n".join(lines)


SYSTEM = (
    "あなたは日本のナイトライフ情報メディア『めぐりび』の編集者です。"
    "相席ラウンジの混雑データをもとに、来店を検討する一般ユーザー向けに書きます。"
    "初めて読む人がさっと一読しただけで分かるよう、やさしい普段の言葉で簡潔に書きます。"
    "『めぐりびスコア0.08』『埋まり具合0.075』のような内部指標や 0〜1 の生の数値は本文に出さず、"
    "渡されたデータにある人数・割合・時刻を、そのまま普段の言葉で述べます。"
    "渡されたデータに無い『空いています』『混んでいます』『ほぼ満席』のような混雑の断定はしません。"
    "使う数字は、時刻(例: 23時ごろ)やおおよその人数・割合など、誰でも直感的に分かるものだけにします。"
    "誇張せず、データに無い事柄（予約の可否・待ち時間・特典など）には言及しません。"
    "出力は Markdown。1行目を『# 見出し』にし、その後に本文。前置き・言い訳・メタ発言は書かない。"
)


def run_ollama(model: str, system: str, user: str, options: dict | None = None,
               think: bool | None = None, keep_alive: str | int = 0,
               format: dict | None = None) -> tuple[str, float, str]:  # noqa: A002
    """Ollama /api/chat を叩く。返り値 (text, elapsed_sec, error)。

    options: 既定 (num_ctx=NUM_CTX, temperature=0.7) に上書きマージする追加オプション。
    tune_local_llm.py の計測結果 (例: num_ctx=2048 + num_gpu=999 で 13.7→24.8 tok/s) を
    呼び出し側から注入するために使う。
    think: reasoning モードの明示切替 (gemma4 等 thinking 対応モデル用)。None=モデル既定。
    レポート用途は think=False 推奨 (推論不要。ON だと思考で数千トークン消費し遅く・発熱増)。
    keep_alive: モデルのメモリ常駐時間。0=生成後すぐアンロード(既定・実験用)。
    バッチ処理では "10m" 等にして全店の間ロードを維持し、1店ごとの再ロード(8-11s)を無くす
    (終了時は unload_ollama() で明示解放すること)。
    format: Ollama の構造化出力 (JSON スキーマ強制)。**必ずボディのトップレベル**に置く。
    options に混ぜると Ollama 側に黙って無視され、小型モデルがキー名を誤字る事故
    (例: last_week_summaary) が復活するので注意 (週次コメンタリーが依存している)。"""
    opts: dict = {"num_ctx": NUM_CTX, "temperature": 0.7}
    if options:
        opts.update(options)
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "keep_alive": keep_alive,
        "options": opts,
    }
    if think is not None:
        body["think"] = think
    if format is not None:
        body["format"] = format
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            d = json.loads(r.read().decode("utf-8"))
        text = (d.get("message") or {}).get("content", "")
        return text, time.time() - t0, ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return "", time.time() - t0, f"HTTP {e.code}: {body}"
    except Exception as e:  # noqa: BLE001
        return "", time.time() - t0, str(e)


def unload_ollama(model: str) -> None:
    """モデルを即アンロードして VRAM を解放する (keep_alive:0 の空生成)。best-effort。
    keep_alive>0 でバッチ実行した後、ラン終了時に呼んで GPU を音楽PJ等へ明け渡す。"""
    try:
        payload = json.dumps({"model": model, "keep_alive": 0, "prompt": ""}).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception:  # noqa: BLE001
        pass


def check_ollama() -> list[str]:
    try:
        d = _get_json(f"{OLLAMA_URL}/api/tags", timeout=10)
        return [m.get("name", "") for m in (d.get("models") or [])]
    except Exception:
        return []


def check_backend_health(timeout: int = 10) -> dict:
    """backend の /healthz を一度だけ覗く（リトライ無し・ベストエフォート）。

    local_report_job.py がバッチ開始前に呼び、`memory.rss_mb`（oriental/routes/health.py
    が返す RSS 実測値）が閾値を超えていれば「backend がメモリイベントで劣化しているかも
    しれない」とみなし、生成を始める前に短く待つ判断に使う（#2 由来）。
    到達不可・タイムアウト・JSON 以外の応答はすべて空 dict を返す（呼び出し側は
    「健全性は分からない」として続行してよい設計。診断のためだけにバッチ全体を
    止めたくない）。
    """
    try:
        return _get_json(f"{BACKEND}/healthz", timeout=timeout)
    except Exception:  # noqa: BLE001
        return {}
