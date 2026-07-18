#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ローカルLLM 品質スパイク（go/no-go 用）

目的:
  Gemini API を置き換えるローカルLLM候補を、実データで「週次レポート」と
  「渋谷 vs 新宿 比較記事」の2タスクについて生成させ、横並びで目視比較する。

使い方（このファイルがあるリポジトリのルートで）:
  1) Ollama を入れて、モデルを pull しておく（初回のみ・別途手順参照）:
       ollama pull qwen3.5:4b
       ollama pull qwen3.5:9b
       ollama pull gemma4:12b
  2) 実行:
       python scripts/experiments/local_llm_spike.py
  3) 生成物は ./local_llm_spike_out/ に .md で保存される。エディタで読み比べる。

設計メモ:
  - 各モデルは keep_alive:0 で「生成後すぐアンロード」→ VRAM を次モデル/音楽PJに明け渡す
    （8GB共有・衝突させない運用に合わせる。3モデルを積み上げない）。
  - 実データはライブ backend から取得。取れなければ埋め込みサンプルにフォールバック
    （＝Ollama さえ動けばオフラインでも品質の当たりは見られる）。
  - 小型モデルに JSON 厳格出力は強制しない（フォーマット税回避）。本文＋見出しの質を見る。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from contextlib import nullcontext
from pathlib import Path

# 共有GPUロック（音楽PJと衝突しないための排他）。見つからなければロック無しで続行。
try:
    sys.path.insert(0, r"C:\Users\Public\共有データ系")
    import gpu_lock  # type: ignore
except Exception:  # noqa: BLE001
    gpu_lock = None

# ---- 設定（ここを編集すれば対象モデル/店舗を変えられる） --------------------
OLLAMA = "http://localhost:11434"
MODELS = ["qwen3.5:4b", "qwen3.5:9b", "gemma4:12b"]  # 質重視なら qwen3.5:4b-q8_0 等に差し替え可
BACKEND = "https://riental-lounge-monitor.onrender.com"
STORE_A = "shibuya"   # 週次レポート対象 & 比較の片方
STORE_B = "shinjuku"  # 比較のもう片方
NUM_CTX = 8192
TIMEOUT_SEC = 360
OUT_DIR = Path("local_llm_spike_out")

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


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


def facts_block(facts: dict, label: str) -> str:
    lines = [f"【{label}】"]
    def add(k, name, suffix=""):
        if facts.get(k) is not None:
            lines.append(f"- {name}: {facts[k]}{suffix}")
    add("megribi_score", "めぐりびスコア(0-1, 高いほど狙い目)")
    add("occupancy_rate", "現在の席の埋まり具合(0-1)")
    add("female_ratio", "女性比率(0-1)")
    add("latest_total", "直近の来店規模(推定・人)")
    add("forecast_peak_total", "今夜のピーク予測(推定規模)")
    add("forecast_peak_time", "ピーク予測時刻")
    lines.append(f"- データ出典: {facts.get('source')}")
    return "\n".join(lines)


SYSTEM = (
    "あなたは日本のナイトライフ情報メディア『めぐりび』の編集者です。"
    "相席ラウンジの混雑データをもとに、来店を検討する一般ユーザー向けに書きます。"
    "初めて読む人がさっと一読しただけで分かるよう、やさしい普段の言葉で簡潔に書きます。"
    "『めぐりびスコア0.08』『埋まり具合0.075』のような内部指標や 0〜1 の生の数値は本文に出さず、"
    "『空いています』『混んでいます』『ほぼ満席』『半分くらい』のように普通の言葉で言い換えます。"
    "使う数字は、時刻(例: 23時ごろ)やおおよその人数など、誰でも直感的に分かるものだけにします。"
    "誇張せず、データに無い事柄（予約の可否・待ち時間・特典など）には言及しません。"
    "出力は Markdown。1行目を『# 見出し』にし、その後に本文。前置き・言い訳・メタ発言は書かない。"
)


def prompt_weekly(store_label: str, facts: dict) -> str:
    return (
        f"次のデータは相席ラウンジ「{store_label}」の直近の混雑状況です。\n\n"
        f"{facts_block(facts, store_label)}\n\n"
        "これをもとに、今週の混雑傾向と『いつ行くと良さそうか』を、"
        "来店検討者向けに150〜250字程度でまとめた短い週次レポートを書いてください。"
        "見出し(#)から始め、数字に基づく具体的な示唆を1つ入れてください。"
    )


def prompt_compare(a_label: str, fa: dict, b_label: str, fb: dict) -> str:
    return (
        f"次は相席ラウンジ2店舗の混雑データです。\n\n"
        f"{facts_block(fa, a_label)}\n\n{facts_block(fb, b_label)}\n\n"
        f"この2店舗「{a_label}」と「{b_label}」の違いを、データに基づいて比較する"
        "ブログ記事(400〜600字)を書いてください。見出し(#)＋小見出し(##)を使い、"
        "『どちらがどんな人・シーンに向くか』の結論を必ず入れてください。数字を具体的に引用し、"
        "分からない点は断定しないこと。"
    )


