# -*- coding: utf-8 -*-
"""gemma4:12b ローカル生成の速度チューニング・ハーネス（自己改善用）。

目的: 品質を落とさずに daily/weekly レポート生成を速くする設定を「計測して」選ぶ。
遅さの根因: gemma4:12b は約 8.9GB で RTX 4060 の 8GB VRAM に収まらず、
約 30% が CPU 分担になり ~14 tok/s に律速される。さらに音楽プロジェクトとの
GPU 共存のため keep_alive:0（毎店モデル再ロード）で動かしており、
1 店あたり再ロード時間が丸ごと上乗せされる。

計測する設定マトリクス（既定）:
  - num_ctx 8192（現行） / 4096 / 2048  … KV キャッシュ縮小で GPU 載せ層を増やす
  - num_gpu=999 強制     … 全層 GPU 試行（失敗したら記録して続行）
  - 各設定で コールド（ロード込み）と ウォーム（常駐時）を両方計測
    → 「バッチ常駐モード」（1 ジョブ中はモデル常駐・終了時に解放）の削減効果を試算

品質ゲート: 生成文が構造チェック（# 見出し / 長さ / 禁止語なし / ですます調 /
コードフェンスなし / 文末完結）を通らない設定は、どんなに速くても採用候補から除外。

■ 過去の計測済み知見（再試行しないこと）:
  - OLLAMA_FLASH_ATTENTION=1 + KV cache q8_0 は本機では逆効果（14 → 3.4 tok/s、2026-07 計測）。
  - ollama を強制 kill すると llama-server 子プロセスが VRAM を掴んだまま残る。
    掃除は Get-Process llama-server | Stop-Process。

使い方:
  python scripts/tune_local_llm.py                 # 既定マトリクスを計測
  python scripts/tune_local_llm.py --quick         # baseline と ctx2048 のみ
  python scripts/tune_local_llm.py --models gemma4:12b,<別量子化タグ>
                                                   # 量子化 A/B（事前に ollama pull が必要）
結果: local_llm_spike_out/tuning_results.json に保存し、要約を標準出力へ表示。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

# Windows コンソール (cp932) での文字化け対策
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, r"C:\Users\Public\共有データ系")
import gpu_lock  # noqa: E402

OLLAMA = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:12b"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "local_llm_spike_out")
OUT_PATH = os.path.join(OUT_DIR, "tuning_results.json")

FORBIDDEN = ["キャバクラ", "キャスト", "指名", "同伴", "シャンパン", "ホステス"]

# 本番 (local_report_job.py) の daily プロンプトと同規模・同形式の固定プロンプト。
# ネットワークに依存しないよう、実在店舗相当の数値を静的に埋め込む。
SYSTEM_PROMPT = (
    "あなたは相席ラウンジの混雑情報サイト MEGRIBI の日次レポートライター。"
    "対象は相席ラウンジであり、キャバクラ・クラブ（接客型）ではない。"
    "キャバクラ、キャスト、指名、同伴、シャンパン、ホステスなどの語は禁止。"
    "です・ます調の落ち着いた情報記事の口調で書く。"
    "砕けた語尾（〜だね/〜よ/〜みたい/〜かもね）や営業文句、挨拶、前置きは書かない。"
)

USER_PROMPT = (
    "次のデータは相席ラウンジ「オリエンタルラウンジ 渋谷店」の現在の混雑状況と今夜の予測です。\n\n"
    "【現況】20:15 時点 混雑率 34%（男性 12 名 / 女性 9 名）\n"
    "【直近 1 時間の傾向】上昇中（+11pt）\n"
    "【今夜の予測ピーク】23:00-01:00 に 90-100%（ほぼ満席）\n"
    "【時間帯別予測】21:00: 55% / 22:00: 72% / 23:00: 91% / 00:00: 97% / 01:00: 94% / 02:00: 78%\n"
    "【曜日文脈】金曜夜。先週金曜は 23 時台にピーク 100% を記録。\n\n"
    "これをもとに、今夜これから来店を検討している人向けに、150〜300字程度の短い日次レポートを"
    "書いてください。見出し(#)から始め、今夜の混雑の見通しと『いつ頃行くと良さそうか』を"
    "数字に基づいて具体的に示唆してください。前置き・メタ発言は書かない。"
)

NS = 1e9


def _http_json(path: str, body: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def unload(model: str) -> None:
    """モデルを VRAM から降ろす（コールド計測と音楽プロジェクト共存のため）。"""
    try:
        _http_json("/api/generate", {"model": model, "keep_alive": 0, "prompt": ""}, timeout=120)
    except Exception:
        pass
    time.sleep(3)


def vram_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def processor_split(model: str) -> str | None:
    """ollama ps から CPU/GPU 分担率（例 '30%/70% CPU/GPU'）を取る。"""
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=15)
        for line in out.stdout.splitlines():
            if model.split(":")[0] in line:
                return " ".join(line.split()[-3:])
    except Exception:
        pass
    return None


def quality_check(text: str) -> tuple[bool, list[str]]:
    """本番と同じ品質基準の構造チェック。速くても品質が崩れる設定は不採用。"""
    problems: list[str] = []
    t = (text or "").strip()
    if not t:
        return False, ["empty"]
    first = t.splitlines()[0].strip()
    if not first.startswith("#"):
        problems.append("no-heading")
    body = "\n".join(t.splitlines()[1:]).strip()
    if not (100 <= len(body) <= 450):
        problems.append(f"length={len(body)}")
    if "```" in t:
        problems.append("code-fence")
    if not ("です" in t or "ます" in t):
        problems.append("not-desu-masu")
    for w in FORBIDDEN:
        if w in t:
            problems.append(f"forbidden:{w}")
    if t[-1] not in "。！？!?)）」":
        problems.append("truncated?")
    return (not problems), problems


def one_generation(model: str, options: dict, keep_alive) -> dict:
    t0 = time.time()
    d = _http_json("/api/chat", {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "stream": False,
        "keep_alive": keep_alive,
        "options": options,
    })
    wall = time.time() - t0
    text = (d.get("message") or {}).get("content", "")
    ok, problems = quality_check(text)
    return {
        "wall_s": round(wall, 1),
        "load_s": round(d.get("load_duration", 0) / NS, 1),
        "prompt_eval_s": round(d.get("prompt_eval_duration", 0) / NS, 1),
        "prompt_tokens": d.get("prompt_eval_count", 0),
        "gen_s": round(d.get("eval_duration", 0) / NS, 1),
        "gen_tokens": d.get("eval_count", 0),
        "tok_per_s": round(d.get("eval_count", 0) / max(d.get("eval_duration", 1) / NS, 1e-9), 1),
        "quality_ok": ok,
        "quality_problems": problems,
        "text": text,
    }


def bench_config(name: str, model: str, options: dict) -> dict:
    """1 設定 = アンロード → コールド 1 回 → ウォーム 1 回。"""
    print(f"\n=== {name} (model={model}, options={options}) ===")
    unload(model)
    result: dict = {"name": name, "model": model, "options": options}
    try:
        cold = one_generation(model, options, keep_alive="5m")
        result["split"] = processor_split(model)
        result["vram_mib"] = vram_used_mib()
        warm = one_generation(model, options, keep_alive="5m")
        result["cold"] = cold
        result["warm"] = warm
        result["error"] = None
        print(f"  cold: wall={cold['wall_s']}s (load={cold['load_s']}s, gen={cold['gen_s']}s, "
              f"{cold['tok_per_s']} tok/s) quality={'OK' if cold['quality_ok'] else cold['quality_problems']}")
        print(f"  warm: wall={warm['wall_s']}s ({warm['tok_per_s']} tok/s) "
              f"quality={'OK' if warm['quality_ok'] else warm['quality_problems']}")
        print(f"  split={result['split']}  vram={result['vram_mib']}MiB")
    except Exception as e:  # 設定によってはロード失敗もあり得る（num_gpu 強制など）
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  FAILED: {result['error']}")
    finally:
        unload(model)
    return result


def estimate(result: dict, n_stores: int) -> dict | None:
    """1 エディション（n_stores 店）の所要を 2 方式で試算。
    per-store: 毎店ロード（現行 keep_alive:0） / batch: ジョブ中常駐（初回のみロード）"""
    if result.get("error") or "cold" not in result:
        return None
    cold_w, warm_w = result["cold"]["wall_s"], result["warm"]["wall_s"]
    return {
        "per_store_min": round(n_stores * cold_w / 60, 1),
        "batch_min": round((cold_w + (n_stores - 1) * warm_w) / 60, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="baseline と ctx2048 のみ計測")
    ap.add_argument("--configs", default="",
                    help="カンマ区切りで matrix の設定名を絞り込む (例: ctx3072_allgpu,ctx4096_allgpu)")
    ap.add_argument("--models", default=DEFAULT_MODEL,
                    help="カンマ区切り。量子化 A/B は事前に ollama pull しておく")
    ap.add_argument("--lock-timeout", type=int, default=900)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    matrix = [
        ("baseline_ctx8192", {"num_ctx": 8192, "temperature": 0.7}),
        ("ctx4096",          {"num_ctx": 4096, "temperature": 0.7}),
        ("ctx2048",          {"num_ctx": 2048, "temperature": 0.7}),
        ("ctx2048_allgpu",   {"num_ctx": 2048, "temperature": 0.7, "num_gpu": 999}),
        # weekly はプロンプトが長い (実測 ~2300-3300 tokens) ため 2048 では頭が切れる。
        # 全 GPU 強制のまま KV をどこまで広げられるかの探索用 (2026-07-03 追加)。
        ("ctx3072_allgpu",   {"num_ctx": 3072, "temperature": 0.7, "num_gpu": 999}),
        ("ctx4096_allgpu",   {"num_ctx": 4096, "temperature": 0.7, "num_gpu": 999}),
    ]
    if args.quick:
        matrix = [matrix[0], matrix[2]]
    if args.configs:
        wanted = {c.strip() for c in args.configs.split(",") if c.strip()}
        matrix = [(n, o) for (n, o) in matrix if n in wanted]
        if not matrix:
            print(f"[tune] --configs に一致する設定なし: {sorted(wanted)}")
            return 1

    results: list[dict] = []
    print(f"[tune] GPU ロック取得待ち…（音楽プロジェクト/レポートジョブと排他）")
    with gpu_lock.acquire(owner="meguribi-tune", timeout=args.lock_timeout):
        for model in models:
            for name, options in matrix:
                cfg_name = name if model == DEFAULT_MODEL else f"{model}::{name}"
                results.append(bench_config(cfg_name, model, options))

    # ---- 集計 ----
    print("\n" + "=" * 72)
    print("設定別サマリ（daily 44店/エディション と weekly 38店 の試算・分）")
    print("=" * 72)
    baseline_est = None
    rows = []
    for r in results:
        est44 = estimate(r, 44)
        est38 = estimate(r, 38)
        q = (not r.get("error")) and r["cold"]["quality_ok"] and r["warm"]["quality_ok"]
        if r["name"].startswith("baseline") and est44:
            baseline_est = est44
        rows.append((r["name"], q, est44, est38, r))
        if r.get("error"):
            print(f"  {r['name']:24} ロード失敗（この設定は不可）")
            continue
        print(f"  {r['name']:24} 品質={'合格' if q else '不合格'}  "
              f"tok/s={r['warm']['tok_per_s']:>5}  "
              f"daily44: 毎店ロード {est44['per_store_min']}分 / 常駐 {est44['batch_min']}分  "
              f"weekly38: 常駐 {est38['batch_min']}分")

    candidates = [(n, e44, r) for (n, q, e44, _, r) in rows if q and e44]
    reco = min(candidates, key=lambda x: x[1]["batch_min"]) if candidates else None

    payload = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
        "recommended": (
            {
                "name": reco[0],
                "model": reco[2]["model"],
                "options": reco[2]["options"],
                "daily44_batch_min": reco[1]["batch_min"],
                "note": "品質ゲート合格のうち常駐モード試算が最速の設定",
            } if reco else None
        ),
        "baseline_daily44": baseline_est,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[tune] 詳細を保存: {OUT_PATH}")
    if reco and baseline_est:
        print(f"[tune] 推奨: {reco[0]}  daily 1エディション {baseline_est['per_store_min']}分"
              f" → 常駐 {reco[1]['batch_min']}分")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