def run_ollama(model: str, system: str, user: str, options: dict | None = None,
               think: bool | None = None, keep_alive: str | int = 0) -> tuple[str, float, str]:
    """Ollama /api/chat を叩く。返り値 (text, elapsed_sec, error)。

    options: 既定 (num_ctx=NUM_CTX, temperature=0.7) に上書きマージする追加オプション。
    tune_local_llm.py の計測結果 (例: num_ctx=2048 + num_gpu=999 で 13.7→24.8 tok/s) を
    呼び出し側から注入するために使う。
    think: reasoning モードの明示切替 (gemma4 等 thinking 対応モデル用)。None=モデル既定。
    レポート用途は think=False 推奨 (推論不要。ON だと思考で数千トークン消費し遅く・発熱増)。
    keep_alive: モデルのメモリ常駐時間。0=生成後すぐアンロード(既定・実験用)。
    バッチ処理では "10m" 等にして全店の間ロードを維持し、1店ごとの再ロード(8-11s)を無くす
    (終了時は unload_ollama() で明示解放すること)。"""
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
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=payload,
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
            f"{OLLAMA}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception:  # noqa: BLE001
        pass


def check_ollama() -> list[str]:
    try:
        d = _get_json(f"{OLLAMA}/api/tags", timeout=10)
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


def main() -> int:
    installed = check_ollama()
    if installed is None or installed == []:
        # 空でも接続自体は成功しているかもしれないので区別
        try:
            _get_json(f"{OLLAMA}/api/tags", timeout=5)
        except Exception:
            print("[ERROR] Ollama に接続できません (http://localhost:11434)。")
            print("        Ollama を起動してください。未インストールなら手順参照。")
            return 1
    print(f"[info] Ollama 稼働中。pull 済みモデル: {installed or '(なし)'}")

    OUT_DIR.mkdir(exist_ok=True)
    print(f"[info] 出力先: {OUT_DIR.resolve()}")

    print(f"[info] 実データ取得中: {STORE_A}, {STORE_B} ...")
    fa = fetch_store_facts(STORE_A)
    fb = fetch_store_facts(STORE_B)
    a_label = f"オリエンタルラウンジ {STORE_A}"
    b_label = f"オリエンタルラウンジ {STORE_B}"
    print(f"[info] {STORE_A} facts source={fa.get('source')} / {STORE_B} facts source={fb.get('source')}")

    tasks = [
        ("weekly", prompt_weekly(a_label, fa)),
        ("compare", prompt_compare(a_label, fa, b_label, fb)),
    ]

    # 共有GPUを掴む間は排他ロック（音楽PJと衝突させない）。gpu_lock が無ければ素通り。
    if gpu_lock is not None:
        print(f"[info] GPUロック取得中 (free VRAM: {gpu_lock.gpu_free_mb()} MiB) ...")
        lock_cm = gpu_lock.acquire(owner="meguribi-spike", timeout=900)
    else:
        print("[info] gpu_lock 未検出 → ロック無しで実行（衝突に注意）")
        lock_cm = nullcontext()

    summary = []
    with lock_cm:
        for model in MODELS:
            if installed and not any(model.split(":")[0] in m for m in installed):
                print(f"[warn] {model} が pull されていない可能性。`ollama pull {model}` を先に。スキップせず試行します。")
            for task_name, user in tasks:
                print(f"\n[run] model={model} task={task_name} ... 生成中(初回はモデルロードで時間がかかる)")
                text, elapsed, err = run_ollama(model, SYSTEM, user)
                safe_model = model.replace(":", "_").replace("/", "_")
                out = OUT_DIR / f"{task_name}__{safe_model}.md"
                header = f"<!-- model={model} task={task_name} elapsed={elapsed:.1f}s chars={len(text)} error={err or 'none'} -->\n\n"
                out.write_text(header + (text if text else f"(生成失敗: {err})"), encoding="utf-8")
                status = "OK" if text and not err else f"FAIL({err[:60]})"
                print(f"     -> {out.name}  {elapsed:.1f}s  {len(text)}字  {status}")
                summary.append((model, task_name, round(elapsed, 1), len(text), status))

    print("\n==== SUMMARY ====")
    print(f"{'model':<16}{'task':<10}{'sec':>7}{'chars':>8}  status")
    for m, t, s, c, st in summary:
        print(f"{m:<16}{t:<10}{s:>7}{c:>8}  {st}")
    print(f"\n読み比べ: {OUT_DIR.resolve()} の .md を開いて、日本語の自然さ/正確さ/構成を比較してください。")
    print("同じ task 同士（例 compare__*.md）を横並びで見るのがおすすめ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
